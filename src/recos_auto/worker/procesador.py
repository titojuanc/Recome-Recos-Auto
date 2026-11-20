"""Lógica pura de un mensaje: parsear, pedir la recomendación, armar y publicar (sin AMQP)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from recos_auto.common.mensajes import MensajeUsuario
from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.notificacion import Notificacion, armar_notificaciones
from recos_auto.worker.publicador import ErrorPublicacion
from recos_auto.worker.recomendaciones import ErrorRecomendacion, Recomendacion

NOTIFICADO = "notificado"
SIN_RECOMENDACION = "sin_recomendacion"
INVALIDO = "invalido"
TRANSITORIO = "transitorio"


@dataclass(frozen=True)
class Resultado:
    tipo: str
    motivo: str = ""


def procesar(
    cuerpo: bytes,
    cfg: ConfigWorker,
    obtener: Callable[[object, str], Recomendacion],
    publicar: Callable[[Notificacion], None],
) -> Resultado:
    """Nunca lanza: todo fallo se traduce en un `Resultado`. `motivo` no contiene PII."""
    try:
        mensaje = MensajeUsuario.model_validate_json(cuerpo)
    except ValidationError:
        return Resultado(INVALIDO, "mensaje_no_cumple_contrato")
    except ValueError:
        return Resultado(INVALIDO, "mensaje_no_es_json")

    try:
        recomendacion = obtener(mensaje.recommendation_id, mensaje.modulo)
    except ErrorRecomendacion as exc:
        if exc.clase == "sin_recomendacion":
            return Resultado(SIN_RECOMENDACION, exc.motivo)
        if exc.clase == "invalido":
            return Resultado(INVALIDO, exc.motivo)
        return Resultado(TRANSITORIO, exc.motivo)

    if recomendacion.push_sub is None and not recomendacion.mail_enabled:
        # El usuario apagó el mail y no tiene push disponible: no hay por dónde avisarle.
        return Resultado(SIN_RECOMENDACION, "sin_canal_activo")

    try:
        notificaciones = armar_notificaciones(mensaje, recomendacion, cfg)
    except (ValidationError, KeyError, IndexError, ValueError):
        return Resultado(INVALIDO, "no_se_pudo_armar_la_notificacion")

    try:
        # Un aviso por canal activo. Si uno falla se reintenta todo: los ids son deterministas y
        # Notificaciones descarta el que ya salió.
        for notificacion in notificaciones:
            publicar(notificacion)
    except ErrorPublicacion as exc:
        return Resultado(TRANSITORIO, str(exc))
    return Resultado(NOTIFICADO)
