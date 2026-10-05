"""Proceso real del worker: config inválida, SIGTERM y logs sin datos personales (US4)."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import URL_RABBIT_TEST

RAIZ = Path(__file__).resolve().parents[2]


def _entorno(extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("API_", "RABBITMQ_"))}
    env["PYTHONPATH"] = str(RAIZ / "src")
    env.update(extra)
    return env


def _lanzar(env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "recos_auto.worker"],
        env=env,
        cwd=RAIZ,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_config_faltante_sale_con_78_sin_filtrar_secretos():
    proceso = _lanzar(_entorno({"API_GENERAL_API_KEY": "clave-super-secreta"}))
    _, err = proceso.communicate(timeout=20)
    assert proceso.returncode == 78
    assert "RABBITMQ_URL" in err
    assert "clave-super-secreta" not in err


@pytest.mark.integration
def test_sigterm_apaga_en_orden_y_los_logs_no_tienen_pii(
    config_worker, publicar_usuarios, profundidad
):
    from tests.integration.test_worker_flujo import ApiRecos  # noqa: F401  (mismo mock)

    publicar_usuarios(3)
    env = _entorno(
        {
            "API_GENERAL_BASE_URL": "http://127.0.0.1:9/api/v1",  # puerto cerrado: transitorio
            "API_GENERAL_API_KEY": "clave-super-secreta",
            "RABBITMQ_URL": URL_RABBIT_TEST,
            "RABBITMQ_USERS_QUEUE": config_worker.users_queue,
            "RABBITMQ_QUEUE_NOTIFICACIONES": config_worker.notificaciones_queue,
            "WORKER_CONCURRENCY": "2",
            "WORKER_POLL_S": "0.1",
            "BREAKER_BACKOFF_S": "0.2",
        }
    )
    proceso = _lanzar(env)
    time.sleep(3)
    proceso.send_signal(signal.SIGTERM)
    salida, err = proceso.communicate(timeout=30)
    assert proceso.returncode == 0
    texto = salida + err
    assert "worker_detenido" in texto
    for secreto in ("clave-super-secreta", "u1@example.com", "Usuario 1", "secreto"):
        assert secreto not in texto
    for linea in filter(None, texto.splitlines()):
        json.loads(linea)  # todo log es JSON
    # Nada se perdió: los 3 mensajes siguen en la cola (retenidos o devueltos) y no hay DLQ.
    assert profundidad(config_worker.users_queue) == 3
    assert profundidad(config_worker.dead_letter_queue) == 0
