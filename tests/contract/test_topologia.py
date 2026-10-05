from __future__ import annotations

import time

import httpx
import pika
import pika.exceptions
import pytest

from recos_auto.common.config import Config
from recos_auto.common.topology import declarar_topologia

pytestmark = pytest.mark.integration


@pytest.fixture
def canal(conexion_rabbit):
    return conexion_rabbit.channel()


def _publicar(canal, cfg, cuerpo: bytes = b"{}"):
    canal.basic_publish(
        exchange="",
        routing_key=cfg.users_queue,
        body=cuerpo,
        properties=pika.BasicProperties(delivery_mode=2),
        mandatory=True,
    )


def _esperar_mensaje(canal, cola, segundos=8.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        metodo, _, cuerpo = canal.basic_get(cola, auto_ack=True)
        if metodo:
            return cuerpo
        time.sleep(0.25)
    return None


def test_declaracion_es_idempotente(canal, config_rabbit):
    declarar_topologia(canal, config_rabbit)
    declarar_topologia(canal, config_rabbit)


def test_publicar_con_confirmacion_llega_a_la_cola(canal, config_rabbit):
    declarar_topologia(canal, config_rabbit)
    canal.confirm_delivery()
    _publicar(canal, config_rabbit, b'{"hola": 1}')
    assert _esperar_mensaje(canal, config_rabbit.users_queue) == b'{"hola": 1}'


def test_redeclarar_con_otro_delivery_limit_falla(conexion_rabbit, config_rabbit, env_base):
    declarar_topologia(conexion_rabbit.channel(), config_rabbit)
    otro = Config.from_env(
        dict(
            env_base,
            RABBITMQ_URL=config_rabbit.rabbitmq_url,
            RABBITMQ_USERS_QUEUE=config_rabbit.users_queue,
            RABBITMQ_DELIVERY_LIMIT="9",
        )
    )
    with pytest.raises(pika.exceptions.ChannelClosedByBroker) as exc:
        declarar_topologia(conexion_rabbit.channel(), otro)
    assert exc.value.reply_code == 406  # PRECONDITION_FAILED


def test_tras_agotar_entregas_el_mensaje_va_a_la_dead_letter(canal, config_rabbit):
    declarar_topologia(canal, config_rabbit)
    _publicar(canal, config_rabbit, b"reintentar")
    entregas = 0
    for _ in range(config_rabbit.delivery_limit + 3):
        metodo, _, _ = canal.basic_get(config_rabbit.users_queue, auto_ack=False)
        if not metodo:
            time.sleep(0.3)
            continue
        entregas += 1
        canal.basic_nack(metodo.delivery_tag, requeue=True)
    assert entregas == config_rabbit.delivery_limit + 1  # 1 original + 5 reintentos
    assert _esperar_mensaje(canal, config_rabbit.dead_letter_queue) == b"reintentar"


def test_un_mensaje_vencido_por_ttl_pasa_a_la_dead_letter(conexion_rabbit, env_base, config_rabbit):
    """TTL corto por variable de entorno (2 s); el valor de producción se prueba abajo."""
    corto = Config.from_env(
        dict(
            env_base,
            RABBITMQ_URL=config_rabbit.rabbitmq_url,
            RABBITMQ_USERS_QUEUE=config_rabbit.users_queue,
            RABBITMQ_USERS_MESSAGE_TTL_MS="2000",
        )
    )
    canal = conexion_rabbit.channel()
    declarar_topologia(canal, corto)
    _publicar(canal, corto, b"se-vence")
    # Nadie consume el mensaje: debe aparecer en la dead-letter pasado el TTL.
    assert _esperar_mensaje(canal, corto.dead_letter_queue, segundos=15) == b"se-vence"


def _argumentos_declarados(cfg: Config, cola: str) -> dict | None:
    """Lee los argumentos reales de la cola vía API de administración (si está disponible)."""
    url = httpx.URL(cfg.rabbitmq_url)
    base = f"http://{url.host}:15672/api/queues/%2F/{cola}"
    auth = (url.username or "guest", url.password or "guest")
    limite = time.monotonic() + 15
    while time.monotonic() < limite:
        try:
            r = httpx.get(base, auth=auth, timeout=2)
        except httpx.HTTPError:
            return None
        if r.status_code == 200:
            return r.json().get("arguments", {})
        time.sleep(1)
    return None


def test_argumentos_de_produccion_2h_y_7_dias(canal, config_rabbit):
    declarar_topologia(canal, config_rabbit)
    usuarios = _argumentos_declarados(config_rabbit, config_rabbit.users_queue)
    if usuarios is None:
        pytest.skip("API de administración de RabbitMQ no disponible")
    assert usuarios["x-message-ttl"] == 7_200_000
    assert usuarios["x-delivery-limit"] == 5
    assert usuarios["x-dead-letter-exchange"] == config_rabbit.dead_letter_exchange
    assert usuarios["x-queue-type"] == "quorum"
    muertos = _argumentos_declarados(config_rabbit, config_rabbit.dead_letter_queue)
    assert muertos["x-message-ttl"] == 604_800_000
