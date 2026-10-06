"""Rendimiento (SC-005): 10 000 mensajes con latencia simulada de la API, 0 duplicados.

Latencia máxima tolerable por llamada con N hilos: 7200 s * N / 10 000 mensajes.
Con 4 hilos (por defecto) son ~2,9 s por llamada; con 8 hilos, ~5,7 s.
"""

import time

import httpx
import pytest

from recos_auto.worker.consumidor import Consumidor  # noqa: F401
from tests.integration.test_worker_flujo import ApiRecos, Arnes, _esperar

pytestmark = [pytest.mark.integration, pytest.mark.lento]

TOTAL = 10_000
LATENCIA_S = 0.005
DOS_HORAS_S = 7200


class ApiLenta(ApiRecos):
    def __call__(self, request: httpx.Request) -> httpx.Response:
        time.sleep(LATENCIA_S)
        return super().__call__(request)


def test_diez_mil_mensajes_en_menos_de_dos_horas_sin_duplicados(
    config_worker, publicar_usuarios, leer_cola
):
    publicar_usuarios(TOTAL)
    inicio = time.monotonic()
    with Arnes(config_worker, ApiLenta(), hilos=8) as arnes:
        assert _esperar(
            lambda: arnes.contadores.snapshot()["notificados"] == TOTAL, timeout=DOS_HORAS_S
        )
    duracion = time.monotonic() - inicio
    salidas = leer_cola(config_worker.notificaciones_queue)
    assert len(salidas) == TOTAL
    assert len({s["id_mensaje"] for s in salidas}) == TOTAL
    assert duracion < DOS_HORAS_S
    print(f"\n{TOTAL} mensajes en {duracion:.1f} s con {LATENCIA_S * 1000:.0f} ms por llamada")
