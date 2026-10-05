"""Fixtures: entorno base, RabbitMQ real (se saltea si no hay) y api-general simulada."""

from __future__ import annotations

import os
import uuid

import httpx
import pika
import pytest

from recos_auto.common.config import Config

URL_RABBIT_TEST = os.environ.get("RABBITMQ_TEST_URL", "amqp://guest:guest@localhost:5672/")
BASE_URL_API = "http://api.test/api/v1"
CLAVE_API = "local.clave-de-prueba"


@pytest.fixture
def env_base() -> dict[str, str]:
    return {
        "API_GENERAL_BASE_URL": BASE_URL_API,
        "API_GENERAL_API_KEY": CLAVE_API,
        "RABBITMQ_URL": "amqp://usuario:secreto@rabbit.test:5672/",
    }


@pytest.fixture
def config(env_base) -> Config:
    return Config.from_env(env_base)


def hacer_usuarios(cantidad: int, desde: int = 1) -> list[dict]:
    return [
        {
            "recommendation_id": str(uuid.UUID(int=i)),
            "user_id": i,
            "nombre": f"Usuario {i}",
            "email": f"u{i}@example.com",
            "idioma": "es",
        }
        for i in range(desde, desde + cantidad)
    ]


class ApiMock:
    """api-general simulada con paginación por offset.

    `forzar` es una lista de respuestas que se devuelven primero, en orden:
    un entero es un estado HTTP y una excepción se lanza como error de red.
    """

    def __init__(self, usuarios: list[dict], clave: str = CLAVE_API):
        self.usuarios = usuarios
        self.clave = clave
        self.pedidos: list[httpx.Request] = []
        self.forzar: list[int | Exception] = []
        self.forzar_a_partir_del_pedido = 1  # n.º de pedido desde el que aplica `forzar`
        self.token_fijo: str | None = None  # si se define, siempre devuelve este token
        self.siempre_hay_mas = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.pedidos.append(request)
        if self.forzar and len(self.pedidos) >= self.forzar_a_partir_del_pedido:
            forzado = self.forzar.pop(0)
            if isinstance(forzado, Exception):
                raise forzado
            return httpx.Response(forzado, json={"error": "forzado"})
        if request.headers.get("X-Internal-API-Key") != self.clave:
            return httpx.Response(401, json={"error": "clave"})
        tamano = int(request.url.params.get("page_size", "100"))
        desde = int(request.url.params.get("page_token", "0"))
        items = self.usuarios[desde : desde + tamano]
        siguiente = desde + tamano
        hay_mas = siguiente < len(self.usuarios) or self.siempre_hay_mas
        token = self.token_fijo if self.token_fijo is not None else str(siguiente)
        return httpx.Response(
            200, json={"items": items, "next_page_token": token if hay_mas else None}
        )

    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def api_mock_factory():
    def _crear(cantidad: int = 0, usuarios: list[dict] | None = None) -> ApiMock:
        return ApiMock(usuarios if usuarios is not None else hacer_usuarios(cantidad))

    return _crear


def _parametros() -> pika.URLParameters:
    parametros = pika.URLParameters(URL_RABBIT_TEST)
    parametros.socket_timeout = 2
    parametros.connection_attempts = 1
    return parametros


@pytest.fixture
def conexion_rabbit():
    try:
        conexion = pika.BlockingConnection(_parametros())
    except Exception:
        pytest.skip("RabbitMQ no disponible (docker compose -f docker-compose.test.yml up -d)")
    yield conexion
    if conexion.is_open:
        conexion.close()


@pytest.fixture
def config_rabbit(env_base, conexion_rabbit):
    """Config apuntando al RabbitMQ real con una cola única por test (se borra al terminar)."""
    nombre = f"recos-auto.test-{uuid.uuid4().hex[:8]}.usuarios"
    env = dict(env_base, RABBITMQ_URL=URL_RABBIT_TEST, RABBITMQ_USERS_QUEUE=nombre)
    cfg = Config.from_env(env)
    yield cfg
    if conexion_rabbit.is_open:
        canal = conexion_rabbit.channel()
        for cola in (cfg.users_queue, cfg.dead_letter_queue):
            canal.queue_delete(cola)
        canal.exchange_delete(cfg.dead_letter_exchange)


# --------------------------------------------------------------------------------------
# Fixtures del worker (feature 002)
# --------------------------------------------------------------------------------------


@pytest.fixture
def env_worker(env_base) -> dict[str, str]:
    return dict(env_base)


@pytest.fixture
def config_worker(env_base, conexion_rabbit):
    """ConfigWorker con colas únicas por test (usuarios y notificaciones); se borran al final."""
    from recos_auto.worker.config import ConfigWorker

    sufijo = uuid.uuid4().hex[:8]
    env = dict(
        env_base,
        RABBITMQ_URL=URL_RABBIT_TEST,
        RABBITMQ_USERS_QUEUE=f"recos-auto.test-{sufijo}.usuarios",
        RABBITMQ_QUEUE_NOTIFICACIONES=f"recos-auto.test-{sufijo}.notificaciones",
        WORKER_POLL_S="0.1",
        SUMMARY_INTERVAL_S="3600",
        BREAKER_BACKOFF_S="0.2",
        BREAKER_BACKOFF_MAX_S="0.5",
    )
    cfg = ConfigWorker.from_env(env)
    canal = conexion_rabbit.channel()
    # Quien declara la cola de notificaciones es Recome-Notificaciones; aquí la simula el test.
    canal.queue_declare(
        queue=cfg.notificaciones_queue, durable=True, arguments={"x-queue-type": "quorum"}
    )
    yield cfg
    if conexion_rabbit.is_open:
        canal = conexion_rabbit.channel()
        for cola in (cfg.users_queue, cfg.dead_letter_queue, cfg.notificaciones_queue):
            canal.queue_delete(cola)
        canal.exchange_delete(cfg.dead_letter_exchange)


def mensaje_usuario_dict(
    user_id: int, modulo: str = "peliculas", fecha: str = "2026-10-06", email: str | None = None
) -> dict:
    from datetime import date

    from recos_auto.common.mensajes import message_id_para

    return {
        "version": 1,
        "message_id": str(message_id_para(user_id, date.fromisoformat(fecha), modulo)),
        "corrida_id": "corrida-test",
        "fecha": fecha,
        "modulo": modulo,
        "recommendation_id": str(uuid.UUID(int=user_id)),
        "user_id": user_id,
        "nombre": f"Usuario {user_id}",
        "email": email or f"u{user_id}@example.com",
        "idioma": "es",
    }


@pytest.fixture
def publicar_usuarios(conexion_rabbit, config_worker):
    """Publica `n` mensajes de usuario válidos en la cola de entrada (declarando la topología)."""
    import json

    from recos_auto.common.topology import declarar_topologia

    def _publicar(n: int, desde: int = 1, modulo: str = "peliculas") -> list[dict]:
        canal = conexion_rabbit.channel()
        declarar_topologia(canal, config_worker)
        mensajes = [mensaje_usuario_dict(i, modulo) for i in range(desde, desde + n)]
        for m in mensajes:
            canal.basic_publish(
                exchange="",
                routing_key=config_worker.users_queue,
                body=json.dumps(m).encode(),
                properties=pika.BasicProperties(delivery_mode=2),
            )
        canal.close()
        return mensajes

    return _publicar


@pytest.fixture
def leer_cola(conexion_rabbit):
    """Vacía una cola y devuelve los cuerpos JSON (para inspeccionar notificaciones)."""
    import json

    def _leer(nombre: str) -> list[dict]:
        canal = conexion_rabbit.channel()
        salida = []
        while True:
            metodo, _props, cuerpo = canal.basic_get(nombre, auto_ack=True)
            if metodo is None:
                break
            salida.append(json.loads(cuerpo))
        canal.close()
        return salida

    return _leer


@pytest.fixture
def profundidad(conexion_rabbit):
    def _p(nombre: str) -> int:
        canal = conexion_rabbit.channel()
        try:
            return canal.queue_declare(queue=nombre, passive=True).method.message_count
        finally:
            canal.close()

    return _p
