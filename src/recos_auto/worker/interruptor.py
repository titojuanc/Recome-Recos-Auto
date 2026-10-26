"""Interruptor (circuit breaker) compartido por los hilos del worker (FR-024, research D7).

Estados: cerrado -> abierto (tras `fallos` fallos seguidos) -> semiabierto (una sola sonda)
-> cerrado (éxito) o abierto de nuevo (fallo, con backoff exponencial acotado).
`fallos == 0` lo deshabilita.
"""

from __future__ import annotations

import threading
import time

CERRADO = "cerrado"
ABIERTO = "abierto"
SEMIABIERTO = "semiabierto"


class Interruptor:
    def __init__(
        self,
        fallos: int,
        backoff_s: float,
        backoff_max_s: float,
        reloj=time.monotonic,
    ):
        self._umbral = fallos
        self._backoff = backoff_s
        self._backoff_max = max(backoff_max_s, backoff_s)
        self._reloj = reloj
        self._lock = threading.Lock()
        self._estado = CERRADO
        self._consecutivos = 0
        self._aperturas = 0
        self._hasta = 0.0

    @property
    def habilitado(self) -> bool:
        return self._umbral > 0

    @property
    def estado(self) -> str:
        with self._lock:
            return self._estado

    def espera(self) -> float:
        """Segundos que hay que esperar antes de llamar a la API (0 = se puede intentar).

        Cuando vence el backoff, el primer llamador pasa a ser la única sonda (semiabierto).
        """
        with self._lock:
            if self._estado == CERRADO:
                return 0.0
            if self._estado == SEMIABIERTO:
                return max(self._backoff, 0.05)  # ya hay una sonda en curso
            restante = self._hasta - self._reloj()
            if restante > 0:
                return restante
            self._estado = SEMIABIERTO
            return 0.0

    def exito(self) -> None:
        with self._lock:
            self._estado = CERRADO
            self._consecutivos = 0
            self._aperturas = 0

    def fallo(self) -> bool:
        """Registra un fallo transitorio. Devuelve True si el interruptor quedó abierto."""
        if not self.habilitado:
            return False
        with self._lock:
            self._consecutivos += 1
            if self._estado == SEMIABIERTO or self._consecutivos >= self._umbral:
                pausa = min(self._backoff * (2**self._aperturas), self._backoff_max)
                self._aperturas += 1
                self._estado = ABIERTO
                self._hasta = self._reloj() + pausa
            return self._estado == ABIERTO
