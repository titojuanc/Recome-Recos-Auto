"""Módulo del día: alternancia día por medio, sin estado (FR-009)."""

from __future__ import annotations

from datetime import date


def modulo_para(fecha: date, referencia: date) -> str:
    """`peliculas` en los días pares desde la referencia y `juegos` en los impares.

    Python devuelve un módulo no negativo también para días anteriores a la referencia.
    """
    return "peliculas" if (fecha - referencia).days % 2 == 0 else "juegos"
