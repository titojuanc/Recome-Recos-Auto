from __future__ import annotations

import dataclasses
import uuid
from datetime import date
from unittest.mock import MagicMock

import pika.exceptions
import pytest

from recos_auto.common.mensajes import UsuarioDestinatario, construir_mensaje
from recos_auto.cron.api_general import Pagina
from recos_auto.cron.corrida import ejecutar_corrida
from recos_auto.cron.publicador import PublicacionError, Publicador


def _mensaje(user_id: int = 42):
    usuario = UsuarioDestinatario(
        recommendation_id=uuid.UUID(int=user_id),
        user_id=user_id,
        nombre="Ana",
        email="ana@example.com",
    )
    return construir_mensaje(usuario, "c1", date(2026, 10, 5), "peliculas")


class CanalFalso:
    def __init__(self, errores: list[Exception] | None = None):
        self.errores = list(errores or [])
        self.intentos = 0
        self.publicados = 0

    def confirm_delivery(self):
        pass

    def basic_publish(self, **_kwargs):
        self.intentos += 1
        if self.errores:
            raise self.errores.pop(0)
        self.publicados += 1


def _publicador(config, canal, esperas, **cambios):
    cfg = dataclasses.replace(config, **cambios) if cambios else config
    return Publicador(cfg, canal=canal, dormir=esperas.append)


def test_reintenta_un_mensaje_no_confirmado_y_lo_publica(config):
    canal = CanalFalso([pika.exceptions.NackError([])])
    esperas: list[float] = []
    _publicador(config, canal, esperas).publicar(_mensaje())
    assert canal.publicados == 1
    assert canal.intentos == 2
    assert esperas == [0.5]


def test_backoff_exponencial_en_la_publicacion(config):
    canal = CanalFalso([pika.exceptions.NackError([])] * 3)
    esperas: list[float] = []
    _publicador(config, canal, esperas).publicar(_mensaje())
    assert esperas == [0.5, 1.0, 2.0]


def test_agotados_los_reintentos_falla_sin_datos_personales(config):
    canal = CanalFalso([pika.exceptions.UnroutableError([])] * 10)
    with pytest.raises(PublicacionError) as exc:
        _publicador(config, canal, []).publicar(_mensaje())
    assert canal.intentos == config.publish_max_retries + 1
    assert "ana@example.com" not in str(exc.value)
    assert config.rabbitmq_url not in str(exc.value)


def test_sin_reintentos_configurados_falla_de_inmediato(config):
    canal = CanalFalso([pika.exceptions.NackError([])])
    with pytest.raises(PublicacionError):
        _publicador(config, canal, [], publish_max_retries=0).publicar(_mensaje())
    assert canal.intentos == 1


# --- reconexión y conexión inicial ---------------------------------------------------------


def _conexion(cerrada: bool, canal) -> MagicMock:
    conexion = MagicMock()
    conexion.is_closed = cerrada
    conexion.is_open = not cerrada
    conexion.channel.return_value = canal
    canal.is_closed = cerrada
    return conexion


@pytest.fixture
def sin_topologia(mocker):
    return mocker.patch("recos_auto.cron.publicador.declarar_topologia")


def test_reconecta_si_se_pierde_la_conexion(config, mocker, sin_topologia):
    canal1 = CanalFalso([pika.exceptions.StreamLostError("perdida")])
    canal2 = CanalFalso()
    conexiones = [_conexion(True, canal1), _conexion(False, canal2)]
    abrir = mocker.patch(
        "recos_auto.cron.publicador.pika.BlockingConnection", side_effect=conexiones
    )
    publicador = Publicador(config, dormir=lambda s: None)
    publicador.abrir()
    publicador.publicar(_mensaje())
    assert abrir.call_count == 2
    assert canal2.publicados == 1


def test_la_conexion_inicial_se_reintenta(config, mocker, sin_topologia):
    canal = CanalFalso()
    ok = _conexion(False, canal)
    mocker.patch(
        "recos_auto.cron.publicador.pika.BlockingConnection",
        side_effect=[
            pika.exceptions.AMQPConnectionError(),
            pika.exceptions.AMQPConnectionError(),
            ok,
        ],
    )
    esperas: list[float] = []
    Publicador(config, dormir=esperas.append).abrir()
    assert esperas == [0.5, 1.0]


def test_conexion_inicial_imposible_falla_sin_exponer_credenciales(config, mocker, sin_topologia):
    mocker.patch(
        "recos_auto.cron.publicador.pika.BlockingConnection",
        side_effect=pika.exceptions.AMQPConnectionError(),
    )
    with pytest.raises(PublicacionError) as exc:
        Publicador(config, dormir=lambda s: None).abrir()
    assert "secreto" not in str(exc.value)


def test_cola_existente_con_otros_parametros_es_error_claro(config, mocker):
    mocker.patch("recos_auto.cron.publicador.pika.BlockingConnection")
    mocker.patch(
        "recos_auto.cron.publicador.declarar_topologia",
        side_effect=pika.exceptions.ChannelClosedByBroker(406, "PRECONDITION_FAILED"),
    )
    with pytest.raises(PublicacionError, match="PRECONDITION_FAILED"):
        Publicador(config, dormir=lambda s: None).abrir()


# --- efecto sobre la corrida ---------------------------------------------------------------


class ApiFalsa:
    def __init__(self, cantidad: int):
        self.cantidad = cantidad

    def paginas(self):
        yield Pagina(
            numero=1,
            items=[
                {
                    "recommendation_id": str(uuid.UUID(int=i)),
                    "user_id": i,
                    "nombre": f"U{i}",
                    "email": f"u{i}@example.com",
                }
                for i in range(1, self.cantidad + 1)
            ],
        )


class PublicadorQueFalla:
    def __init__(self, fallan: set[int]):
        self.fallan = fallan
        self.publicados: list[int] = []

    def publicar(self, mensaje):
        if mensaje.user_id in self.fallan:
            raise PublicacionError("el broker no confirmó la publicación (NackError)")
        self.publicados.append(mensaje.user_id)


def test_un_fallo_aislado_se_cuenta_y_la_corrida_sigue(config):
    pub = PublicadorQueFalla({2})
    resumen = ejecutar_corrida(config, ApiFalsa(4), pub)
    assert (resumen.publicados, resumen.fallidos) == (3, 1)
    assert resumen.resultado == "parcial"
    assert pub.publicados == [1, 3, 4]


def test_fallos_consecutivos_abortan_la_corrida(config):
    cfg = dataclasses.replace(config, max_consecutive_publish_failures=3)
    pub = PublicadorQueFalla(set(range(1, 100)))
    resumen = ejecutar_corrida(cfg, ApiFalsa(50), pub)
    assert resumen.resultado == "error"
    assert resumen.fallidos == 3
    assert resumen.recibidos == 3  # no siguió procesando
    assert "RabbitMQ" in resumen.error


def test_un_exito_reinicia_la_cuenta_de_fallos_consecutivos(config):
    cfg = dataclasses.replace(config, max_consecutive_publish_failures=3)
    pub = PublicadorQueFalla({1, 2, 4, 5, 7, 8})  # nunca 3 seguidos
    resumen = ejecutar_corrida(cfg, ApiFalsa(9), pub)
    assert resumen.resultado == "parcial"
    assert (resumen.publicados, resumen.fallidos) == (3, 6)


def test_los_fallos_se_registran_sin_datos_personales(config, capsys):
    import logging

    from recos_auto.common.logs import configurar_logs

    configurar_logs("INFO")
    ejecutar_corrida(config, ApiFalsa(2), PublicadorQueFalla({1}))
    salida = capsys.readouterr().out
    logging.getLogger().handlers.clear()
    assert "publicacion_fallida" in salida
    assert "u1@example.com" not in salida
    assert "U1" not in salida
