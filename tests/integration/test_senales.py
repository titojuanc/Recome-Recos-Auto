"""SIGTERM sobre el proceso real: termina ordenadamente y registra la corrida como interrumpida."""

from __future__ import annotations

import json
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

RAIZ = Path(__file__).resolve().parents[2]
CLAVE = "local.clave-de-prueba"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _esperar_puerto(puerto: int, segundos: float = 10.0) -> None:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", puerto)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError("la api-general simulada no arrancó")


@pytest.fixture
def api_simulada():
    puerto = _puerto_libre()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(RAIZ / "docker/mock-api-general/server.py"),
            "--port",
            str(puerto),
            "--users",
            "40",
            "--delay",
            "0.5",
            "--key",
            CLAVE,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _esperar_puerto(puerto)
    yield puerto
    proc.terminate()
    proc.wait(timeout=5)


def _lector(proc: subprocess.Popen) -> queue.Queue:
    cola: queue.Queue = queue.Queue()

    def leer():
        for linea in proc.stdout:
            cola.put(linea)
        cola.put(None)

    threading.Thread(target=leer, daemon=True).start()
    return cola


def _vaciar(canal, cola: str, esperados: int, segundos: float = 10.0) -> int:
    cantidad = 0
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        metodo, _, _ = canal.basic_get(cola, auto_ack=True)
        if metodo:
            cantidad += 1
            continue
        if cantidad >= esperados:
            break
        time.sleep(0.2)
    return cantidad


def test_sigterm_interrumpe_la_corrida_y_sale_con_codigo_1(
    api_simulada, config_rabbit, conexion_rabbit, tmp_path
):
    env = dict(
        os.environ,
        PYTHONPATH=str(RAIZ / "src"),
        API_GENERAL_BASE_URL=f"http://127.0.0.1:{api_simulada}/api/v1",
        API_GENERAL_API_KEY=CLAVE,
        RABBITMQ_URL=config_rabbit.rabbitmq_url,
        RABBITMQ_USERS_QUEUE=config_rabbit.users_queue,
        API_GENERAL_PAGE_SIZE="5",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "recos_auto.cron", "run"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lineas = _lector(proc)
    salida: list[str] = []
    try:
        # Esperar a que lea la primera página y entonces pedir el apagado.
        while True:
            linea = lineas.get(timeout=20)
            assert linea is not None, f"el proceso terminó antes de tiempo: {salida}"
            salida.append(linea)
            if '"pagina_leida"' in linea:
                break
        proc.send_signal(signal.SIGTERM)
        codigo = proc.wait(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
    while (linea := lineas.get(timeout=5)) is not None:
        salida.append(linea)

    eventos = [json.loads(x) for x in salida if x.startswith("{")]
    nombres = [e["evento"] for e in eventos]
    assert codigo == 1
    assert "corrida_interrumpida" in nombres
    assert nombres[-1] == "corrida_finalizada"
    final = eventos[-1]
    assert final["resultado"] == "interrumpida"
    assert final["publicados"] < 40
    assert final["recibidos"] == final["publicados"] + final["omitidos"] + final["repetidos"]
    # Lo que figura como publicado está realmente en la cola.
    assert (
        _vaciar(conexion_rabbit.channel(), config_rabbit.users_queue, final["publicados"])
        == (final["publicados"])
    )
    # Ninguna línea contiene datos personales.
    assert "@example.com" not in "".join(salida)
