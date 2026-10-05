"""PII: ninguna corrida deja emails, nombres ni credenciales en los logs (FR-020, SC-007)."""

from __future__ import annotations

import logging

import pytest

from recos_auto.cron.api_general import ApiGeneral
from recos_auto.cron.corrida import ejecutar_corrida

pytestmark = pytest.mark.integration


class _Publicador:
    def publicar(self, mensaje):
        pass


def test_los_logs_no_contienen_pii(config, api_mock_factory, caplog):
    mock = api_mock_factory(cantidad=10)
    api = ApiGeneral(config, transport=mock.transporte())
    with caplog.at_level(logging.DEBUG):
        ejecutar_corrida(config, api, _Publicador())
    texto = " ".join(r.getMessage() + " " + str(getattr(r, "campos", "")) for r in caplog.records)
    assert "@" not in texto
    assert config.api_general_api_key not in texto
    assert config.rabbitmq_url not in texto
