"""`python -m recos_auto.worker`: N hilos consumidores (WORKER_CONCURRENCY) y apagado ordenado."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time

import pika

from recos_auto.common.config import ConfigError
from recos_auto.common.logs import configurar_logs, evento
from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.consumidor import Consumidor
from recos_auto.worker.contadores import Contadores
from recos_auto.worker.interruptor import Interruptor
from recos_auto.worker.recomendaciones import ClienteRecomendaciones

EXIT_OK = 0
EXIT_APAGADO_FORZADO = 75
EXIT_CONFIG = 78
log = logging.getLogger("recos_auto.worker")


def _pendientes(cfg: ConfigWorker) -> int | None:
    """Mensajes en la cola de entrada (consulta pasiva); None si no se pudo consultar."""
    try:
        conexion = pika.BlockingConnection(pika.URLParameters(cfg.rabbitmq_url))
        try:
            canal = conexion.channel()
            return canal.queue_declare(queue=cfg.users_queue, passive=True).method.message_count
        finally:
            conexion.close()
    except Exception:  # noqa: BLE001 - es solo informativo
        return None


def _resumen(cfg: ConfigWorker, contadores: Contadores, interruptor: Interruptor) -> None:
    evento(
        log,
        "resumen",
        logging.INFO,
        pendientes=_pendientes(cfg),
        interruptor=interruptor.estado,
        **contadores.resumen(),
    )


def _bucle_resumen(cfg, contadores, interruptor, parar: threading.Event) -> None:
    while not parar.wait(cfg.summary_interval_s):
        _resumen(cfg, contadores, interruptor)


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
    threading.Thread(
        target=_bucle_resumen, args=(cfg, contadores, interruptor, parar), daemon=True
    ).start()

    codigo = EXIT_OK
    try:
        while any(h.is_alive() for h in hilos) and not parar.is_set():
            parar.wait(0.5)
        # Apagado: cada hilo termina el mensaje en curso; esperamos hasta SHUTDOWN_TIMEOUT_S.
        limite = time.monotonic() + cfg.shutdown_timeout_s
        for hilo in hilos:
            hilo.join(timeout=max(0.0, limite - time.monotonic()))
        if any(h.is_alive() for h in hilos):
            codigo = EXIT_APAGADO_FORZADO
            evento(log, "apagado_forzado", logging.ERROR)
    finally:
        parar.set()
        cliente.cerrar()
    _resumen(cfg, contadores, interruptor)
    evento(log, "worker_detenido", logging.INFO, codigo=codigo)
    return codigo


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
