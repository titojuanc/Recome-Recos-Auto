from __future__ import annotations

from datetime import date, timedelta

import pytest

from recos_auto.cron.modulo import modulo_para

REF = date(2026, 10, 5)


def test_alterna_dia_por_medio_desde_la_referencia():
    assert modulo_para(date(2026, 10, 5), REF) == "peliculas"
    assert modulo_para(date(2026, 10, 6), REF) == "juegos"
    assert modulo_para(date(2026, 10, 7), REF) == "peliculas"


def test_fecha_anterior_a_la_referencia():
    assert modulo_para(date(2026, 10, 4), REF) == "juegos"
    assert modulo_para(date(2026, 10, 3), REF) == "peliculas"


def test_misma_fecha_da_el_mismo_resultado():
    assert modulo_para(date(2026, 11, 20), REF) == modulo_para(date(2026, 11, 20), REF)


@pytest.mark.parametrize(
    "inicio",
    [date(2026, 12, 30), date(2027, 1, 30), date(2028, 2, 27), date(2026, 10, 30)],
)
def test_sin_saltos_ni_repeticiones_en_cambios_de_mes_y_anio(inicio):
    modulos = [modulo_para(inicio + timedelta(days=i), REF) for i in range(6)]
    for anterior, siguiente in zip(modulos, modulos[1:], strict=False):
        assert anterior != siguiente


def test_anio_bisiesto():
    assert modulo_para(date(2028, 2, 29), REF) != modulo_para(date(2028, 3, 1), REF)
    assert modulo_para(date(2028, 2, 28), REF) != modulo_para(date(2028, 2, 29), REF)


def test_cambia_con_otra_referencia():
    assert modulo_para(REF, date(2026, 10, 6)) == "juegos"
