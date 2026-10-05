"""Arranque del contenedor: valida config, genera el crontab y registra la próxima corrida.

No ejecuta ninguna corrida al arrancar (FR-018); eso lo hace Supercronic según el horario.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from recos_auto.common.config import Config
from recos_auto.common.logs import evento

log = logging.getLogger("recos_auto.cron")

_RANGOS = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]


def _valores(campo: str, minimo: int, maximo: int) -> set[int]:
    salida: set[int] = set()
    for parte in campo.split(","):
        base, _, paso = parte.partition("/")
        paso_n = int(paso) if paso else 1
        if base == "*":
            desde, hasta = minimo, maximo
        elif "-" in base:
            a, b = base.split("-")
            desde, hasta = int(a), int(b)
        else:
            desde = int(base)
            hasta = maximo if paso else desde
        salida.update(range(desde, hasta + 1, paso_n))
    return salida


def proxima_corrida(cfg: Config, ahora: datetime | None = None) -> datetime | None:
    """Próxima coincidencia del horario cron (en la zona configurada), o None si no se halla."""
    try:
        campos = cfg.run_schedule.split()
        conjuntos = [_valores(c, lo, hi) for c, (lo, hi) in zip(campos, _RANGOS, strict=True)]
    except ValueError:
        return None
    minuto, hora, dia, mes, semana = conjuntos
    actual = (ahora or datetime.now(cfg.zona)).astimezone(cfg.zona)
    actual = actual.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        # el domingo es 0 en cron; weekday() devuelve 0 para el lunes
        if (
            actual.minute in minuto
            and actual.hour in hora
            and actual.day in dia
            and actual.month in mes
            and (actual.isoweekday() % 7) in semana
        ):
            return actual
        actual += timedelta(minutes=1)
    return None


def generar_crontab(cfg: Config, ruta: Path) -> None:
    """Escribe el crontab sin secretos: el job hereda el entorno del proceso."""
    ruta.write_text(
        f"CRON_TZ={cfg.run_timezone}\n{cfg.run_schedule} python -m recos_auto.cron run\n"
    )


def preparar(cfg: Config, ruta: Path) -> None:
    generar_crontab(cfg, ruta)
    proxima = proxima_corrida(cfg)
    evento(
        log,
        "bootstrap_ok",
        logging.INFO,
        zona=cfg.run_timezone,
        horario=cfg.run_schedule,
        proxima_corrida=proxima.isoformat() if proxima else None,
    )
    evento(log, "corrida_omitida_al_arrancar", logging.INFO, zona=cfg.run_timezone)
