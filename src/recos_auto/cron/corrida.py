"""Orquestación de una corrida: lee usuarios, valida, deduplica, publica y resume."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime

from pydantic import ValidationError

from recos_auto.common.config import Config
from recos_auto.common.logs import evento
from recos_auto.common.mensajes import UsuarioDestinatario, construir_mensaje
from recos_auto.cron.api_general import ApiGeneralError
from recos_auto.cron.modulo import modulo_para
from recos_auto.cron.publicador import PublicacionError

log = logging.getLogger("recos_auto.cron")

CODIGOS_DE_SALIDA = {
    "exito": 0,
    "error": 1,
    "interrumpida": 1,
    "parcial": 2,
    "omitida_por_bloqueo": 75,
}


class CorridaAbortada(Exception):
    """Se abandona la corrida porque seguir no tiene sentido (p. ej. RabbitMQ no responde)."""


@dataclass
class Resumen:
    corrida_id: str
    fecha: date
    modulo: str
    paginas: int = 0
    recibidos: int = 0
    publicados: int = 0
    omitidos: int = 0
    repetidos: int = 0
    fallidos: int = 0
    duracion_s: float = 0.0
    resultado: str = "exito"
    error: str | None = None


def codigo_de_salida(resultado: str) -> int:
    return CODIGOS_DE_SALIDA[resultado]


def ejecutar_corrida(
    cfg: Config,
    api,
    publicador,
    *,
    fecha: date | None = None,
    reloj: Callable[[], datetime] | None = None,
    debe_detenerse: Callable[[], bool] = lambda: False,
) -> Resumen:
    """Una corrida completa. La fecha y el módulo se fijan una sola vez al iniciar (UTC-3).

    No lanza por fallos esperados (api-general, RabbitMQ, apagado): los refleja en `resultado`.
    """
    reloj = reloj or (lambda: datetime.now(cfg.zona))
    inicio = reloj().astimezone(cfg.zona)
    fecha = fecha or inicio.date()
    modulo = modulo_para(fecha, cfg.module_reference_date)
    resumen = Resumen(corrida_id=uuid.uuid4().hex[:8], fecha=fecha, modulo=modulo)
    evento(log, "corrida_iniciada", corrida_id=resumen.corrida_id, fecha=str(fecha), modulo=modulo)

    try:
        _procesar(cfg, api, publicador, resumen, debe_detenerse)
    except (ApiGeneralError, CorridaAbortada) as error:
        resumen.resultado = "error"
        resumen.error = str(error)
    if resumen.resultado == "exito" and resumen.fallidos:
        resumen.resultado = "parcial"

    resumen.duracion_s = (reloj().astimezone(cfg.zona) - inicio).total_seconds()
    datos = asdict(resumen)
    datos["fecha"] = str(fecha)
    if resumen.resultado == "interrumpida":
        evento(log, "corrida_interrumpida", logging.WARNING, **datos)
    nivel = logging.ERROR if resumen.resultado == "error" else logging.INFO
    evento(log, "corrida_finalizada", nivel, **datos)
    return resumen


def _procesar(cfg: Config, api, publicador, resumen: Resumen, debe_detenerse) -> None:
    vistos: set[int] = set()
    consecutivos = 0
    for pagina in api.paginas():
        if debe_detenerse():
            resumen.resultado = "interrumpida"
            return
        resumen.paginas += 1
        evento(
            log,
            "pagina_leida",
            corrida_id=resumen.corrida_id,
            pagina=pagina.numero,
            usuarios=len(pagina.items),
        )
        for crudo in pagina.items:
            if debe_detenerse():
                resumen.resultado = "interrumpida"
                return
            resumen.recibidos += 1
            try:
                usuario = UsuarioDestinatario.model_validate(crudo)
            except ValidationError as error:
                resumen.omitidos += 1
                _registrar_omitido(crudo, error)
                continue
            if usuario.user_id in vistos:
                resumen.repetidos += 1
                continue
            vistos.add(usuario.user_id)
            mensaje = construir_mensaje(usuario, resumen.corrida_id, resumen.fecha, resumen.modulo)
            try:
                publicador.publicar(mensaje)
            except PublicacionError as error:
                resumen.fallidos += 1
                consecutivos += 1
                evento(
                    log,
                    "publicacion_fallida",
                    logging.WARNING,
                    user_id=usuario.user_id,
                    motivo=str(error),
                )
                if consecutivos >= cfg.max_consecutive_publish_failures:
                    raise CorridaAbortada(
                        f"RabbitMQ no confirma publicaciones ({consecutivos} fallos seguidos)"
                    ) from None
                continue
            consecutivos = 0
            resumen.publicados += 1


def _registrar_omitido(crudo: object, error: ValidationError) -> None:
    """Registra solo el user_id (si existe) y los nombres de campos inválidos, nunca sus valores."""
    user_id = crudo.get("user_id") if isinstance(crudo, dict) else None
    campos = sorted({str(e["loc"][0]) if e["loc"] else "?" for e in error.errors()})
    evento(
        log,
        "usuario_omitido",
        user_id=user_id if isinstance(user_id, int) else None,
        campos_invalidos=campos,
    )
