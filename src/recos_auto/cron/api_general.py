"""Cliente de api-general: recorre `GET /internal/v1/notification-targets` página por página."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx

from recos_auto.common.config import Config
from recos_auto.common.logs import evento

RUTA = "/internal/v1/notification-targets"
log = logging.getLogger("recos_auto.cron.api_general")


class ApiGeneralError(Exception):
    """Error al leer usuarios. Nunca incluye la clave de servicio ni datos de usuarios."""

    def __init__(self, mensaje: str, estado: int | None = None, transitorio: bool = False):
        super().__init__(mensaje)
        self.estado = estado
        self.transitorio = transitorio


@dataclass(frozen=True)
class Pagina:
    numero: int
    items: list[dict]


class ApiGeneral:
    def __init__(
        self,
        cfg: Config,
        transport: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._cfg = cfg
        self._dormir = dormir
        self._url = cfg.api_general_base_url + RUTA
        self._cliente = httpx.Client(
            timeout=cfg.api_timeout_s,
            headers={"X-Internal-API-Key": cfg.api_general_api_key, "Accept": "application/json"},
            transport=transport,
        )

    def cerrar(self) -> None:
        self._cliente.close()

    def paginas(self) -> Iterator[Pagina]:
        """Genera todas las páginas. Corta con error ante un token repetido o el tope de páginas."""
        token: str | None = None
        vistos: set[str] = set()
        numero = 0
        while True:
            if numero >= self._cfg.api_max_pages:
                raise ApiGeneralError("se superó el tope de páginas configurado")
            cuerpo = self._pedir(token)
            numero += 1
            yield Pagina(numero=numero, items=cuerpo["items"])
            siguiente = cuerpo.get("next_page_token")
            if not siguiente:
                return
            if siguiente == token or siguiente in vistos:
                raise ApiGeneralError("next_page_token repetido: la paginación no avanza")
            vistos.add(siguiente)
            token = siguiente

    def _pedir(self, token: str | None) -> dict:
        """Pide una página con reintentos acotados y backoff exponencial solo ante errores
        transitorios (red, timeout, 429, 5xx). 400/401/403/404 fallan de inmediato (FR-005)."""
        intentos = self._cfg.api_max_retries + 1
        for intento in range(intentos):
            try:
                return self._pedir_una_vez(token)
            except ApiGeneralError as error:
                if not error.transitorio or intento == intentos - 1:
                    raise
                espera = self._cfg.api_retry_backoff_s * 2**intento
                evento(
                    log,
                    "api_general_reintento",
                    logging.WARNING,
                    intento=intento + 1,
                    estado=error.estado,
                    espera_s=espera,
                )
                self._dormir(espera)
        raise AssertionError("inalcanzable")  # pragma: no cover

    def _pedir_una_vez(self, token: str | None) -> dict:
        params: dict[str, str | int] = {"page_size": self._cfg.page_size}
        if token:
            params["page_token"] = token
        try:
            respuesta = self._cliente.get(self._url, params=params)
        except httpx.HTTPError as error:
            raise ApiGeneralError(
                f"fallo de red al consultar api-general ({type(error).__name__})", transitorio=True
            ) from None
        if respuesta.status_code != 200:
            estado = respuesta.status_code
            raise ApiGeneralError(
                f"api-general respondió {estado}",
                estado=estado,
                transitorio=estado == 429 or estado >= 500,
            )
        return _validar_cuerpo(respuesta)


def _validar_cuerpo(respuesta: httpx.Response) -> dict:
    try:
        cuerpo = respuesta.json()
    except ValueError:
        raise ApiGeneralError("api-general devolvió una respuesta que no es JSON") from None
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("items"), list):
        raise ApiGeneralError("api-general devolvió una respuesta sin la lista `items`")
    return cuerpo
