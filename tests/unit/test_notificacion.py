"""Notificación: id_mensaje determinístico, contenido y contrato (T008, T010)."""

import json
import uuid
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from recos_auto.common.mensajes import MensajeUsuario, message_id_para
from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.notificacion import Notificacion, armar_notificacion, id_mensaje_para
from recos_auto.worker.recomendaciones import Recomendacion

BASE = {
    "API_GENERAL_BASE_URL": "http://api.test/api/v1",
    "API_GENERAL_API_KEY": "local.clave-secreta",
    "RABBITMQ_URL": "amqp://usuario:secreto@rabbit.test:5672/",
}
SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "specs/002-worker-recomendaciones/contracts/mensaje-notificacion.schema.json"
    ).read_text()
)
LIMITE = 2**63 - 1


def _mensaje(user_id=5, modulo="peliculas", fecha=date(2026, 10, 6), idioma="es", nombre="Ana"):
    return MensajeUsuario(
        message_id=message_id_para(user_id, fecha, modulo),
        corrida_id="c1",
        fecha=fecha,
        modulo=modulo,
        recommendation_id=uuid.UUID(int=user_id),
        user_id=user_id,
        nombre=nombre,
        email=f"u{user_id}@example.com",
        idioma=idioma,
    )


def _rec(titulo="Matrix", modulo="peliculas", rid=5):
    return Recomendacion(
        recommendation_id=uuid.UUID(int=rid),
        item_id=uuid.UUID(int=99),
        module=modulo,
        titulo=titulo,
        position=1,
    )


def _cfg(**extra):
    return ConfigWorker.from_env(dict(BASE, **extra))


def test_id_mensaje_es_determinista_positivo_y_de_63_bits():
    mid = message_id_para(5, date(2026, 10, 6), "peliculas")
    assert id_mensaje_para(mid) == id_mensaje_para(mid)
    assert 1 <= id_mensaje_para(mid) <= LIMITE


def test_id_mensaje_distingue_usuario_fecha_y_modulo():
    ids = {
        id_mensaje_para(message_id_para(u, f, m))
        for u in range(1, 200)
        for f in (date(2026, 10, 6), date(2026, 10, 7))
        for m in ("peliculas", "juegos")
    }
    assert len(ids) == 199 * 2 * 2


def test_id_mensaje_nunca_es_cero():
    assert id_mensaje_para(uuid.UUID(int=0)) == 1
    assert id_mensaje_para(uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")) <= LIMITE


def test_contenido_por_defecto_peliculas():
    n = armar_notificacion(_mensaje(modulo="peliculas"), _rec(), _cfg())
    assert n.canal == "mail"
    assert n.contenido.titulo == "Tu recomendación de hoy: Matrix"
    assert "una película" in n.contenido.cuerpo
    assert "Matrix" in n.contenido.cuerpo
    assert f"https://recome.example/peliculas/{uuid.UUID(int=99)}" in n.contenido.cuerpo


def test_contenido_por_defecto_juegos():
    n = armar_notificacion(_mensaje(modulo="juegos"), _rec(titulo="Zelda", modulo="juegos"), _cfg())
    assert "un juego" in n.contenido.cuerpo
    assert "película" not in n.contenido.cuerpo
    assert "/juegos/" in n.contenido.cuerpo


def test_mail_y_destinatario_salen_del_mismo_mensaje():
    mensaje = _mensaje(user_id=42)
    n = armar_notificacion(mensaje, _rec(rid=42), _cfg())
    assert n.mail == mensaje.email
    assert n.destinatario == mensaje.user_id == 42
    assert n.id_mensaje == id_mensaje_para(mensaje.message_id)


def test_el_idioma_se_ignora():
    a = armar_notificacion(_mensaje(idioma="en"), _rec(), _cfg())
    b = armar_notificacion(_mensaje(idioma=None), _rec(), _cfg())
    c = armar_notificacion(_mensaje(idioma="es"), _rec(), _cfg())
    assert a.contenido == b.contenido == c.contenido


def test_el_cuerpo_por_defecto_no_contiene_el_nombre():
    n = armar_notificacion(_mensaje(nombre="Ana Maria Perez"), _rec(), _cfg())
    assert "Ana" not in n.contenido.cuerpo
    assert "Perez" not in n.contenido.titulo


def test_titulo_con_llaves_y_marcado_no_rompe_las_plantillas():
    n = armar_notificacion(_mensaje(), _rec(titulo="{x} <b>Ñandú</b> {0}"), _cfg())
    assert "{x} <b>Ñandú</b> {0}" in n.contenido.titulo


def test_plantillas_configurables():
    cfg = _cfg(
        NOTIF_TITULO_TEMPLATE="Hoy: {titulo} ({modulo})",
        NOTIF_CUERPO_TEMPLATE="{que_es} -> {url}",
        NOTIF_URL_TEMPLATE="https://x.test/{modulo}/{item_id}",
    )
    n = armar_notificacion(_mensaje(), _rec(), cfg)
    assert n.contenido.titulo == "Hoy: Matrix (película)"
    assert n.contenido.cuerpo == f"una película -> https://x.test/peliculas/{uuid.UUID(int=99)}"


def test_notificacion_valida_contra_el_schema():
    n = armar_notificacion(_mensaje(), _rec(), _cfg())
    jsonschema.validate(n.model_dump(mode="json"), SCHEMA)


@pytest.mark.parametrize(
    "roto",
    [
        {"canal": "push"},
        {"mail": None},
        {"extra": 1},
        {"id_mensaje": 0},
        {"destinatario": 0},
    ],
)
def test_el_schema_rechaza_notificaciones_invalidas(roto):
    base = armar_notificacion(_mensaje(), _rec(), _cfg()).model_dump(mode="json")
    datos = {**base, **roto}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(datos, SCHEMA)


def test_el_schema_exige_el_mail():
    base = armar_notificacion(_mensaje(), _rec(), _cfg()).model_dump(mode="json")
    del base["mail"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(base, SCHEMA)


def test_el_modelo_prohibe_campos_extra():
    with pytest.raises(ValueError):
        Notificacion.model_validate(
            {
                "id_mensaje": 1,
                "destinatario": 1,
                "mail": "a@b.co",
                "contenido": {"titulo": "t", "cuerpo": "c"},
                "adjunto": {},
            }
        )
