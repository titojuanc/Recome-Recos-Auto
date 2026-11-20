"""Notificación de salida: identidad estable y contenido (research.md D4 y D5)."""

from __future__ import annotations

import uuid
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


TIPO_RECOMENDACION_DIA = "recomendacion_dia"
# Parámetro con el que el frontend cuenta el clic en la notificación (spec 013 de api-general).
PARAMETRO_ORIGEN = "n"
# Id del aviso: con él el clic se cuenta sin que el usuario tenga la sesión iniciada.
PARAMETRO_MENSAJE = "m"


def con_origen(url: str, tipo: str, id_mensaje: int | None = None) -> str:
    """Agrega `?n=<tipo>&m=<id_mensaje>` a la URL, conservando la consulta y el fragmento.

    El frontend lo lee al abrir la notificación (push o mail), cuenta el clic y lo saca de la barra.
    Si la URL ya traía `n` o `m`, se reemplazan.
    """
    partes = urlsplit(url)
    consulta = [
        par
        for par in parse_qsl(partes.query, keep_blank_values=True)
        if par[0] not in (PARAMETRO_ORIGEN, PARAMETRO_MENSAJE)
    ]
    consulta.append((PARAMETRO_ORIGEN, tipo))
    if id_mensaje is not None:
        consulta.append((PARAMETRO_MENSAJE, str(id_mensaje)))
    return urlunsplit(partes._replace(query=urlencode(consulta)))


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
    # Analytics del admin (spec 013 de api-general): Notificaciones cuenta el envío con este tipo.
    tipo: Literal["recomendacion_dia"] = TIPO_RECOMENDACION_DIA
    destinatario: int = Field(ge=1)
    # Con canal=push, `mail` es el respaldo si la suscripción ya no existe (404/410); va vacío
    # cuando el usuario apagó el mail.
    mail: EmailStr | None = None
    push_sub: PushSub | None = None
    contenido: Contenido

    @model_validator(mode="after")
    def _push_exige_suscripcion(self) -> Notificacion:
        if self.canal == "push" and self.push_sub is None:
            raise ValueError("canal 'push' requiere push_sub")
        if self.canal == "mail" and self.push_sub is not None:
            raise ValueError("canal 'mail' no admite push_sub")
        if self.canal == "mail" and self.mail is None:
            raise ValueError("canal 'mail' requiere mail")
        return self


def id_mensaje_mail_para(message_id: uuid.UUID) -> int:
    """Id del aviso por mail cuando el mismo usuario recibe también el push.

    Notificaciones deduplica por `id_mensaje`: si el mail compartiera el id del push se descartaría.
    Determinista, para que un reintento no duplique el envío.
    """
    return id_mensaje_para(uuid.uuid5(message_id, "mail"))


def armar_notificaciones(
    mensaje: MensajeUsuario, recomendacion: Recomendacion, cfg: ConfigWorker
) -> list[Notificacion]:
    """Un aviso por cada canal activo del usuario; uno no anula al otro.

    Con push y mail activos salen dos mensajes independientes (el push ya no lleva el mail de
    respaldo: lo enviaría duplicado). Con un solo canal activo, sale un solo mensaje.
    """
    if recomendacion.push_sub is None:
        return [_armar_mail(mensaje, recomendacion, cfg, id_mensaje_para(mensaje.message_id))]
    avisos = [_armar_push(mensaje, recomendacion, cfg)]
    if recomendacion.mail_enabled:
        avisos.append(
            _armar_mail(mensaje, recomendacion, cfg, id_mensaje_mail_para(mensaje.message_id))
        )
    return avisos


def _datos_comunes(
    mensaje: MensajeUsuario, recomendacion: Recomendacion, cfg: ConfigWorker, id_mensaje: int
):
    """FR-025: `mail` y `destinatario` salen del MISMO mensaje que originó la recomendación."""
    nombre_modulo, que_es = _MODULOS[mensaje.modulo]
    # El frontend resuelve /catalogo/:itemId con el id del catálogo; `item_id` (UUID del motor de
    # recomendaciones) solo se usa si api-general todavía no manda `catalog_item_id`.
    destino_id = recomendacion.catalog_item_id or recomendacion.item_id
    # Cada aviso lleva su propio link con `?n=` y `?m=<id_mensaje>`: el clic se cuenta por aviso y
    # por canal, aunque el usuario abra el mail en un navegador sin sesión.
    url = con_origen(
        cfg.notif_url_template.format(modulo=mensaje.modulo, item_id=destino_id),
        TIPO_RECOMENDACION_DIA,
        id_mensaje,
    )
    titulo = cfg.notif_titulo_template.format(titulo=recomendacion.titulo, modulo=nombre_modulo)
    return titulo, nombre_modulo, que_es, url


def _armar_push(
    mensaje: MensajeUsuario, recomendacion: Recomendacion, cfg: ConfigWorker
) -> Notificacion:
    id_mensaje = id_mensaje_para(mensaje.message_id)
    titulo, nombre_modulo, que_es, url = _datos_comunes(mensaje, recomendacion, cfg, id_mensaje)
    # El link va en `url` (no en el cuerpo). Sin mail de respaldo: si el usuario lo tiene activo,
    # recibe su propio aviso por mail (ver `armar_notificaciones`).
    cuerpo = cfg.notif_cuerpo_push_template.format(
        titulo=recomendacion.titulo, modulo=nombre_modulo, que_es=que_es
    )
    return Notificacion(
        id_mensaje=id_mensaje,
        canal="push",
        destinatario=mensaje.user_id,
        push_sub=recomendacion.push_sub,
        contenido=Contenido(titulo=titulo, cuerpo=cuerpo, url=url),
    )


def _armar_mail(
    mensaje: MensajeUsuario, recomendacion: Recomendacion, cfg: ConfigWorker, id_mensaje: int
) -> Notificacion:
    titulo, nombre_modulo, que_es, url = _datos_comunes(mensaje, recomendacion, cfg, id_mensaje)
    cuerpo = cfg.notif_cuerpo_template.format(
        titulo=recomendacion.titulo, modulo=nombre_modulo, que_es=que_es, url=url
    )
    return Notificacion(
        id_mensaje=id_mensaje,
        destinatario=mensaje.user_id,
        mail=mensaje.email,
        contenido=Contenido(titulo=titulo, cuerpo=cuerpo),
    )
