from __future__ import annotations

import io
import json
import logging

import pytest

from recos_auto.common.logs import configurar_logs, evento


@pytest.fixture
def salida():
    flujo = io.StringIO()
    configurar_logs("INFO", flujo=flujo)
    yield flujo
    logging.getLogger().handlers.clear()


def _lineas(flujo: io.StringIO) -> list[dict]:
    return [json.loads(linea) for linea in flujo.getvalue().splitlines() if linea.strip()]


def test_una_linea_json_por_evento(salida):
    log = logging.getLogger("recos_auto.test")
    evento(log, "corrida_iniciada", corrida_id="abc", modulo="juegos")
    [linea] = _lineas(salida)
    assert linea["evento"] == "corrida_iniciada"
    assert linea["corrida_id"] == "abc"
    assert linea["modulo"] == "juegos"
    assert linea["level"] == "INFO"
    assert "ts" in linea


def test_no_emite_pii_en_campos(salida):
    log = logging.getLogger("recos_auto.test")
    evento(log, "usuario_omitido", user_id=7, email="ana@example.com", nombre="Ana López")
    texto = salida.getvalue()
    assert "ana@example.com" not in texto
    assert "Ana López" not in texto
    assert _lineas(salida)[0]["user_id"] == 7


def test_no_emite_pii_en_el_texto_libre(salida):
    log = logging.getLogger("recos_auto.test")
    log.error("falló el envío a ana@example.com con amqp://usuario:secreto@rabbit:5672/")
    texto = salida.getvalue()
    assert "ana@example.com" not in texto
    assert "secreto" not in texto


@pytest.mark.parametrize("clave", ["api_key", "API_GENERAL_API_KEY", "rabbitmq_url", "password"])
def test_redacta_campos_secretos(salida, clave):
    log = logging.getLogger("recos_auto.test")
    evento(log, "bootstrap_ok", **{clave: "valor-super-secreto"})
    assert "valor-super-secreto" not in salida.getvalue()


def test_no_emite_pii_en_excepciones(salida):
    log = logging.getLogger("recos_auto.test")
    try:
        raise ValueError("falló para ana@example.com")
    except ValueError:
        log.exception("error")
    assert "ana@example.com" not in salida.getvalue()


def test_silencia_pika_y_httpx(salida):
    assert logging.getLogger("pika").level >= logging.WARNING
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_acepta_acentos_y_emojis_en_campos_permitidos(salida):
    log = logging.getLogger("recos_auto.test")
    evento(log, "x", motivo="módulo ✔")
    assert _lineas(salida)[0]["motivo"] == "módulo ✔"
