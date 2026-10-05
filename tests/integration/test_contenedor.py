"""Imagen del cron: config inválida, disparo programado y apagado ordenado (FR-024, SC-003)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.contenedor]

RAIZ = Path(__file__).resolve().parents[2]
IMAGEN = "recos-auto-cron:test"
CLAVE = "local.clave-de-prueba"


def _docker(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kw)


@pytest.fixture(scope="module")
def imagen():
    if shutil.which("docker") is None:
        pytest.skip("docker no disponible")
    r = _docker("build", "-q", "-t", IMAGEN, "-f", str(RAIZ / "docker/cron/Dockerfile"), str(RAIZ))
    if r.returncode != 0:
        pytest.skip(f"no se pudo construir la imagen: {r.stderr[-200:]}")


@pytest.fixture
def api_simulada():
    puerto = 18080 + int(uuid.uuid4().int % 500)
    proc = subprocess.Popen(
        [
            sys.executable,
            str(RAIZ / "docker/mock-api-general/server.py"),
            "--port",
            str(puerto),
            "--users",
            "5",
            "--key",
            CLAVE,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    yield puerto
    proc.terminate()
    proc.wait(5)


def _env(puerto: int, cola: str, **extra: str) -> list[str]:
    valores = {
        "API_GENERAL_BASE_URL": f"http://127.0.0.1:{puerto}/api/v1",
        "API_GENERAL_API_KEY": CLAVE,
        "RABBITMQ_URL": "amqp://guest:guest@127.0.0.1:5672/%2F",
        "RABBITMQ_USERS_QUEUE": cola,
        **extra,
    }
    return [a for k, v in valores.items() for a in ("-e", f"{k}={v}")]


def test_sin_variables_sale_con_78(imagen):
    r = _docker("run", "--rm", IMAGEN)
    assert r.returncode == 78
    assert "API_GENERAL_API_KEY" in r.stderr


def test_arranque_no_ejecuta_corrida_y_apaga_ordenado(imagen, api_simulada):
    nombre = f"recos-cron-{uuid.uuid4().hex[:6]}"
    cola = f"test.contenedor.{uuid.uuid4().hex[:6]}"
    r = _docker(
        "run",
        "-d",
        "--name",
        nombre,
        "--network",
        "host",
        *_env(api_simulada, cola, RUN_SCHEDULE="0 3 1 1 *"),
        IMAGEN,
    )
    if r.returncode != 0:
        pytest.skip(r.stderr)
    try:
        time.sleep(3)
        logs = _docker("logs", nombre)
        salida = logs.stdout + logs.stderr
        assert "bootstrap_ok" in salida
        assert "corrida_iniciada" not in salida
        assert CLAVE not in salida
        t0 = time.monotonic()
        _docker("stop", "-t", "30", nombre)
        assert time.monotonic() - t0 < 10
        codigo = _docker("inspect", "-f", "{{.State.ExitCode}}", nombre).stdout.strip()
        assert codigo in {"0", "143"}
    finally:
        _docker("rm", "-f", nombre)


def test_run_manual_publica_y_sale_0(imagen, api_simulada):
    cola = f"test.contenedor.{uuid.uuid4().hex[:6]}"
    r = _docker(
        "run",
        "--rm",
        "--network",
        "host",
        "--entrypoint",
        "python",
        *_env(api_simulada, cola),
        IMAGEN,
        "-m",
        "recos_auto.cron",
        "run",
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
