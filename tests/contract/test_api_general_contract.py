"""El cliente respeta el contrato documentado en contracts/api-general-notification-targets.md."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from recos_auto.common.mensajes import UsuarioDestinatario
from recos_auto.cron.api_general import ApiGeneral

RAIZ = Path(__file__).resolve().parents[2]
CONTRATO = RAIZ / "specs/001-cron-carga-usuarios/contracts/api-general-notification-targets.md"


def _ejemplo_del_contrato() -> dict:
    texto = CONTRATO.read_text()
    bloque = re.search(r"```json\n(.*?)```", texto, re.S)
    assert bloque, "el contrato debe incluir un ejemplo de respuesta JSON"
    return json.loads(bloque.group(1))


def test_el_ejemplo_del_contrato_se_parsea_como_usuario():
    cuerpo = _ejemplo_del_contrato()
    assert set(cuerpo) == {"items", "next_page_token"}
    for item in cuerpo["items"]:
        assert set(item) == {"recommendation_id", "user_id", "nombre", "email", "idioma"}
        UsuarioDestinatario.model_validate(item)


def test_el_cliente_consume_la_respuesta_del_contrato(config):
    cuerpo = dict(_ejemplo_del_contrato(), next_page_token=None)
    pedidos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, json=cuerpo)

    cliente = ApiGeneral(config, transport=httpx.MockTransport(handler), dormir=lambda s: None)
    [pagina] = list(cliente.paginas())
    assert pagina.items == cuerpo["items"]
    assert pedidos[0].method == "GET"
    assert pedidos[0].url.path.endswith("/internal/v1/notification-targets")
    assert "X-Internal-API-Key" in pedidos[0].headers


def test_idioma_puede_ser_null():
    item = dict(_ejemplo_del_contrato()["items"][0], idioma=None)
    assert UsuarioDestinatario.model_validate(item).idioma is None
