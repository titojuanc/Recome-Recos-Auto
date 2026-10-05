"""`python -m recos_auto.worker`: N hilos consumidores (WORKER_CONCURRENCY) y apagado ordenado."""

from __future__ import annotations

import logging
import signal
import sys
import threading

from recos_auto.common.config import ConfigError
from recos_auto.common.logs import configurar_logs, evento
from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.consumidor import Consumidor
from recos_auto.worker.contadores import Contadores
from recos_auto.worker.interruptor import Interruptor
from recos_auto.worker.recomendaciones import ClienteRecomendaciones

EXIT_OK = 0
EXIT_CONFIG = 78
log = logging.getLogger("recos_auto.worker")


def ejecutar(
    cfg: ConfigWorker, parar: threading.Event, contadores: Contadores | None = None
) -> int:
    contadores = contadores or Contadores()
    interruptor = Interruptor(
        cfg.breaker_failures, cfg.breaker_backoff_s, cfg.breaker_backoff_max_s
    )
    cliente = ClienteRecomendaciones(cfg)
    hilos = [
        threading.Thread(
            target=Consumidor(
                cfg, cliente, interruptor, contadores, parar, nombre=f"worker-{i + 1}"
            ).run,
            name=f"worker-{i + 1}",
            daemon=True,
        )
        for i in range(cfg.concurrency)
    ]
    evento(log, "worker_iniciado", logging.INFO, concurrencia=cfg.concurrency)
    for hilo in hilos:
        hilo.start()
    try:
        for hilo in hilos:
            while hilo.is_alive():
                hilo.join(timeout=0.5)
    finally:
        parar.set()
        cliente.cerrar()
    evento(log, "worker_detenido", logging.INFO, **contadores.snapshot())
    return EXIT_OK


def main() -> int:
    try:
        cfg = ConfigWorker.from_env()
    except ConfigError as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    configurar_logs(cfg.log_level)
    parar = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: parar.set())
    return ejecutar(cfg, parar)


if __name__ == "__main__":
    sys.exit(main())
