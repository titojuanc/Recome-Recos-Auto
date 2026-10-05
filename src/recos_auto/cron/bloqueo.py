"""Una sola corrida a la vez por contenedor, con `flock` no bloqueante (FR-011)."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

RUTA_POR_DEFECTO = "/tmp/recos-auto-cron.lock"  # noqa: S108 - por contenedor, sin volúmenes


class BloqueoOcupado(Exception):
    """Ya hay otra corrida en ejecución."""


class Bloqueo:
    def __init__(self, ruta: str | os.PathLike = RUTA_POR_DEFECTO):
        self._ruta = Path(ruta)
        self._fd: int | None = None

    def __enter__(self) -> Bloqueo:
        fd = os.open(self._ruta, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise BloqueoOcupado("ya hay otra corrida en ejecución") from None
        self._fd = fd
        return self

    def __exit__(self, *_exc) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
