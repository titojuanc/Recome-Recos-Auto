"""Reconexión (FR-015, SC-008): el broker cierra las conexiones y el worker retoma solo."""

import base64
import json
import time
import urllib.parse
import urllib.request

import pytest

from tests.integration.test_worker_flujo import ApiRecos, Arnes, _esperar

pytestmark = pytest.mark.integration

API_MGMT = "http://localhost:15672/api"


def _mgmt(ruta: str, metodo: str = "GET"):
    req = urllib.request.Request(f"{API_MGMT}{ruta}", method=metodo)
    req.add_header("Authorization", "Basic " + base64.b64encode(b"guest:guest").decode())
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
        cuerpo = r.read()
    return json.loads(cuerpo) if cuerpo else None


def _nombres() -> set[str]:
    return {c["name"] for c in _mgmt("/connections")}


def _cerrar_conexiones_ajenas(propias: set[str]) -> int:
    """Cierra desde el broker todas las conexiones salvo las del propio test."""
    cerradas = 0
    for c in _mgmt("/connections"):
        if c["name"] not in propias:
            _mgmt(f"/connections/{urllib.parse.quote(c['name'], safe='')}", "DELETE")
            cerradas += 1
    return cerradas


def test_el_worker_reconecta_y_retoma_sin_duplicar(
    config_worker, conexion_rabbit, publicar_usuarios, leer_cola
):
    try:
        _mgmt("/overview")
    except Exception:
        pytest.skip("API de administración de RabbitMQ no disponible")

    publicar_usuarios(3)
    # la API de administración refresca sus estadísticas cada ~5 s
    assert _esperar(lambda: _nombres(), timeout=20)
    propias = _nombres()
    with Arnes(config_worker, ApiRecos(), hilos=2) as arnes:
        assert _esperar(lambda: arnes.contadores.snapshot()["notificados"] == 3)
        assert _esperar(lambda: len(_nombres() - propias) >= 1, timeout=20)
        assert _cerrar_conexiones_ajenas(propias) >= 1
        time.sleep(0.5)
        publicar_usuarios(3, desde=4)
        assert _esperar(lambda: arnes.contadores.snapshot()["notificados"] == 6, timeout=30)
    salidas = leer_cola(config_worker.notificaciones_queue)
    assert len({s["id_mensaje"] for s in salidas}) == 6
    assert sorted(s["destinatario"] for s in salidas) == [1, 2, 3, 4, 5, 6]
