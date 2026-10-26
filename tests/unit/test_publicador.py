from __future__ import annotations

import json
import uuid
from datetime import date

import pika
import pika.exceptions
import pytest

from recos_auto.common.mensajes import UsuarioDestinatario, construir_mensaje
from recos_auto.cron.publicador import PublicacionError, Publicador


def _mensaje(user_id: int = 42):
    usuario = UsuarioDestinatario(
        recommendation_id=uuid.UUID(int=user_id),
        user_id=user_id,
        nombre="José 🎬",
        email="jose@example.com",
    )
    return construir_mensaje(usuario, "corrida1", date(2026, 10, 5), "peliculas")


class CanalFalso:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.publicados: list[dict] = []

    def basic_publish(self, exchange, routing_key, body, properties, mandatory):
        if self.error:
            raise self.error
        self.publicados.append(
            {
                "exchange": exchange,
                "routing_key": routing_key,
                "body": body,
                "properties": properties,
                "mandatory": mandatory,
            }
        )


def test_publica_en_la_cola_de_usuarios_por_el_exchange_por_defecto(config):
    canal = CanalFalso()
    Publicador(config, canal=canal).publicar(_mensaje())
    [pub] = canal.publicados
    assert pub["exchange"] == ""
    assert pub["routing_key"] == config.users_queue


def test_mensaje_persistente_con_propiedades(config):
    canal = CanalFalso()
    msg = _mensaje()
    Publicador(config, canal=canal).publicar(msg)
    props = canal.publicados[0]["properties"]
    assert props.delivery_mode == 2
    assert props.content_type == "application/json"
    assert props.message_id == str(msg.message_id)


def test_mandatory_activado(config):
    canal = CanalFalso()
    Publicador(config, canal=canal).publicar(_mensaje())
    assert canal.publicados[0]["mandatory"] is True


def test_el_cuerpo_es_json_utf8_con_el_mensaje(config):
    canal = CanalFalso()
    Publicador(config, canal=canal).publicar(_mensaje())
    cuerpo = json.loads(canal.publicados[0]["body"].decode("utf-8"))
    assert cuerpo["nombre"] == "José 🎬"
    assert cuerpo["user_id"] == 42
    assert cuerpo["modulo"] == "peliculas"


def test_no_ruteable_se_trata_como_fallo(config):
    canal = CanalFalso(error=pika.exceptions.UnroutableError([]))
    with pytest.raises(PublicacionError):
        Publicador(config, canal=canal).publicar(_mensaje())


def test_nack_del_broker_se_trata_como_fallo(config):
    canal = CanalFalso(error=pika.exceptions.NackError([]))
    with pytest.raises(PublicacionError):
        Publicador(config, canal=canal).publicar(_mensaje())


def test_el_error_no_incluye_datos_personales(config):
    canal = CanalFalso(error=pika.exceptions.UnroutableError([]))
    with pytest.raises(PublicacionError) as exc:
        Publicador(config, canal=canal).publicar(_mensaje())
    assert "jose@example.com" not in str(exc.value)
    assert "José" not in str(exc.value)
