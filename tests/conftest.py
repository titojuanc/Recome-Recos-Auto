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
