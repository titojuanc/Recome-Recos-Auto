"""Invariantes transversales con todos los modos de fallo activos (SC-003, FR-014, FR-021)."""

import json
import os
import uuid
from pathlib import Path

import httpx
import jsonschema
import pytest

from tests.integration.test_worker_flujo import ApiRecos, Arnes, _esperar

pytestmark = pytest.mark.integration

RAIZ = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (
        RAIZ / "specs/002-worker-recomendaciones/contracts/mensaje-notificacion.schema.json"
    ).read_text()
)
OMITIR = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def _archivos() -> set[str]:
    visto = set()
    for base, dirs, nombres in os.walk(RAIZ):
        dirs[:] = [d for d in dirs if d not in OMITIR]
        visto.update(os.path.join(base, n) for n in nombres)
    return visto


class ApiMezclada(ApiRecos):
    """usuario % 4: 0 -> 404, 1 -> 400, 2 -> 503 la primera vez, 3 -> ok."""

    def __init__(self):
        super().__init__()
        self._vistos: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        rid = request.url.path.rsplit("/", 1)[-1]
        resto = uuid.UUID(rid).int % 4
        if resto == 0:
            return httpx.Response(404)
        if resto == 1:
            return httpx.Response(400)
        if resto == 2 and rid not in self._vistos:
            self._vistos.add(rid)
            return httpx.Response(503)
        return super().__call__(request)


def test_invariantes_con_todos_los_fallos(
    config_worker, conexion_rabbit, publicar_usuarios, leer_cola, profundidad
):
    antes = _archivos()
    publicar_usuarios(40)
    canal = conexion_rabbit.channel()
    canal.basic_publish("", config_worker.users_queue, b"basura")  # mensaje malformado
    canal.close()

    with Arnes(config_worker, ApiMezclada(), hilos=3) as arnes:

        def terminado():
            s = arnes.contadores.snapshot()
            return s["notificados"] + s["sin_recomendacion"] + s["invalidos"] == 41

        assert _esperar(terminado, timeout=30)

    salidas = leer_cola(config_worker.notificaciones_queue)
    # (a) SC-003: solo notificaciones completas y válidas, una por usuario
    for s in salidas:
        jsonschema.validate(s, SCHEMA)
    assert len({s["id_mensaje"] for s in salidas}) == len(salidas) == 20
    # (c) FR-021: nada se pierde en silencio
    c = arnes.contadores.snapshot()
    assert c["notificados"] == 20
    assert c["sin_recomendacion"] == 10
    assert c["invalidos"] == 11  # 10 por 400 + 1 malformado
    assert c["recibidos"] == (
        c["notificados"] + c["sin_recomendacion"] + c["invalidos"] + c["reintentados"]
    )
    assert profundidad(config_worker.users_queue) == 0
    assert profundidad(config_worker.dead_letter_queue) == 11
    # (b) FR-014: no quedaron archivos nuevos con datos de usuario
    assert _archivos() == antes
