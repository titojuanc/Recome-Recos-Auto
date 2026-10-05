"""Contrato de topología compartida: el worker declara lo mismo que el cron (FR-012)."""

import pytest
from pika.exceptions import ChannelClosedByBroker

from recos_auto.common.config import Config
from recos_auto.common.topology import declarar_topologia

pytestmark = pytest.mark.integration


def test_cron_y_worker_declaran_la_misma_topologia_sin_406(
    conexion_rabbit, config_worker, env_base
):
    cron = Config.from_env(dict(env_base, RABBITMQ_USERS_QUEUE=config_worker.users_queue))
    canal = conexion_rabbit.channel()
    declarar_topologia(canal, cron)
    declarar_topologia(canal, config_worker)  # idempotente: no debe dar PRECONDITION_FAILED
    declarar_topologia(canal, config_worker)


def test_ttl_distinto_provoca_406(conexion_rabbit, config_worker, env_base):
    """Control negativo: RabbitMQ rechaza un desalineo (por eso el test anterior vale)."""
    canal = conexion_rabbit.channel()
    declarar_topologia(canal, config_worker)
    otro = Config.from_env(
        dict(
            env_base,
            RABBITMQ_USERS_QUEUE=config_worker.users_queue,
            RABBITMQ_USERS_MESSAGE_TTL_MS=str(config_worker.users_message_ttl_ms + 1),
        )
    )
    canal2 = conexion_rabbit.channel()
    with pytest.raises(ChannelClosedByBroker) as error:
        declarar_topologia(canal2, otro)
    assert error.value.reply_code == 406
