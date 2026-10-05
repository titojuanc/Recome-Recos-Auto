"""Notificación de salida: identidad estable y contenido (research.md D4 y D5)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from recos_auto.common.mensajes import MensajeUsuario
from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.recomendaciones import Recomendacion

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


class Notificacion(BaseModel):
    """Subconjunto del contrato de Recome-Recos-Notificaciones que produce este worker."""

    model_config = ConfigDict(extra="forbid")

    id_mensaje: int = Field(ge=1, le=_MASCARA_63_BITS)
    canal: Literal["mail"] = "mail"
    destinatario: int = Field(ge=1)
    mail: EmailStr
    contenido: Contenido


def armar_notificacion(
    mensaje: MensajeUsuario, recomendacion: Recomendacion, cfg: ConfigWorker
) -> Notificacion:
    """FR-025: `mail` y `destinatario` salen del MISMO mensaje que originó la recomendación."""
    nombre_modulo, que_es = _MODULOS[mensaje.modulo]
    url = cfg.notif_url_template.format(modulo=mensaje.modulo, item_id=recomendacion.item_id)
    titulo = cfg.notif_titulo_template.format(titulo=recomendacion.titulo, modulo=nombre_modulo)
    cuerpo = cfg.notif_cuerpo_template.format(
        titulo=recomendacion.titulo, modulo=nombre_modulo, que_es=que_es, url=url
    )
    return Notificacion(
        id_mensaje=id_mensaje_para(mensaje.message_id),
        destinatario=mensaje.user_id,
        mail=mensaje.email,
        contenido=Contenido(titulo=titulo, cuerpo=cuerpo),
    )
