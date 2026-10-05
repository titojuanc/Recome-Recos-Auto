from __future__ import annotations

import dataclasses

import httpx
import pytest

from recos_auto.cron.api_general import ApiGeneral, ApiGeneralError


def _cliente(config, api, **cambios):
    cfg = dataclasses.replace(config, **cambios) if cambios else config
    return ApiGeneral(cfg, transport=api.transporte(), dormir=lambda s: None)


def test_recorre_todas_las_paginas(config, api_mock_factory):
    api = api_mock_factory(250)
    paginas = list(_cliente(config, api, page_size=100).paginas())
    assert [p.numero for p in paginas] == [1, 2, 3]
    assert sum(len(p.items) for p in paginas) == 250
    assert len(api.pedidos) == 3


def test_envia_clave_tamano_y_token(config, api_mock_factory):
    api = api_mock_factory(150)
    list(_cliente(config, api, page_size=100).paginas())
    primero, segundo = api.pedidos
    assert primero.url.path == "/api/v1/internal/v1/notification-targets"
    assert primero.headers["X-Internal-API-Key"] == config.api_general_api_key
    assert primero.url.params["page_size"] == "100"
    assert "page_token" not in primero.url.params
    assert segundo.url.params["page_token"] == "100"


def test_sin_usuarios_devuelve_una_pagina_vacia(config, api_mock_factory):
    api = api_mock_factory(0)
    paginas = list(_cliente(config, api).paginas())
    assert len(paginas) == 1
    assert paginas[0].items == []


def test_token_repetido_corta_con_error(config, api_mock_factory):
    api = api_mock_factory(500)
    api.token_fijo = "7"
    with pytest.raises(ApiGeneralError, match="repetido"):
        list(_cliente(config, api, page_size=100).paginas())


def test_tope_de_paginas_evita_bucle_infinito(config, api_mock_factory):
    api = api_mock_factory(0)
    api.siempre_hay_mas = True  # nunca termina, con tokens distintos
    with pytest.raises(ApiGeneralError, match="tope"):
        list(_cliente(config, api, page_size=10, api_max_pages=3).paginas())
    assert len(api.pedidos) == 3


def test_pagina_sin_usuarios_validos_pero_con_token_nuevo_continua(config):
    respuestas = [
        {"items": [], "next_page_token": "5"},
        {"items": [{"user_id": 6}], "next_page_token": None},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=respuestas.pop(0))

    cliente = ApiGeneral(config, transport=httpx.MockTransport(handler), dormir=lambda s: None)
    paginas = list(cliente.paginas())
    assert [len(p.items) for p in paginas] == [0, 1]


def test_clave_invalida_es_error_fatal(config, api_mock_factory):
    api = api_mock_factory(5)
    api.clave = "otra-clave"
    with pytest.raises(ApiGeneralError) as exc:
        list(_cliente(config, api).paginas())
    assert exc.value.estado == 401


@pytest.mark.parametrize("cuerpo", [b"no es json", b'{"sin_items": []}', b'{"items": "x"}'])
def test_respuesta_malformada_es_error(config, cuerpo):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=cuerpo)

    cliente = ApiGeneral(config, transport=httpx.MockTransport(handler), dormir=lambda s: None)
    with pytest.raises(ApiGeneralError):
        list(cliente.paginas())


def test_los_errores_no_incluyen_la_clave(config, api_mock_factory):
    api = api_mock_factory(5)
    api.clave = "otra"
    with pytest.raises(ApiGeneralError) as exc:
        list(_cliente(config, api).paginas())
    assert config.api_general_api_key not in str(exc.value)
