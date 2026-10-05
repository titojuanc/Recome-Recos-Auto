from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from recos_auto.common.mensajes import (
    MensajeUsuario,
    UsuarioDestinatario,
    construir_mensaje,
    message_id_para,
)

USUARIO = {
    "recommendation_id": "3f2b8c1e-5a4d-4c53-9f0a-1d2e3f4a5b6c",
    "user_id": 42,
    "nombre": "Ana",
    "email": "ana@example.com",
    "idioma": "es",
}


def test_message_id_es_deterministico():
    a = message_id_para(42, date(2026, 10, 5), "peliculas")
    b = message_id_para(42, date(2026, 10, 5), "peliculas")
    assert a == b
    assert isinstance(a, uuid.UUID)
    assert a.version == 5


@pytest.mark.parametrize(
    ("user_id", "fecha", "modulo"),
    [
        (43, date(2026, 10, 5), "peliculas"),
        (42, date(2026, 10, 6), "peliculas"),
        (42, date(2026, 10, 5), "juegos"),
    ],
)
def test_message_id_cambia_con_cada_componente(user_id, fecha, modulo):
    base = message_id_para(42, date(2026, 10, 5), "peliculas")
    assert message_id_para(user_id, fecha, modulo) != base


def test_construir_mensaje_completo():
    usuario = UsuarioDestinatario.model_validate(USUARIO)
    msg = construir_mensaje(usuario, corrida_id="c1", fecha=date(2026, 10, 5), modulo="peliculas")
    assert msg.version == 1
    assert msg.message_id == message_id_para(42, date(2026, 10, 5), "peliculas")
    cuerpo = msg.model_dump(mode="json")
    assert cuerpo["fecha"] == "2026-10-05"
    assert cuerpo["modulo"] == "peliculas"
    assert cuerpo["user_id"] == 42
    assert cuerpo["idioma"] == "es"
    assert isinstance(cuerpo["message_id"], str)


def test_idioma_es_opcional():
    sin_idioma = {k: v for k, v in USUARIO.items() if k != "idioma"}
    usuario = UsuarioDestinatario.model_validate(sin_idioma)
    assert usuario.idioma is None


@pytest.mark.parametrize("campo", ["recommendation_id", "user_id", "nombre", "email"])
def test_campos_obligatorios(campo):
    datos = {k: v for k, v in USUARIO.items() if k != campo}
    with pytest.raises(ValidationError):
        UsuarioDestinatario.model_validate(datos)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("user_id", 0),
        ("user_id", -1),
        ("recommendation_id", "no-es-uuid"),
        ("email", "sin-arroba"),
        ("nombre", "   "),
    ],
)
def test_valores_invalidos(campo, valor):
    with pytest.raises(ValidationError):
        UsuarioDestinatario.model_validate(dict(USUARIO, **{campo: valor}))


def test_nombres_con_acentos_y_emojis_intactos():
    nombre = "José Ñandú 🎬"
    usuario = UsuarioDestinatario.model_validate(dict(USUARIO, nombre=nombre))
    msg = construir_mensaje(usuario, "c1", date(2026, 10, 5), "juegos")
    assert msg.model_dump(mode="json")["nombre"] == nombre


def test_modulo_invalido_rechazado():
    usuario = UsuarioDestinatario.model_validate(USUARIO)
    with pytest.raises(ValidationError):
        construir_mensaje(usuario, "c1", date(2026, 10, 5), "libros")


def test_mensaje_no_admite_campos_extra():
    cuerpo = construir_mensaje(
        UsuarioDestinatario.model_validate(USUARIO), "c1", date(2026, 10, 5), "juegos"
    ).model_dump(mode="json")
    cuerpo["extra"] = 1
    with pytest.raises(ValidationError):
        MensajeUsuario.model_validate(cuerpo)
