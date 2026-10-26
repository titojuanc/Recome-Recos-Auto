"""Cliente de api-general para la recomendación del día.

Contrato: specs/002-worker-recomendaciones/contracts/api-general-notification-recommendation.md.
No reintenta: los reintentos son los de RabbitMQ (hasta 5). Clasifica cada fallo para que el
procesador decida el destino del mensaje.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from recos_auto.worker.config import ConfigWorker

RUTA = "/internal/v1/notification-recommendations/"
MAX_TITULO = 120
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ESPACIOS = re.compile(r"\s+")

Clase = Literal["sin_recomendacion", "invalido", "transitorio"]


def limpiar_titulo(titulo: str) -> str:
    """Quita caracteres de control, normaliza espacios y trunca a MAX_TITULO caracteres."""
    limpio = _ESPACIOS.sub(" ", _CONTROL.sub(" ", titulo)).strip()
    if len(limpio) > MAX_TITULO:
        limpio = limpio[: MAX_TITULO - 1].rstrip() + "…"
    return limpio


class ErrorRecomendacion(Exception):
    """Fallo clasificado. `motivo` es un texto corto y seguro (sin datos personales)."""

    def __init__(self, clase: Clase, motivo: str):
        super().__init__(motivo)
        self.clase = clase
        self.motivo = motivo


@dataclass(frozen=True)
class Recomendacion:
    recommendation_id: uuid.UUID
    item_id: uuid.UUID
    module: str
    titulo: str
    position: int


class _Respuesta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recommendation_id: uuid.UUID
    item_id: uuid.UUID
    module: str
    titulo: str
    position: int


def clasificar_estado(estado: int) -> tuple[Clase, str]:
    """Tabla de research.md D6 para respuestas que no son 200."""
    if estado in (404, 412):
        return "sin_recomendacion", f"http_{estado}"
    if estado in (401, 403, 429) or estado >= 500:
        return "transitorio", f"http_{estado}"
    return "invalido", f"http_{estado}"


class ClienteRecomendaciones:
    def __init__(self, cfg: ConfigWorker, transport: httpx.BaseTransport | None = None):
        self._cfg = cfg
        self._http = httpx.Client(
            timeout=cfg.api_timeout_s,
            headers={"X-Internal-API-Key": cfg.api_general_api_key},
            transport=transport,
        )

    def cerrar(self) -> None:
        self._http.close()

    def obtener(self, recommendation_id: uuid.UUID, modulo: str) -> Recomendacion:
        url = f"{self._cfg.api_general_base_url}{RUTA}{recommendation_id}"
        try:
            respuesta = self._http.get(url, params={"module": modulo})
        except httpx.TimeoutException as error:
            raise ErrorRecomendacion("transitorio", "timeout") from error
        except httpx.HTTPError as error:
            raise ErrorRecomendacion("transitorio", f"red_{type(error).__name__}") from error

        if respuesta.status_code != 200:
            clase, motivo = clasificar_estado(respuesta.status_code)
            raise ErrorRecomendacion(clase, motivo)

        try:
            datos = _Respuesta.model_validate(respuesta.json())
        except (ValueError, ValidationError) as error:
            raise ErrorRecomendacion("invalido", "respuesta_invalida") from error

        # FR-025: la recomendación debe ser la pedida, para el módulo pedido.
        if datos.recommendation_id != recommendation_id:
            raise ErrorRecomendacion("invalido", "recommendation_id_distinto")
        if datos.module != modulo:
            raise ErrorRecomendacion("invalido", "modulo_distinto")

        titulo = limpiar_titulo(datos.titulo)
        if not titulo:
            raise ErrorRecomendacion("sin_recomendacion", "titulo_vacio")
        return Recomendacion(
            recommendation_id=datos.recommendation_id,
            item_id=datos.item_id,
            module=datos.module,
            titulo=titulo,
            position=datos.position,
        )
