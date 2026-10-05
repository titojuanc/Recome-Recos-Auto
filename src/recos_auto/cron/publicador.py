"""Publicación en RabbitMQ con confirmación del broker, reintentos y reconexión (FR-010)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import pika
import pika.exceptions

from recos_auto.common.config import Config
from recos_auto.common.logs import evento
from recos_auto.common.mensajes import MensajeUsuario
from recos_auto.common.topology import declarar_topologia

log = logging.getLogger("recos_auto.cron.publicador")


class PublicacionError(Exception):
    """Fallo al publicar o conectar. No incluye datos personales ni la URL de RabbitMQ."""


class Publicador:
    def __init__(
        self,
        cfg: Config,
        canal=None,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._cfg = cfg
        self._canal = canal
        self._inyectado = canal is not None  # en pruebas no se abre ni se reabre conexión
        self._dormir = dormir
        self._conexion = None

    def __enter__(self) -> Publicador:
        self.abrir()
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()

    @staticmethod
    def _espera(intento: int, base: float) -> float:
        return base * 2**intento

    def abrir(self) -> None:
        """Conecta y declara la topología. Reintenta solo los fallos de conexión."""
        if self._canal is not None:
            return
        intentos = self._cfg.publish_max_retries + 1
        for intento in range(intentos):
            try:
                self._conexion = pika.BlockingConnection(pika.URLParameters(self._cfg.rabbitmq_url))
                self._canal = self._conexion.channel()
                self._canal.confirm_delivery()
                declarar_topologia(self._canal, self._cfg)
                return
            except pika.exceptions.ChannelClosedByBroker as error:
                self.cerrar()
                if error.reply_code == 406:
                    raise PublicacionError(
                        "la cola ya existe con otros parámetros (PRECONDITION_FAILED): "
                        "revisar la topología compartida con el worker"
                    ) from None
                raise PublicacionError(
                    f"RabbitMQ rechazó la declaración ({error.reply_code})"
                ) from None
            except pika.exceptions.AMQPError as error:
                self.cerrar()
                if intento == intentos - 1:
                    raise PublicacionError(
                        f"no se pudo conectar a RabbitMQ ({type(error).__name__})"
                    ) from None
                evento(log, "rabbitmq_reconexion", logging.WARNING, intento=intento + 1)
                self._dormir(self._espera(intento, self._cfg.publish_retry_backoff_s))

    def cerrar(self) -> None:
        if self._inyectado:
            return
        if self._conexion is not None and self._conexion.is_open:
            try:
                self._conexion.close()
            except pika.exceptions.AMQPError:
                pass
        self._conexion = None
        self._canal = None

    def publicar(self, mensaje: MensajeUsuario) -> None:
        """Publica con confirmación; reintenta (con reconexión si hace falta) de forma acotada."""
        intentos = self._cfg.publish_max_retries + 1
        for intento in range(intentos):
            try:
                self._publicar_una_vez(mensaje)
                return
            except PublicacionError as error:
                if intento == intentos - 1:
                    raise PublicacionError(f"{error} tras {intentos} intentos") from None
                evento(log, "publicacion_reintentada", logging.WARNING, intento=intento + 1)
                self._dormir(self._espera(intento, self._cfg.publish_retry_backoff_s))
                self._recuperar_conexion()

    def _recuperar_conexion(self) -> None:
        """Si la conexión o el canal se cerraron, los descarta para que el próximo intento abra."""
        if self._inyectado or self._conexion is None:
            return
        if self._conexion.is_closed or self._canal is None or self._canal.is_closed:
            self.cerrar()

    def _publicar_una_vez(self, mensaje: MensajeUsuario) -> None:
        if self._canal is None:
            self.abrir()
        propiedades = pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json",
            content_encoding="utf-8",
            message_id=str(mensaje.message_id),
        )
        try:
            self._canal.basic_publish(
                exchange="",
                routing_key=self._cfg.users_queue,
                body=mensaje.model_dump_json().encode("utf-8"),
                properties=propiedades,
                mandatory=True,
            )
        except pika.exceptions.AMQPError as error:
            raise PublicacionError(
                f"el broker no confirmó la publicación ({type(error).__name__})"
            ) from None
