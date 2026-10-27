"""Notificación de salida: identidad estable y contenido (research.md D4 y D5)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from recos_auto.common.mensajes import MensajeUsuario
from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.recomendaciones import PushSub, Recomendacion

_MASCARA_63_BITS = 0x7FFF_FFFF_FFFF_FFFF

# (nombre legible en el texto, "qué es" con artículo)
_MODULOS = {
    "peliculas": ("película", "una película"),
    "juegos": ("juego", "un juego"),
}


def id_mensaje_para(message_id: uuid.UUID) -> int:
    """Entero positivo de 63 bits derivado del UUIDv5 del mensaje de usuario.

    Determinista: mismo usuario, fecha y módulo => mismo id (Notificaciones deduplica por él).
    """
    valor = int.from_bytes(message_id.bytes[:8], "big") & _MASCARA_63_BITS
    return valor or 1


class Contenido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(min_length=1)
    cuerpo: str = Field(min_length=1)
    url: str | None = Field(default=None, min_length=1)


class Notificacion(BaseModel):
    """Subconjunto del contrato de Recome-Recos-Notificaciones que produce este worker."""

    model_config = ConfigDict(extra="forbid")

    id_mensaje: int = Field(ge=1, le=_MASCARA_63_BITS)
    canal: Literal["mail", "push"] = "mail"
    destinatario: int = Field(ge=1)
    # Con canal=push, `mail` es el respaldo si la suscripción ya no existe (404/410).
    mail: EmailStr
    push_sub: PushSub | None = None
    contenido: Contenido

    @model_validator(mode="after")
    def _push_exige_suscripcion(self) -> Notificacion:
        if self.canal == "push" and self.push_sub is None:
            raise ValueError("canal 'push' requiere push_sub")
        if self.canal == "mail" and self.push_sub is not None:
            raise ValueError("canal 'mail' no admite push_sub")
        return self


def armar_notificacion(
    mensaje: MensajeUsuario, recomendacion: Recomendacion, cfg: ConfigWorker
) -> Notificacion:
    """FR-025: `mail` y `destinatario` salen del MISMO mensaje que originó la recomendación."""
    nombre_modulo, que_es = _MODULOS[mensaje.modulo]
    # El frontend resuelve /catalogo/:itemId con el id del catálogo; `item_id` (UUID del motor de
    # recomendaciones) solo se usa si api-general todavía no manda `catalog_item_id`.
    destino_id = recomendacion.catalog_item_id or recomendacion.item_id
    url = cfg.notif_url_template.format(modulo=mensaje.modulo, item_id=destino_id)
    titulo = cfg.notif_titulo_template.format(titulo=recomendacion.titulo, modulo=nombre_modulo)
    id_mensaje = id_mensaje_para(mensaje.message_id)

    if recomendacion.push_sub is not None:
        # Push primero; el link va en `url` (no en el cuerpo) y el mail queda de respaldo.
        cuerpo = cfg.notif_cuerpo_push_template.format(
            titulo=recomendacion.titulo, modulo=nombre_modulo, que_es=que_es
        )
        return Notificacion(
            id_mensaje=id_mensaje,
            canal="push",
            destinatario=mensaje.user_id,
            mail=mensaje.email,
            push_sub=recomendacion.push_sub,
            contenido=Contenido(titulo=titulo, cuerpo=cuerpo, url=url),
        )

    cuerpo = cfg.notif_cuerpo_template.format(
        titulo=recomendacion.titulo, modulo=nombre_modulo, que_es=que_es, url=url
    )
    return Notificacion(
        id_mensaje=id_mensaje,
        destinatario=mensaje.user_id,
        mail=mensaje.email,
        contenido=Contenido(titulo=titulo, cuerpo=cuerpo),
    )
