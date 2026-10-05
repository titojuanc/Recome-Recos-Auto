"""Publicación de notificaciones en la cola de salida, con confirmación del broker (FR-006)."""

from __future__ import annotations

import pika
from pika.exceptions import NackError, UnroutableError

from recos_auto.worker.notificacion import Notificacion


class ErrorPublicacion(Exception):
    """El broker no confirmó o no pudo encaminar el mensaje: transitorio (se reintenta)."""


class PublicadorNotificaciones:
    """Usa un canal con `confirm_delivery()` ya activado. No declara la cola de salida."""

    def __init__(self, canal, cola: str):
        self._canal = canal
        self._cola = cola

    def publicar(self, notificacion: Notificacion) -> None:
        cuerpo = notificacion.model_dump_json().encode("utf-8")
        try:
            self._canal.basic_publish(
                exchange="",
                routing_key=self._cola,
                body=cuerpo,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json",
                    message_id=str(notificacion.id_mensaje),
                ),
                mandatory=True,
            )
        except UnroutableError as exc:
            raise ErrorPublicacion("cola de salida inexistente o no encaminable") from exc
        except NackError as exc:
            raise ErrorPublicacion("el broker rechazó la notificación") from exc
