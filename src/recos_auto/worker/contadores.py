"""Contadores del worker, seguros entre hilos (data-model.md)."""

from __future__ import annotations

import threading
import time

NOMBRES = (
    "recibidos",
    "notificados",
    "sin_recomendacion",
    "invalidos",
    "reintentados",
    "pausas_del_corte",
)


class Contadores:
    def __init__(self, reloj=time.monotonic):
        self._lock = threading.Lock()
        self._valores = dict.fromkeys(NOMBRES, 0)
        self._reloj = reloj
        self._inicio = reloj()

    def incrementar(self, nombre: str, cantidad: int = 1) -> None:
        if nombre not in self._valores:
            raise KeyError(nombre)
        with self._lock:
            self._valores[nombre] += cantidad

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._valores)

    def resumen(self) -> dict[str, int | float]:
        datos: dict[str, int | float] = dict(self.snapshot())
        datos["duracion_s"] = round(self._reloj() - self._inicio, 1)
        return datos
