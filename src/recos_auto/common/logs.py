"""Logs JSON a stdout. Nunca emiten emails, nombres, claves ni URLs con credenciales (FR-017)."""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from datetime import UTC, datetime
from typing import Any, TextIO

REDACTADO = "[redactado]"
_EXACTOS = {"email", "mail", "nombre"}
_SUBCADENAS = ("api_key", "apikey", "password", "secret", "clave", "rabbitmq_url", "credencial")
_URL_CON_CREDENCIALES = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")


def _es_sensible(clave: str) -> bool:
    k = clave.lower()
    return k in _EXACTOS or any(s in k for s in _SUBCADENAS)


def _limpiar_texto(texto: str) -> str:
    texto = _URL_CON_CREDENCIALES.sub(r"\1" + REDACTADO + "@", texto)
    return _EMAIL.sub("[email]", texto)


def _limpiar(valor: Any) -> Any:
    if isinstance(valor, str):
        return _limpiar_texto(valor)
    if isinstance(valor, dict):
        return {k: REDACTADO if _es_sensible(str(k)) else _limpiar(v) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_limpiar(v) for v in valor]
    return valor


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "evento": _limpiar_texto(record.getMessage()),
        }
        for clave, valor in getattr(record, "campos", {}).items():
            datos[clave] = REDACTADO if _es_sensible(clave) else _limpiar(valor)
        if record.exc_info:
            datos["traceback"] = _limpiar_texto(
                "".join(traceback.format_exception(*record.exc_info))
            )
        return json.dumps(datos, ensure_ascii=False, default=str)


def configurar_logs(nivel: str = "INFO", flujo: TextIO | None = None) -> None:
    manejador = logging.StreamHandler(flujo or sys.stdout)
    manejador.setFormatter(JsonFormatter())
    raiz = logging.getLogger()
    raiz.handlers.clear()
    raiz.addHandler(manejador)
    raiz.setLevel(nivel.upper())
    for ruidoso in ("pika", "httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def evento(
    logger: logging.Logger, nombre_evento: str, nivel: int = logging.INFO, /, **campos: Any
) -> None:
    """Emite una línea JSON con `evento=nombre_evento` y los campos dados.

    Los tres primeros parámetros son posicionales para no chocar con campos como `nombre`.
    """
    logger.log(nivel, nombre_evento, extra={"campos": campos})
