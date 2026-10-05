from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import jsonschema
import pytest

from recos_auto.common.logs import configurar_logs
from recos_auto.cron.api_general import ApiGeneral
from recos_auto.cron.corrida import ejecutar_corrida
from recos_auto.cron.publicador import Publicador

pytestmark = pytest.mark.integration

RAIZ = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (RAIZ / "specs/001-cron-carga-usuarios/contracts/mensaje-usuario.schema.json").read_text()
)


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


def _correr(cfg, api):
    configurar_logs("WARNING")
    cliente = ApiGeneral(cfg, transport=api.transporte(), dormir=lambda s: None)
    with Publicador(cfg) as publicador:
        return ejecutar_corrida(cfg, cliente, publicador)


def test_250_usuarios_en_3_paginas_dejan_250_mensajes_validos(
    config_rabbit, conexion_rabbit, api_mock_factory
):
    cfg = dataclasses.replace(config_rabbit, page_size=100)
    resumen = _correr(cfg, api_mock_factory(250))
    assert (resumen.paginas, resumen.recibidos, resumen.publicados) == (3, 250, 250)

    mensajes = _vaciar(conexion_rabbit.channel(), cfg.users_queue, esperados=250)
    assert len(mensajes) == 250
    assert len({m["message_id"] for m in mensajes}) == 250
    for mensaje in mensajes:
        jsonschema.validate(mensaje, SCHEMA)


def test_api_general_sin_usuarios_no_publica_nada(config_rabbit, conexion_rabbit, api_mock_factory):
    resumen = _correr(config_rabbit, api_mock_factory(0))
    assert resumen.publicados == 0
    assert resumen.resultado == "exito"
    canal = conexion_rabbit.channel()
    assert _vaciar(canal, config_rabbit.users_queue, esperados=0, segundos=1.0) == []
