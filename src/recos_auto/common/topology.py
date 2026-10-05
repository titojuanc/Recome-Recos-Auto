"""Topología de RabbitMQ: única fuente de verdad, compartida con el worker (feature 002).

Declarar la cola con argumentos distintos a los existentes falla con 406 PRECONDITION_FAILED,
por eso cron y worker deben usar exactamente esta función.
"""

from __future__ import annotations

from typing import Any

from recos_auto.common.config import Config


def argumentos_cola_usuarios(cfg: Config) -> dict[str, Any]:
    return {
        "x-queue-type": "quorum",
        "x-dead-letter-exchange": cfg.dead_letter_exchange,
        "x-delivery-limit": cfg.delivery_limit,
        "x-message-ttl": cfg.users_message_ttl_ms,
    }


def argumentos_dead_letter(cfg: Config) -> dict[str, Any]:
    return {"x-queue-type": "quorum", "x-message-ttl": cfg.dead_letter_ttl_ms}


def declarar_topologia(canal, cfg: Config) -> None:
    """Declara (idempotente) el DLX, la dead-letter y la cola de usuarios."""
    canal.exchange_declare(exchange=cfg.dead_letter_exchange, exchange_type="fanout", durable=True)
    canal.queue_declare(
        queue=cfg.dead_letter_queue, durable=True, arguments=argumentos_dead_letter(cfg)
    )
    canal.queue_bind(queue=cfg.dead_letter_queue, exchange=cfg.dead_letter_exchange)
    canal.queue_declare(
        queue=cfg.users_queue, durable=True, arguments=argumentos_cola_usuarios(cfg)
    )
