from __future__ import annotations

import dataclasses

import httpx
import pytest

from recos_auto.cron.api_general import ApiGeneral, ApiGeneralError


def _cliente(config, api, esperas: list[float], **cambios):
    cfg = dataclasses.replace(config, **cambios) if cambios else config
    return ApiGeneral(cfg, transport=api.transporte(), dormir=esperas.append)


@pytest.mark.parametrize("estado", [500, 502, 503, 504, 429])
def test_errores_transitorios_se_reintentan_y_luego_sigue(config, api_mock_factory, estado):
    api = api_mock_factory(5)
    api.forzar = [estado]
    esperas: list[float] = []
    [pagina] = list(_cliente(config, api, esperas).paginas())
    assert len(pagina.items) == 5
    assert len(api.pedidos) == 2
    assert esperas == [1.0]


@pytest.mark.parametrize(
    "error",
    [httpx.ReadTimeout("t"), httpx.ConnectError("c"), httpx.RemoteProtocolError("p")],
)
def test_timeouts_y_errores_de_red_se_reintentan(config, api_mock_factory, error):
    api = api_mock_factory(3)
    api.forzar = [error]
    [pagina] = list(_cliente(config, api, []).paginas())
    assert len(pagina.items) == 3
    assert len(api.pedidos) == 2


def test_backoff_exponencial(config, api_mock_factory):
    api = api_mock_factory(3)
    api.forzar = [503, 503, 503]
    esperas: list[float] = []
    list(_cliente(config, api, esperas).paginas())
    assert esperas == [1.0, 2.0, 4.0]
    assert len(api.pedidos) == 4


def test_backoff_configurable(config, api_mock_factory):
    api = api_mock_factory(3)
    api.forzar = [503, 503]
    esperas: list[float] = []
    list(_cliente(config, api, esperas, api_retry_backoff_s=0.5).paginas())
    assert esperas == [0.5, 1.0]


def test_agotados_los_reintentos_falla_con_error_transitorio(config, api_mock_factory):
    api = api_mock_factory(3)
    api.forzar = [503] * 10
    with pytest.raises(ApiGeneralError) as exc:
        list(_cliente(config, api, []).paginas())
    assert exc.value.estado == 503
    assert exc.value.transitorio is True
    assert len(api.pedidos) == config.api_max_retries + 1


def test_sin_reintentos_configurados_falla_de_inmediato(config, api_mock_factory):
    api = api_mock_factory(3)
    api.forzar = [503]
    with pytest.raises(ApiGeneralError):
        list(_cliente(config, api, [], api_max_retries=0).paginas())
    assert len(api.pedidos) == 1


@pytest.mark.parametrize("estado", [400, 401, 403, 404])
def test_errores_no_transitorios_no_se_reintentan(config, api_mock_factory, estado):
    api = api_mock_factory(3)
    api.forzar = [estado, 200, 200]
    esperas: list[float] = []
    with pytest.raises(ApiGeneralError) as exc:
        list(_cliente(config, api, esperas).paginas())
    assert exc.value.estado == estado
    assert exc.value.transitorio is False
    assert len(api.pedidos) == 1
    assert esperas == []


def test_el_reintento_de_la_pagina_2_no_repite_la_pagina_1(config, api_mock_factory):
    api = api_mock_factory(250)
    api.forzar = [503]
    api.forzar_a_partir_del_pedido = 2
    paginas = list(_cliente(config, api, [], page_size=100).paginas())
    assert [len(p.items) for p in paginas] == [100, 100, 50]
    tokens = [p.url.params.get("page_token") for p in api.pedidos]
    assert tokens == [None, "100", "100", "200"]
