from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from recos_auto.cron.api_general import Pagina
from recos_auto.cron.corrida import ejecutar_corrida

ZONA = timezone(timedelta(hours=-3))


class ApiFalsa:
    def __init__(self, paginas: list[list[dict]]):
        self._paginas = paginas

    def paginas(self):
        for i, items in enumerate(self._paginas, 1):
            yield Pagina(numero=i, items=items)


class PublicadorFalso:
    def __init__(self):
        self.mensajes = []

    def publicar(self, mensaje):
        self.mensajes.append(mensaje)


def usuario(i: int, **cambios) -> dict:
    base = {
        "recommendation_id": f"00000000-0000-0000-0000-{i:012d}",
        "user_id": i,
        "nombre": f"Usuario {i}",
        "email": f"u{i}@example.com",
        "idioma": "es",
    }
    base.update(cambios)
    return base


def reloj_fijo(anio=2026, mes=10, dia=5, hora=12):
    return lambda: datetime(anio, mes, dia, hora, 0, tzinfo=ZONA)


def correr(paginas, config, reloj=None, fecha=None):
    pub = PublicadorFalso()
    resumen = ejecutar_corrida(
        config, ApiFalsa(paginas), pub, fecha=fecha, reloj=reloj or reloj_fijo()
    )
    return resumen, pub


def test_publica_un_mensaje_por_usuario_valido(config):
    resumen, pub = correr([[usuario(1), usuario(2)], [usuario(3)]], config)
    assert resumen.recibidos == 3
    assert resumen.publicados == 3
    assert resumen.paginas == 2
    assert resumen.resultado == "exito"
    assert [m.user_id for m in pub.mensajes] == [1, 2, 3]


def test_sin_usuarios_termina_bien(config):
    resumen, pub = correr([[]], config)
    assert (resumen.recibidos, resumen.publicados) == (0, 0)
    assert resumen.resultado == "exito"
    assert pub.mensajes == []


@pytest.mark.parametrize(
    "invalido",
    [
        usuario(2, recommendation_id=None),
        usuario(2, user_id=None),
        usuario(2, email=None),
        usuario(2, email="sin-arroba"),
        usuario(2, nombre=""),
    ],
)
def test_omite_usuarios_invalidos_sin_abortar(config, invalido):
    resumen, pub = correr([[usuario(1), invalido, usuario(3)]], config)
    assert resumen.omitidos == 1
    assert resumen.publicados == 2
    assert [m.user_id for m in pub.mensajes] == [1, 3]
    assert resumen.resultado == "exito"


def test_usuario_sin_campos_se_omite(config):
    resumen, _ = correr([[{}, usuario(1)]], config)
    assert (resumen.omitidos, resumen.publicados) == (1, 1)


def test_deduplica_por_user_id_entre_paginas(config):
    resumen, pub = correr([[usuario(1), usuario(2)], [usuario(2), usuario(3)]], config)
    assert resumen.repetidos == 1
    assert resumen.publicados == 3
    assert [m.user_id for m in pub.mensajes] == [1, 2, 3]


def test_invariante_de_contadores(config):
    paginas = [[usuario(1), usuario(1), {}, usuario(2, email="x"), usuario(3)]]
    r, _ = correr(paginas, config)
    assert r.recibidos == r.publicados + r.omitidos + r.repetidos + r.fallidos == 5


def test_modulo_y_fecha_salen_del_reloj_en_utc_menos_3(config):
    resumen, pub = correr([[usuario(1)]], config, reloj=reloj_fijo(dia=6))
    assert resumen.fecha == date(2026, 10, 6)
    assert resumen.modulo == "juegos"
    assert pub.mensajes[0].modulo == "juegos"
    assert pub.mensajes[0].fecha == date(2026, 10, 6)


def test_la_fecha_se_convierte_a_la_zona_configurada(config):
    # 2026-10-06 01:00 UTC es todavía 2026-10-05 en UTC-3
    reloj = lambda: datetime(2026, 10, 6, 1, 0, tzinfo=UTC)  # noqa: E731
    resumen, _ = correr([[usuario(1)]], config, reloj=reloj)
    assert resumen.fecha == date(2026, 10, 5)
    assert resumen.modulo == "peliculas"


def test_fecha_explicita_cambia_el_modulo(config):
    resumen, pub = correr([[usuario(1)]], config, fecha=date(2026, 10, 7))
    assert resumen.modulo == "peliculas"
    resumen, pub = correr([[usuario(1)]], config, fecha=date(2026, 10, 6))
    assert resumen.modulo == "juegos"
    assert pub.mensajes[0].modulo == "juegos"


def test_todos_los_mensajes_de_una_corrida_llevan_el_mismo_modulo_y_fecha(config):
    _, pub = correr([[usuario(i) for i in range(1, 30)]], config)
    assert {m.modulo for m in pub.mensajes} == {"peliculas"}
    assert {m.fecha for m in pub.mensajes} == {date(2026, 10, 5)}
    assert len({m.corrida_id for m in pub.mensajes}) == 1


def test_fecha_y_modulo_se_fijan_al_iniciar_aunque_pase_la_medianoche(config):
    antes = datetime(2026, 10, 5, 23, 59, tzinfo=ZONA)
    despues = datetime(2026, 10, 6, 0, 1, tzinfo=ZONA)
    ticks = itertools.chain([antes], itertools.repeat(despues))
    resumen, pub = correr([[usuario(1), usuario(2)]], config, reloj=lambda: next(ticks))
    assert resumen.fecha == date(2026, 10, 5)
    assert {m.fecha for m in pub.mensajes} == {date(2026, 10, 5)}
    assert {m.modulo for m in pub.mensajes} == {"peliculas"}


def test_misma_identidad_al_relanzar_la_corrida(config):
    _, primera = correr([[usuario(1), usuario(2)]], config)
    _, segunda = correr([[usuario(1), usuario(2)]], config)
    assert [m.message_id for m in primera.mensajes] == [m.message_id for m in segunda.mensajes]
    assert primera.mensajes[0].corrida_id != segunda.mensajes[0].corrida_id


def test_el_resumen_incluye_duracion(config):
    inicio = datetime(2026, 10, 5, 12, 0, 0, tzinfo=ZONA)
    ticks = itertools.chain([inicio], itertools.repeat(inicio + timedelta(seconds=90)))
    resumen, _ = correr([[usuario(1)]], config, reloj=lambda: next(ticks))
    assert resumen.duracion_s == 90
