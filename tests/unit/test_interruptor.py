"""Interruptor: estados, backoff y deshabilitado (T027)."""

from recos_auto.worker.interruptor import ABIERTO, CERRADO, SEMIABIERTO, Interruptor


class Reloj:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _nuevo(fallos=3, reloj=None):
    return Interruptor(fallos, 1.0, 4.0, reloj or Reloj())


def test_cerrado_no_espera():
    assert _nuevo().espera() == 0.0


def test_abre_tras_n_fallos_seguidos():
    i = _nuevo(3)
    assert not i.fallo()
    assert not i.fallo()
    assert i.fallo()
    assert i.estado == ABIERTO
    assert i.espera() == 1.0


def test_un_exito_reinicia_la_cuenta():
    i = _nuevo(3)
    i.fallo()
    i.fallo()
    i.exito()
    assert not i.fallo()
    assert i.estado == CERRADO


def test_semiabierto_deja_pasar_una_sola_sonda():
    reloj = Reloj()
    i = _nuevo(1, reloj)
    i.fallo()
    reloj.t += 1.0
    assert i.espera() == 0.0  # sonda
    assert i.estado == SEMIABIERTO
    assert i.espera() > 0  # el resto espera


def test_fallo_de_la_sonda_reabre_con_backoff_exponencial_acotado():
    reloj = Reloj()
    i = _nuevo(1, reloj)
    esperas = []
    for _ in range(5):
        assert i.fallo()
        esperas.append(i.espera())
        reloj.t += esperas[-1]
        assert i.espera() == 0.0
    assert esperas == [1.0, 2.0, 4.0, 4.0, 4.0]


def test_exito_de_la_sonda_cierra():
    reloj = Reloj()
    i = _nuevo(1, reloj)
    i.fallo()
    reloj.t += 1
    i.espera()
    i.exito()
    assert i.estado == CERRADO
    assert i.espera() == 0.0


def test_cero_lo_deshabilita():
    i = _nuevo(0)
    assert not i.habilitado
    for _ in range(50):
        assert not i.fallo()
    assert i.espera() == 0.0
