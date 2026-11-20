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


def test_sin_push_y_con_el_mail_apagado_no_se_notifica_y_se_da_por_atendido():
    enviados = []
    sin_canal = lambda rid, modulo: Recomendacion(  # noqa: E731
        rid, uuid.UUID(int=999), modulo, "Matrix", 1, mail_enabled=False
    )
    r = p.procesar(_cuerpo(), CFG, sin_canal, enviados.append)
    assert r.tipo == p.SIN_RECOMENDACION
    assert r.motivo == "sin_canal_activo"
    assert enviados == []


def _con_push_y_mail(rid, modulo):
    from recos_auto.worker.recomendaciones import PushKeys, PushSub

    sub = PushSub(endpoint="https://push.example.test/abc", keys=PushKeys(p256dh="p", auth="a"))
    return Recomendacion(rid, uuid.UUID(int=999), modulo, "Matrix", 1, push_sub=sub)


def test_con_push_y_mail_activos_se_publican_los_dos_canales():
    enviados = []
    r = p.procesar(_cuerpo(), CFG, _con_push_y_mail, enviados.append)
    assert r.tipo == p.NOTIFICADO
    assert [n.canal for n in enviados] == ["push", "mail"]
    assert len({n.id_mensaje for n in enviados}) == 2


def test_si_falla_el_segundo_canal_es_transitorio_y_se_reintenta_todo():
    enviados = []

    def segunda_falla(n):
        if enviados:
            raise ErrorPublicacion("sin confirmar")
        enviados.append(n)

    assert p.procesar(_cuerpo(), CFG, _con_push_y_mail, segunda_falla).tipo == p.TRANSITORIO
