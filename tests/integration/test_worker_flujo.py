"""Worker contra RabbitMQ real y api-general simulada (US1, US2)."""

import threading
import time
import uuid

import httpx
import pytest

from recos_auto.worker.consumidor import Consumidor
from recos_auto.worker.contadores import Contadores
from recos_auto.worker.interruptor import Interruptor
from recos_auto.worker.recomendaciones import ClienteRecomendaciones

pytestmark = pytest.mark.integration


class ApiRecos:
    """Responde por recommendation_id; `modo` permite simular caídas."""

    def __init__(self):
        self.modo = "ok"
        self.llamadas: list[str] = []
        self.por_id: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        rid = request.url.path.rsplit("/", 1)[-1]
        self.llamadas.append(rid)
        if self.modo == "caida":
            return httpx.Response(503)
        if self.modo == "404":
            return httpx.Response(404)
        if self.modo == "400":
            return httpx.Response(400)
        return httpx.Response(
            200,
            json={
                "recommendation_id": rid,
                "item_id": str(uuid.UUID(int=1234)),
                "module": request.url.params["module"],
                "titulo": f"Titulo-{rid}",
                "position": 1,
            },
        )


def _esperar(condicion, timeout=15.0):
    fin = time.monotonic() + timeout
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.05)
    return False


class Arnes:
    def __init__(self, cfg, api: ApiRecos, hilos: int = 1):
        self.parar = threading.Event()
        self.contadores = Contadores()
        self.interruptor = Interruptor(
            cfg.breaker_failures, cfg.breaker_backoff_s, cfg.breaker_backoff_max_s
        )
        cliente = ClienteRecomendaciones(cfg, transport=httpx.MockTransport(api))
        self.hilos = [
            threading.Thread(
                target=Consumidor(
                    cfg, cliente, self.interruptor, self.contadores, self.parar, f"t{i}"
                ).run,
                daemon=True,
            )
            for i in range(hilos)
        ]

    def __enter__(self):
        for h in self.hilos:
            h.start()
        return self

    def __exit__(self, *_):
        self.parar.set()
        for h in self.hilos:
            h.join(timeout=10)


def test_camino_feliz_un_mensaje_un_mail_con_su_recomendacion(
    config_worker, publicar_usuarios, leer_cola, profundidad
):
    mensajes = publicar_usuarios(5)
    api = ApiRecos()
    with Arnes(config_worker, api) as arnes:
        assert _esperar(lambda: arnes.contadores.snapshot()["notificados"] == 5)
    salidas = leer_cola(config_worker.notificaciones_queue)
    assert len(salidas) == 5
    assert profundidad(config_worker.users_queue) == 0
    por_dest = {s["destinatario"]: s for s in salidas}
    for m in mensajes:
        s = por_dest[m["user_id"]]
        assert s["mail"] == m["email"]
        assert s["canal"] == "mail"
        assert f"Titulo-{m['recommendation_id']}" in s["contenido"]["titulo"]
    assert len({s["id_mensaje"] for s in salidas}) == 5


def test_sin_recomendacion_se_descarta_sin_notificar(
    config_worker, publicar_usuarios, leer_cola, profundidad
):
    publicar_usuarios(3)
    api = ApiRecos()
    api.modo = "404"
    with Arnes(config_worker, api) as arnes:
        assert _esperar(lambda: arnes.contadores.snapshot()["sin_recomendacion"] == 3)
    assert leer_cola(config_worker.notificaciones_queue) == []
    assert profundidad(config_worker.users_queue) == 0
    assert profundidad(config_worker.dead_letter_queue) == 0


def test_mensaje_invalido_va_a_la_dead_letter(
    config_worker, publicar_usuarios, conexion_rabbit, profundidad
):
    publicar_usuarios(1)
    canal = conexion_rabbit.channel()
    canal.basic_publish("", config_worker.users_queue, b"basura")
    canal.close()
    with Arnes(config_worker, ApiRecos()) as arnes:
        assert _esperar(lambda: arnes.contadores.snapshot()["invalidos"] == 1)
        assert _esperar(lambda: profundidad(config_worker.dead_letter_queue) == 1)
    assert arnes.contadores.snapshot()["notificados"] == 1


def test_error_400_de_la_api_va_a_la_dead_letter(config_worker, publicar_usuarios, profundidad):
    publicar_usuarios(1)
    api = ApiRecos()
    api.modo = "400"
    with Arnes(config_worker, api):
        assert _esperar(lambda: profundidad(config_worker.dead_letter_queue) == 1)


def test_caida_de_la_api_retiene_y_no_pierde_ni_duplica(
    config_worker, publicar_usuarios, leer_cola, profundidad
):
    publicar_usuarios(3)
    api = ApiRecos()
    api.modo = "caida"
    with Arnes(config_worker, api) as arnes:
        assert _esperar(lambda: arnes.contadores.snapshot()["pausas_del_corte"] >= 1)
        assert profundidad(config_worker.dead_letter_queue) == 0
        api.modo = "ok"
        assert _esperar(lambda: arnes.contadores.snapshot()["notificados"] == 3)
    salidas = leer_cola(config_worker.notificaciones_queue)
    assert len(salidas) == 3
    assert len({s["id_mensaje"] for s in salidas}) == 3
    assert profundidad(config_worker.dead_letter_queue) == 0


def test_interruptor_limita_las_llamadas_durante_la_caida(config_worker, publicar_usuarios):
    publicar_usuarios(20)
    api = ApiRecos()
    api.modo = "caida"
    with Arnes(config_worker, api) as arnes:
        assert _esperar(lambda: arnes.contadores.snapshot()["pausas_del_corte"] >= 1)
        time.sleep(1.5)
    # umbral 5 + sondas con backoff 0.2-0.5 s: muy por debajo de 20 mensajes x reintentos
    assert len(api.llamadas) < 20


def test_concurrencia_sin_cruces(config_worker, publicar_usuarios, leer_cola):
    publicar_usuarios(60)
    with Arnes(config_worker, ApiRecos(), hilos=4) as arnes:
        assert _esperar(lambda: arnes.contadores.snapshot()["notificados"] == 60)
    salidas = leer_cola(config_worker.notificaciones_queue)
    assert len(salidas) == 60
    assert len({s["id_mensaje"] for s in salidas}) == 60
    for s in salidas:
        rid = str(uuid.UUID(int=s["destinatario"]))
        assert f"Titulo-{rid}" in s["contenido"]["titulo"]
        assert s["mail"] == f"u{s['destinatario']}@example.com"
