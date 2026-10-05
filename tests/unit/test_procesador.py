"""Procesador: cada tipo de fallo se traduce en el Resultado correcto (T015, T022)."""

import json
import uuid

import pytest

from recos_auto.worker import procesador as p
from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.publicador import ErrorPublicacion
from recos_auto.worker.recomendaciones import ErrorRecomendacion, Recomendacion
from tests.conftest import mensaje_usuario_dict

BASE = {
    "API_GENERAL_BASE_URL": "http://api.test/api/v1",
    "API_GENERAL_API_KEY": "local.clave-secreta",
    "RABBITMQ_URL": "amqp://usuario:secreto@rabbit.test:5672/",
}
CFG = ConfigWorker.from_env(BASE)


def _rec(rid, modulo="peliculas"):
    return Recomendacion(rid, uuid.UUID(int=999), modulo, "Matrix", 1)


def _ok(rid, modulo):
    return _rec(rid, modulo)


def _cuerpo(**cambios):
    d = mensaje_usuario_dict(7)
    d.update(cambios)
    return json.dumps(d).encode()


def test_notificado_publica_una_vez_con_mail_del_mensaje():
    enviados = []
    r = p.procesar(_cuerpo(), CFG, _ok, enviados.append)
    assert r.tipo == p.NOTIFICADO
    assert len(enviados) == 1
    assert enviados[0].mail == "u7@example.com"
    assert enviados[0].destinatario == 7


@pytest.mark.parametrize("cuerpo", [b"no es json", b"{}", b'{"version": 1}'])
def test_mensaje_malformado_es_invalido(cuerpo):
    enviados = []
    assert p.procesar(cuerpo, CFG, _ok, enviados.append).tipo == p.INVALIDO
    assert enviados == []


def test_mail_invalido_es_invalido():
    assert p.procesar(_cuerpo(email="no-es-mail"), CFG, _ok, lambda n: None).tipo == p.INVALIDO


@pytest.mark.parametrize(
    "clase,esperado",
    [
        ("sin_recomendacion", p.SIN_RECOMENDACION),
        ("invalido", p.INVALIDO),
        ("transitorio", p.TRANSITORIO),
    ],
)
def test_clases_de_error_de_la_api(clase, esperado):
    def falla(*_):
        raise ErrorRecomendacion(clase, "http_x")

    enviados = []
    r = p.procesar(_cuerpo(), CFG, falla, enviados.append)
    assert r.tipo == esperado
    assert enviados == []


def test_fallo_de_publicacion_es_transitorio():
    def rota(_):
        raise ErrorPublicacion("sin confirmar")

    assert p.procesar(_cuerpo(), CFG, _ok, rota).tipo == p.TRANSITORIO


def test_el_motivo_no_filtra_datos_personales():
    r = p.procesar(_cuerpo(email="no-es-mail"), CFG, _ok, lambda n: None)
    assert "no-es-mail" not in r.motivo
    assert "Usuario" not in r.motivo
