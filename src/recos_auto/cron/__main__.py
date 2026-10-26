"""CLI: `python -m recos_auto.cron run [--date YYYY-MM-DD]` (contracts/cli.md)."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from datetime import date
from pathlib import Path

from recos_auto.common.config import Config, ConfigError
from recos_auto.common.logs import configurar_logs, evento
from recos_auto.cron.api_general import ApiGeneral
from recos_auto.cron.bloqueo import RUTA_POR_DEFECTO, Bloqueo, BloqueoOcupado
from recos_auto.cron.corrida import codigo_de_salida, ejecutar_corrida
from recos_auto.cron.publicador import PublicacionError, Publicador

EXIT_CONFIG = 78
EXIT_BLOQUEO = codigo_de_salida("omitida_por_bloqueo")
log = logging.getLogger("recos_auto.cron")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m recos_auto.cron")
    sub = parser.add_subparsers(dest="comando", required=True)
    run = sub.add_parser("run", help="ejecuta una corrida completa")
    run.add_argument("--date", help="fecha de la corrida (YYYY-MM-DD); por defecto, hoy en UTC-3")
    boot = sub.add_parser("bootstrap", help="valida config y genera el crontab")
    boot.add_argument("ruta")
    return parser


def _ejecutar(cfg: Config, fecha: date | None) -> int:
    """Corrida con apagado ordenado: SIGTERM/SIGINT solo levantan una bandera, de modo que el
    mensaje en curso termina de publicarse y recién entonces se corta (FR-024)."""
    detener = threading.Event()
    anteriores = {
        sig: signal.signal(sig, lambda *_: detener.set()) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    api = ApiGeneral(cfg)
    try:
        with Publicador(cfg) as publicador:
            resumen = ejecutar_corrida(
                cfg, api, publicador, fecha=fecha, debe_detenerse=detener.is_set
            )
        return codigo_de_salida(resumen.resultado)
    except PublicacionError as error:
        evento(log, "corrida_finalizada", logging.ERROR, resultado="error", error=str(error))
        return codigo_de_salida("error")
    finally:
        api.cerrar()
        for sig, anterior in anteriores.items():
            signal.signal(sig, anterior)


def _run(args: argparse.Namespace, ruta_bloqueo: str | Path) -> int:
    try:
        cfg = Config.from_env()
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return EXIT_CONFIG
    fecha = None
    if args.date:
        try:
            fecha = date.fromisoformat(args.date)
        except ValueError:
            print("--date debe tener el formato YYYY-MM-DD", file=sys.stderr)
            return EXIT_CONFIG
    configurar_logs(cfg.log_level)
    try:
        with Bloqueo(ruta_bloqueo):
            return _ejecutar(cfg, fecha)
    except BloqueoOcupado:
        evento(log, "corrida_omitida_por_bloqueo", logging.WARNING)
        return EXIT_BLOQUEO


def _bootstrap(args: argparse.Namespace) -> int:
    from pathlib import Path

    from recos_auto.cron.bootstrap import preparar

    try:
        cfg = Config.from_env()
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return EXIT_CONFIG
    configurar_logs(cfg.log_level)
    preparar(cfg, Path(args.ruta))
    return 0


def main(argv: list[str] | None = None, *, ruta_bloqueo: str | Path = RUTA_POR_DEFECTO) -> int:
    args = _parser().parse_args(argv)
    if args.comando == "run":
        return _run(args, ruta_bloqueo)
    if args.comando == "bootstrap":
        return _bootstrap(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
