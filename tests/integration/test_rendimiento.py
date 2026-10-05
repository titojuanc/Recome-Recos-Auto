"""Rendimiento: 10 000 usuarios en menos de 15 minutos (SC-002). Marcada `lento`."""

from __future__ import annotations

import time

import pytest

from recos_auto.cron.api_general import ApiGeneral
from recos_auto.cron.corrida import ejecutar_corrida

pytestmark = [pytest.mark.integration, pytest.mark.lento]


class _Publicador:
    def __init__(self):
        self.n = 0

    def publicar(self, mensaje):
        self.n += 1


def test_diez_mil_usuarios_en_menos_de_15_minutos(config, api_mock_factory):
    mock = api_mock_factory(cantidad=10_000)
    api = ApiGeneral(config, transport=mock.transporte())
    pub = _Publicador()
    t0 = time.monotonic()
    ejecutar_corrida(config, api, pub)
    assert pub.n == 10_000
    assert time.monotonic() - t0 < 15 * 60
