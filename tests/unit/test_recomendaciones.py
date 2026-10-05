"""Cliente de recomendaciones y contrato con api-general (T013)."""

import uuid

import httpx
import pytest

from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.recomendaciones import (
    ClienteRecomendaciones,
    ErrorRecomendacion,
    limpiar_titulo,
)

BASE = {
    "API_GENERAL_BASE_URL": "http://api.test/api/v1",
    "API_GENERAL_API_KEY": "local.clave-secreta",
    "RABBITMQ_URL": "amqp://usuario:secreto@rabbit.test:5672/",
}
RID = uuid.UUID(int=7)
ITEM = uuid.UUID(int=99)


def _cliente(handler) -> ClienteRecomendaciones:
    return ClienteRecomendaciones(ConfigWorker.from_env(BASE), httpx.MockTransport(handler))


def _ok(titulo="Matrix", modulo="peliculas", rid=RID):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "recommendation_id": str(rid),
                "item_id": str(ITEM),
                "module": modulo,
                "titulo": titulo,
                "position": 1,
            },
        )

    return handler


def test_pide_url_modulo_y_clave():
    vistos = []

    def handler(request):
        vistos.append(request)
        return _ok()(request)

    rec = _cliente(handler).obtener(RID, "peliculas")
    assert rec.titulo == "Matrix"
    assert rec.item_id == ITEM
    assert vistos[0].url.path == f"/api/v1/internal/v1/notification-recommendations/{RID}"
    assert vistos[0].url.params["module"] == "peliculas"
    assert vistos[0].headers["X-Internal-API-Key"] == "local.clave-secreta"


@pytest.mark.parametrize(
    ("estado", "clase"),
    [
        (404, "sin_recomendacion"),
        (412, "sin_recomendacion"),
        (400, "invalido"),
        (409, "invalido"),
        (401, "transitorio"),
        (403, "transitorio"),
        (429, "transitorio"),
        (500, "transitorio"),
        (502, "transitorio"),
        (503, "transitorio"),
    ],
)
def test_clasificacion_por_estado(estado, clase):
    cliente = _cliente(lambda request: httpx.Response(estado, json={"error": "x"}))
    with pytest.raises(ErrorRecomendacion) as error:
        cliente.obtener(RID, "juegos")
    assert error.value.clase == clase


@pytest.mark.parametrize(
    "falla", [httpx.ReadTimeout("t"), httpx.ConnectError("c"), httpx.RemoteProtocolError("p")]
)
def test_red_y_timeout_son_transitorios(falla):
    def handler(request):
        raise falla

    with pytest.raises(ErrorRecomendacion) as error:
        _cliente(handler).obtener(RID, "juegos")
    assert error.value.clase == "transitorio"


def test_titulo_vacio_es_sin_recomendacion():
    with pytest.raises(ErrorRecomendacion) as error:
        _cliente(_ok(titulo="  \n\t ")).obtener(RID, "peliculas")
    assert (error.value.clase, error.value.motivo) == ("sin_recomendacion", "titulo_vacio")


def test_modulo_distinto_es_invalido_fr025():
    with pytest.raises(ErrorRecomendacion) as error:
        _cliente(_ok(modulo="juegos")).obtener(RID, "peliculas")
    assert (error.value.clase, error.value.motivo) == ("invalido", "modulo_distinto")


def test_recommendation_id_distinto_es_invalido_fr025():
    with pytest.raises(ErrorRecomendacion) as error:
        _cliente(_ok(rid=uuid.UUID(int=8))).obtener(RID, "peliculas")
    assert (error.value.clase, error.value.motivo) == ("invalido", "recommendation_id_distinto")


@pytest.mark.parametrize("cuerpo", [{}, {"titulo": "x"}, [], "texto"])
def test_respuesta_malformada_es_invalida(cuerpo):
    cliente = _cliente(lambda request: httpx.Response(200, json=cuerpo))
    with pytest.raises(ErrorRecomendacion) as error:
        cliente.obtener(RID, "peliculas")
    assert error.value.clase == "invalido"


def test_respuesta_no_json_es_invalida():
    cliente = _cliente(lambda request: httpx.Response(200, content=b"<html>"))
    with pytest.raises(ErrorRecomendacion) as error:
        cliente.obtener(RID, "peliculas")
    assert error.value.clase == "invalido"


def test_la_clave_nunca_aparece_en_los_errores():
    def handler(request):
        raise httpx.ConnectError("fallo con local.clave-secreta")

    with pytest.raises(ErrorRecomendacion) as error:
        _cliente(handler).obtener(RID, "peliculas")
    assert "local.clave-secreta" not in str(error.value)
    assert "local.clave-secreta" not in error.value.motivo


def test_sin_reintentos_propios():
    llamadas = []

    def handler(request):
        llamadas.append(1)
        return httpx.Response(503)

    with pytest.raises(ErrorRecomendacion):
        _cliente(handler).obtener(RID, "peliculas")
    assert len(llamadas) == 1


def test_limpiar_titulo():
    assert limpiar_titulo("  Hola\x00 \n mundo\t") == "Hola mundo"
    largo = limpiar_titulo("a" * 500)
    assert len(largo) == 120
    assert largo.endswith("…")
    assert limpiar_titulo("<b>Ñandú & Co</b>") == "<b>Ñandú & Co</b>"
