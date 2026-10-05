import threading

import pytest

from recos_auto.worker.contadores import NOMBRES, Contadores


def test_incrementos_concurrentes_no_pierden_cuentas():
    c = Contadores()

    def trabajo():
        for _ in range(2000):
            c.incrementar("recibidos")
            c.incrementar("notificados")

    hilos = [threading.Thread(target=trabajo) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert c.snapshot()["recibidos"] == 16000
    assert c.snapshot()["notificados"] == 16000


def test_resumen_tiene_todos_los_campos_y_duracion():
    reloj = iter([100.0, 107.5])
    c = Contadores(reloj=lambda: next(reloj))
    resumen = c.resumen()
    for nombre in NOMBRES:
        assert resumen[nombre] == 0
    assert resumen["duracion_s"] == 7.5


def test_contador_desconocido_falla():
    with pytest.raises(KeyError):
        Contadores().incrementar("email")


def test_el_resumen_no_trae_datos_personales():
    claves = " ".join(Contadores().resumen())
    for prohibido in ("email", "nombre", "mail"):
        assert prohibido not in claves
