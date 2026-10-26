from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from recos_auto.common.mensajes import UsuarioDestinatario, construir_mensaje

RAIZ = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (RAIZ / "specs/001-cron-carga-usuarios/contracts/mensaje-usuario.schema.json").read_text()
)
USUARIO = {
    "recommendation_id": "3f2b8c1e-5a4d-4c53-9f0a-1d2e3f4a5b6c",
    "user_id": 42,
    "nombre": "Ana",
    "email": "ana@example.com",
    "idioma": None,
}


def _cuerpo(**cambios) -> dict:
    usuario = UsuarioDestinatario.model_validate(dict(USUARIO, **cambios))
    return construir_mensaje(usuario, "corrida1", date(2026, 10, 5), "peliculas").model_dump(
        mode="json"
    )


def test_el_mensaje_valida_contra_el_schema():
    jsonschema.validate(_cuerpo(), SCHEMA)


def test_el_mensaje_con_idioma_valida_contra_el_schema():
    jsonschema.validate(_cuerpo(idioma="es"), SCHEMA)


def test_el_schema_rechaza_campos_extra_y_faltantes():
    cuerpo = _cuerpo()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(cuerpo, extra=1), SCHEMA)
    faltante = {k: v for k, v in cuerpo.items() if k != "email"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(faltante, SCHEMA)


def test_el_schema_rechaza_modulo_desconocido():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(_cuerpo(), modulo="libros"), SCHEMA)
