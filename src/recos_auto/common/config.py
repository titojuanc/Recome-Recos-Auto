"""Configuración del cron: todo viene de variables de entorno (contracts/entorno.md)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OBLIGATORIAS = ("API_GENERAL_BASE_URL", "API_GENERAL_API_KEY", "RABBITMQ_URL")

# Compartidos por el cron y el worker: la topología de la cola de usuarios debe coincidir
# exactamente (si no, RabbitMQ responde 406 PRECONDITION_FAILED).
COLA_USUARIOS_DEFECTO = "recos-auto.usuarios"
DELIVERY_LIMIT_DEFECTO = 5
TTL_USUARIOS_MS_DEFECTO = 7_200_000
TTL_DEAD_LETTER_MS_DEFECTO = 604_800_000


class ConfigError(Exception):
    """Configuración incompleta o inválida. Nunca incluye valores, solo nombres de variables."""

    def __init__(self, faltantes: list[str], invalidas: dict[str, str]):
        self.faltantes = faltantes
        self.invalidas = invalidas
        partes = []
        if faltantes:
            partes.append("faltan variables obligatorias: " + ", ".join(faltantes))
        if invalidas:
            partes.append(
                "variables inválidas: " + ", ".join(f"{n} ({m})" for n, m in invalidas.items())
            )
        super().__init__("Configuración inválida; " + "; ".join(partes))


@dataclass(frozen=True)
class Config:
    api_general_base_url: str
    api_general_api_key: str = field(repr=False)
    rabbitmq_url: str = field(repr=False)
    run_schedule: str = "0 12 * * *"
    run_timezone: str = "America/Argentina/Buenos_Aires"
    module_reference_date: date = date(2026, 10, 5)
    page_size: int = 200
    api_timeout_s: float = 10.0
    api_max_retries: int = 3
    api_retry_backoff_s: float = 1.0
    api_max_pages: int = 1000
    users_queue: str = COLA_USUARIOS_DEFECTO
    delivery_limit: int = DELIVERY_LIMIT_DEFECTO
    users_message_ttl_ms: int = TTL_USUARIOS_MS_DEFECTO  # 2 h (FR-014)
    dead_letter_ttl_ms: int = TTL_DEAD_LETTER_MS_DEFECTO  # 7 días (FR-014)
    publish_max_retries: int = 3
    publish_retry_backoff_s: float = 0.5
    max_consecutive_publish_failures: int = 5
    log_level: str = "INFO"

    @property
    def dead_letter_queue(self) -> str:
        return f"{self.users_queue}.dead-letter"

    @property
    def dead_letter_exchange(self) -> str:
        return f"{self.users_queue}.dlx"

    @property
    def zona(self) -> ZoneInfo:
        return ZoneInfo(self.run_timezone)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
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

        def entero(nombre: str, destino: str, minimo: int, maximo: int | None = None):
            if nombre not in env:
                return
            try:
                valor = int(env[nombre])
            except ValueError:
                invalidas[nombre] = "debe ser un entero"
                return
            if valor < minimo or (maximo is not None and valor > maximo):
                rango = f"entre {minimo} y {maximo}" if maximo else f"mayor o igual a {minimo}"
                invalidas[nombre] = f"debe estar {rango}"
                return
            valores[destino] = valor

        def decimal(nombre: str, destino: str, minimo: float):
            if nombre not in env:
                return
            try:
                valor = float(env[nombre])
            except ValueError:
                invalidas[nombre] = "debe ser un número"
                return
            if valor < minimo:
                invalidas[nombre] = f"debe ser mayor o igual a {minimo}"
                return
            valores[destino] = valor

        if env.get("API_GENERAL_BASE_URL") and not _es_url(
            env["API_GENERAL_BASE_URL"], ("http", "https")
        ):
            invalidas["API_GENERAL_BASE_URL"] = "debe ser una URL http(s)"
        if env.get("RABBITMQ_URL") and not _es_url(env["RABBITMQ_URL"], ("amqp", "amqps")):
            invalidas["RABBITMQ_URL"] = "debe ser una URL amqp(s)"

        texto("RUN_SCHEDULE", "run_schedule", _cron_valido, "debe tener 5 campos cron")
        texto("RUN_TIMEZONE", "run_timezone", _zona_valida, "zona horaria IANA desconocida")
        if "MODULE_REFERENCE_DATE" in env:
            try:
                valores["module_reference_date"] = date.fromisoformat(env["MODULE_REFERENCE_DATE"])
            except ValueError:
                invalidas["MODULE_REFERENCE_DATE"] = "formato esperado YYYY-MM-DD"
        entero("API_GENERAL_PAGE_SIZE", "page_size", 1, 500)
        decimal("API_GENERAL_TIMEOUT_S", "api_timeout_s", 0.1)
        entero("API_GENERAL_MAX_RETRIES", "api_max_retries", 0)
        decimal("API_GENERAL_RETRY_BACKOFF_S", "api_retry_backoff_s", 0)
        entero("API_GENERAL_MAX_PAGES", "api_max_pages", 1)
        texto("RABBITMQ_USERS_QUEUE", "users_queue")
        entero("RABBITMQ_DELIVERY_LIMIT", "delivery_limit", 1)
        entero("RABBITMQ_USERS_MESSAGE_TTL_MS", "users_message_ttl_ms", 1)
        entero("RABBITMQ_DEAD_LETTER_TTL_MS", "dead_letter_ttl_ms", 1)
        entero("PUBLISH_MAX_RETRIES", "publish_max_retries", 0)
        decimal("PUBLISH_RETRY_BACKOFF_S", "publish_retry_backoff_s", 0)
        entero("MAX_CONSECUTIVE_PUBLISH_FAILURES", "max_consecutive_publish_failures", 1)
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


def _es_url(valor: str, esquemas: tuple[str, ...]) -> bool:
    try:
        partes = urlparse(valor)
    except ValueError:
        return False
    return partes.scheme in esquemas and bool(partes.hostname)


def _cron_valido(valor: str) -> bool:
    campos = valor.split()
    return len(campos) == 5 and all(re.fullmatch(r"[\d*/,\-A-Za-z?]+", c) for c in campos)


def _zona_valida(valor: str) -> bool:
    try:
        ZoneInfo(valor)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True
