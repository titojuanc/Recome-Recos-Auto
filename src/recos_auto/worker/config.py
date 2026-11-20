"""Configuración del worker: todo viene de variables de entorno (contracts/entorno.md)."""

from __future__ import annotations

import os
import string
from collections.abc import Mapping
from dataclasses import dataclass, field

from recos_auto.common.config import (
    COLA_USUARIOS_DEFECTO,
    DELIVERY_LIMIT_DEFECTO,
    OBLIGATORIAS,
    TTL_DEAD_LETTER_MS_DEFECTO,
    TTL_USUARIOS_MS_DEFECTO,
    ConfigError,
    _es_url,
)

TITULO_DEFECTO = "Tu recomendación de hoy: {titulo}"
CUERPO_DEFECTO = "Hoy te recomendamos {que_es}: {titulo}. Mirala acá: {url}"
CUERPO_PUSH_DEFECTO = "Hoy te recomendamos {que_es}: {titulo}."
URL_DEFECTO = "https://recome.example/catalogo/{item_id}"

# Variables que admite cada plantilla.
CAMPOS_TITULO = {"titulo", "modulo"}
CAMPOS_CUERPO = {"titulo", "modulo", "que_es", "url"}
CAMPOS_CUERPO_PUSH = {"titulo", "modulo", "que_es"}
CAMPOS_URL = {"modulo", "item_id"}

# El `consumer_timeout` por defecto de RabbitMQ es 30 min: una retención mayor cierra el canal.
LIMITE_RETENCION_S = 1800


def _campos_validos(plantilla: str, permitidos: set[str]) -> bool:
    try:
        campos = {c for _, c, _, _ in string.Formatter().parse(plantilla) if c is not None}
    except ValueError:
        return False
    return campos <= permitidos and all(c for c in campos)


@dataclass(frozen=True)
class ConfigWorker:
    api_general_base_url: str
    api_general_api_key: str = field(repr=False)
    rabbitmq_url: str = field(repr=False)
    users_queue: str = COLA_USUARIOS_DEFECTO
    delivery_limit: int = DELIVERY_LIMIT_DEFECTO
    users_message_ttl_ms: int = TTL_USUARIOS_MS_DEFECTO
    dead_letter_ttl_ms: int = TTL_DEAD_LETTER_MS_DEFECTO
    notificaciones_queue: str = "notificaciones"
    concurrency: int = 4
    api_timeout_s: float = 10.0
    publish_confirm_timeout_s: float = 10.0
    breaker_failures: int = 5  # 0 = interruptor deshabilitado
    breaker_backoff_s: float = 5.0
    breaker_backoff_max_s: float = 60.0
    breaker_max_hold_s: float = 1500.0
    notif_titulo_template: str = TITULO_DEFECTO
    notif_cuerpo_template: str = CUERPO_DEFECTO
    notif_cuerpo_push_template: str = CUERPO_PUSH_DEFECTO
    notif_url_template: str = URL_DEFECTO
    shutdown_timeout_s: float = 25.0
    summary_interval_s: float = 60.0
    poll_s: float = 1.0
    log_level: str = "INFO"

    @property
    def dead_letter_queue(self) -> str:
        return f"{self.users_queue}.dead-letter"

    @property
    def dead_letter_exchange(self) -> str:
        return f"{self.users_queue}.dlx"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ConfigWorker:
        env = os.environ if env is None else env
        faltantes = [n for n in OBLIGATORIAS if not env.get(n)]
        invalidas: dict[str, str] = {}
        valores: dict[str, object] = {}

        def texto(nombre: str, destino: str, validar=None, motivo: str = "valor inválido"):
            if nombre not in env:
                return
            valor = env[nombre]
            if not valor or (validar and not validar(valor)):
                invalidas[nombre] = motivo
                return
            valores[destino] = valor

        def entero(nombre: str, destino: str, minimo: int):
            if nombre not in env:
                return
            try:
                valor = int(env[nombre])
            except ValueError:
                invalidas[nombre] = "debe ser un entero"
                return
            if valor < minimo:
                invalidas[nombre] = f"debe ser mayor o igual a {minimo}"
                return
            valores[destino] = valor

        def decimal(nombre: str, destino: str, minimo: float, maximo: float | None = None):
            if nombre not in env:
                return
            try:
                valor = float(env[nombre])
            except ValueError:
                invalidas[nombre] = "debe ser un número"
                return
            if valor < minimo or (maximo is not None and valor >= maximo):
                invalidas[nombre] = "fuera de rango"
                return
            valores[destino] = valor

        if env.get("API_GENERAL_BASE_URL") and not _es_url(
            env["API_GENERAL_BASE_URL"], ("http", "https")
        ):
            invalidas["API_GENERAL_BASE_URL"] = "debe ser una URL http(s)"
        if env.get("RABBITMQ_URL") and not _es_url(env["RABBITMQ_URL"], ("amqp", "amqps")):
            invalidas["RABBITMQ_URL"] = "debe ser una URL amqp(s)"

        texto("RABBITMQ_USERS_QUEUE", "users_queue")
        texto("RABBITMQ_QUEUE_NOTIFICACIONES", "notificaciones_queue")
        entero("RABBITMQ_DELIVERY_LIMIT", "delivery_limit", 1)
        entero("RABBITMQ_USERS_MESSAGE_TTL_MS", "users_message_ttl_ms", 1)
        entero("RABBITMQ_DEAD_LETTER_TTL_MS", "dead_letter_ttl_ms", 1)
        entero("WORKER_CONCURRENCY", "concurrency", 1)
        decimal("API_GENERAL_TIMEOUT_S", "api_timeout_s", 0.1)
        decimal("PUBLISH_CONFIRM_TIMEOUT_S", "publish_confirm_timeout_s", 0.1)
        entero("BREAKER_FAILURES", "breaker_failures", 0)
        decimal("BREAKER_BACKOFF_S", "breaker_backoff_s", 0.0)
        decimal("BREAKER_BACKOFF_MAX_S", "breaker_backoff_max_s", 0.0)
        decimal("BREAKER_MAX_HOLD_S", "breaker_max_hold_s", 0.0, LIMITE_RETENCION_S)
        texto(
            "NOTIF_TITULO_TEMPLATE",
            "notif_titulo_template",
            lambda v: _campos_validos(v, CAMPOS_TITULO),
            f"solo admite {sorted(CAMPOS_TITULO)}",
        )
        texto(
            "NOTIF_CUERPO_TEMPLATE",
            "notif_cuerpo_template",
            lambda v: _campos_validos(v, CAMPOS_CUERPO),
            f"solo admite {sorted(CAMPOS_CUERPO)}",
        )
        texto(
            "NOTIF_CUERPO_PUSH_TEMPLATE",
            "notif_cuerpo_push_template",
            lambda v: _campos_validos(v, CAMPOS_CUERPO_PUSH),
            f"solo admite {sorted(CAMPOS_CUERPO_PUSH)}",
        )
        texto(
            "NOTIF_URL_TEMPLATE",
            "notif_url_template",
            lambda v: _campos_validos(v, CAMPOS_URL),
            f"solo admite {sorted(CAMPOS_URL)}",
        )
        decimal("SHUTDOWN_TIMEOUT_S", "shutdown_timeout_s", 0.0)
        decimal("SUMMARY_INTERVAL_S", "summary_interval_s", 0.1)
        decimal("WORKER_POLL_S", "poll_s", 0.05)
        texto(
            "LOG_LEVEL",
            "log_level",
            lambda v: v.upper() in {"DEBUG", "INFO", "WARNING", "ERROR"},
            "debe ser DEBUG, INFO, WARNING o ERROR",
        )
        if "log_level" in valores:
            valores["log_level"] = str(valores["log_level"]).upper()

        if faltantes or invalidas:
            raise ConfigError(faltantes, invalidas)
        return cls(
            api_general_base_url=env["API_GENERAL_BASE_URL"].rstrip("/"),
            api_general_api_key=env["API_GENERAL_API_KEY"],
            rabbitmq_url=env["RABBITMQ_URL"],
            **valores,  # type: ignore[arg-type]
        )
