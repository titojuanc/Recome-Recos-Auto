from __future__ import annotations

import dataclasses
import json
import time
from datetime import date

import pytest

from recos_auto.common.logs import configurar_logs
from recos_auto.cron.api_general import ApiGeneral
from recos_auto.cron.corrida import ejecutar_corrida
from recos_auto.cron.publicador import Publicador

pytestmark = pytest.mark.integration


def _vaciar(canal, cola, esperados: int, segundos: float = 10.0) -> list[dict]:
    mensajes: list[dict] = []
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        metodo, _, cuerpo = canal.basic_get(cola, auto_ack=True)
        if metodo:
            mensajes.append(json.loads(cuerpo))
            continue
        if len(mensajes) >= esperados:
            break
        time.sleep(0.2)
    return mensajes


def _correr(cfg, api, fecha: date | None = None):
    configurar_logs("WARNING")
    cliente = ApiGeneral(cfg, transport=api.transporte(), dormir=lambda s: None)
    with Publicador(cfg) as publicador:
        return ejecutar_corrida(cfg, cliente, publicador, fecha=fecha)


def test_relanzar_la_misma_fecha_publica_los_mismos_message_id(
    config_rabbit, conexion_rabbit, api_mock_factory
):
    api = api_mock_factory(30)
    fecha = date(2026, 10, 7)
    _correr(config_rabbit, api, fecha)
    primera = _vaciar(conexion_rabbit.channel(), config_rabbit.users_queue, esperados=30)
    _correr(config_rabbit, api, fecha)
    segunda = _vaciar(conexion_rabbit.channel(), config_rabbit.users_queue, esperados=30)

    assert len(primera) == len(segunda) == 30
    assert {m["message_id"] for m in primera} == {m["message_id"] for m in segunda}
    assert {m["corrida_id"] for m in primera} != {m["corrida_id"] for m in segunda}


def test_otra_fecha_cambia_la_identidad_de_los_mensajes(
    config_rabbit, conexion_rabbit, api_mock_factory
):
    api = api_mock_factory(5)
    _correr(config_rabbit, api, date(2026, 10, 5))
    a = _vaciar(conexion_rabbit.channel(), config_rabbit.users_queue, esperados=5)
    _correr(config_rabbit, api, date(2026, 10, 6))
    b = _vaciar(conexion_rabbit.channel(), config_rabbit.users_queue, esperados=5)
    assert {m["message_id"] for m in a}.isdisjoint({m["message_id"] for m in b})
    assert {m["modulo"] for m in a} == {"peliculas"}
    assert {m["modulo"] for m in b} == {"juegos"}


def test_fallo_en_la_pagina_2_con_exito_al_reintentar_no_duplica(
    config_rabbit, conexion_rabbit, api_mock_factory
):
    cfg = dataclasses.replace(config_rabbit, page_size=100)
    api = api_mock_factory(250)
    api.forzar = [503]
    api.forzar_a_partir_del_pedido = 2
    resumen = _correr(cfg, api)

    assert resumen.resultado == "exito"
    assert resumen.publicados == 250
    assert len(api.pedidos) == 4  # 3 páginas + 1 reintento
    mensajes = _vaciar(conexion_rabbit.channel(), cfg.users_queue, esperados=250)
    assert len(mensajes) == 250
    assert len({m["message_id"] for m in mensajes}) == 250


def test_api_general_caida_termina_en_error_sin_publicar_de_mas(
    config_rabbit, conexion_rabbit, api_mock_factory
):
    cfg = dataclasses.replace(config_rabbit, page_size=100)
    api = api_mock_factory(250)
    api.forzar = [503] * 10
    api.forzar_a_partir_del_pedido = 2  # la página 1 sale bien
    resumen = _correr(cfg, api)

    assert resumen.resultado == "error"
    assert resumen.publicados == 100
    assert "503" in resumen.error
    mensajes = _vaciar(conexion_rabbit.channel(), cfg.users_queue, esperados=100)
    assert len(mensajes) == 100
