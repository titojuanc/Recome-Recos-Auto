"""Mensaje cron -> worker (contracts/mensaje-usuario.schema.json) y entrada de api-general."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Modulo = Literal["peliculas", "juegos"]
VERSION_MENSAJE = 1
# Namespace fijo: cambiarlo cambiaría la identidad de todos los mensajes (rompe la deduplicación).
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://recome.local/recos-auto/mensaje-usuario")

UserId = Annotated[int, Field(ge=1, strict=True)]


def message_id_para(user_id: int, fecha: date, modulo: str) -> uuid.UUID:
    """Identidad determinística: misma (usuario, fecha, módulo) => mismo UUID (FR-012)."""
    return uuid.uuid5(NAMESPACE, f"{user_id}|{fecha.isoformat()}|{modulo}")


class UsuarioDestinatario(BaseModel):
    """Registro `items[]` de api-general. Contiene datos personales: no loguear."""

    model_config = ConfigDict(extra="ignore")

    recommendation_id: uuid.UUID
    user_id: UserId
    nombre: str
    email: EmailStr
    idioma: str | None = None

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("nombre vacío")
        return valor  # se conserva tal cual (acentos, emojis)


class MensajeUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = VERSION_MENSAJE
    message_id: uuid.UUID
    corrida_id: str = Field(min_length=1)
    fecha: date
    modulo: Modulo
    recommendation_id: uuid.UUID
    user_id: UserId
    nombre: str
    email: EmailStr
    idioma: str | None = None


def construir_mensaje(
    usuario: UsuarioDestinatario, corrida_id: str, fecha: date, modulo: str
) -> MensajeUsuario:
    return MensajeUsuario(
        message_id=message_id_para(usuario.user_id, fecha, modulo),
        corrida_id=corrida_id,
        fecha=fecha,
        modulo=modulo,  # type: ignore[arg-type]
        recommendation_id=usuario.recommendation_id,
        user_id=usuario.user_id,
        nombre=usuario.nombre,
        email=usuario.email,
        idioma=usuario.idioma,
    )
