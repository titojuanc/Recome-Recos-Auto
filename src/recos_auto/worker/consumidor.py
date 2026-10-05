"""Hilo consumidor: una conexión y un canal propios (pika no es thread-safe), prefetch=1.

Reglas de reconocimiento (research D6):
- notificado / sin recomendación -> ack (la notificación se publicó y confirmó antes).
- inválido -> nack(requeue=False): va a la dead-letter.
- transitorio -> con interruptor abierto se RETIENE el mensaje sin ack (no suma
  `x-delivery-count`, D3) hasta `breaker_max_hold_s`; sin interruptor -> nack(requeue=True).
"""

from __future__ import annotations

import logging
import threading
import time

import pika
from pika.exceptions import AMQPError

from recos_auto.common.logs import evento
from recos_auto.common.topology import declarar_topologia
from recos_auto.worker import procesador
from recos_auto.worker.config import ConfigWorker
from recos_auto.worker.contadores import Contadores
from recos_auto.worker.interruptor import Interruptor
from recos_auto.worker.publicador import PublicadorNotificaciones
from recos_auto.worker.recomendaciones import ClienteRecomendaciones

log = logging.getLogger("recos_auto.worker")


class Consumidor:
    def __init__(
        self,
        cfg: ConfigWorker,
        cliente: ClienteRecomendaciones,
        interruptor: Interruptor,
        contadores: Contadores,
        parar: threading.Event,
        nombre: str = "worker-1",
    ):
        self._cfg = cfg
        self._cliente = cliente
        self._interruptor = interruptor
        self._contadores = contadores
        self._parar = parar
        self.nombre = nombre

    # -- ciclo de vida -------------------------------------------------------------------
    def run(self) -> None:
        """Consume hasta que `parar` se active; reconecta con backoff ante fallos de AMQP."""
        espera = self._cfg.breaker_backoff_s or 1.0
        while not self._parar.is_set():
            try:
                self._sesion()
                return
            except AMQPError as exc:
                evento(
                    log,
                    "conexion_perdida",
                    logging.WARNING,
                    hilo=self.nombre,
                    error=type(exc).__name__,
                )
                self._parar.wait(espera)
                espera = min(espera * 2, max(self._cfg.breaker_backoff_max_s, 1.0))

    def _sesion(self) -> None:
        conexion = pika.BlockingConnection(pika.URLParameters(self._cfg.rabbitmq_url))
        try:
            canal = conexion.channel()
            declarar_topologia(canal, self._cfg)
            canal.confirm_delivery()
            canal.basic_qos(prefetch_count=1)
            publicador = PublicadorNotificaciones(canal, self._cfg.notificaciones_queue)
            while not self._parar.is_set():
                metodo, _props, cuerpo = canal.basic_get(self._cfg.users_queue, auto_ack=False)
                if metodo is None:
                    conexion.process_data_events(time_limit=self._cfg.poll_s)
                    continue
                self._manejar(conexion, canal, metodo.delivery_tag, cuerpo, publicador)
        finally:
            if conexion.is_open:
                try:
                    conexion.close()
                except AMQPError:
                    pass

    # -- un mensaje ----------------------------------------------------------------------
    def _manejar(self, conexion, canal, tag: int, cuerpo: bytes, publicador) -> None:
        self._contadores.incrementar("recibidos")
        retenido_desde: float | None = None
        while True:
            espera = self._interruptor.espera()
            if espera > 0:
                retenido_desde = retenido_desde or time.monotonic()
                vencido = time.monotonic() - retenido_desde >= self._cfg.breaker_max_hold_s
                if self._parar.is_set() or vencido:
                    self._devolver(canal, tag)
                    return
                # process_data_events mantiene vivos los heartbeats mientras se retiene.
                conexion.process_data_events(time_limit=min(espera, self._cfg.poll_s))
                continue

            resultado = procesador.procesar(
                cuerpo, self._cfg, self._cliente.obtener, publicador.publicar
            )
            if resultado.tipo in (procesador.NOTIFICADO, procesador.SIN_RECOMENDACION):
                self._interruptor.exito()
                canal.basic_ack(tag)
                clave = (
                    "notificados"
                    if resultado.tipo == procesador.NOTIFICADO
                    else "sin_recomendacion"
                )
                self._contadores.incrementar(clave)
                return
            if resultado.tipo == procesador.INVALIDO:
                canal.basic_nack(tag, requeue=False)
                self._contadores.incrementar("invalidos")
                evento(log, "mensaje_invalido", logging.WARNING, motivo=resultado.motivo)
                return

            # transitorio
            evento(log, "fallo_transitorio", logging.WARNING, motivo=resultado.motivo)
            if self._interruptor.fallo():
                self._contadores.incrementar("pausas_del_corte")
                retenido_desde = retenido_desde or time.monotonic()
                continue  # se retiene (sin ack) y se reintenta cuando el interruptor lo permita
            self._devolver(canal, tag)
            conexion.process_data_events(time_limit=self._cfg.poll_s)
            return

    def _devolver(self, canal, tag: int) -> None:
        canal.basic_nack(tag, requeue=True)
        self._contadores.incrementar("reintentados")
