from __future__ import annotations

import fcntl

import pytest

from recos_auto.cron.bloqueo import Bloqueo, BloqueoOcupado


def test_toma_y_libera_el_bloqueo(tmp_path):
    ruta = tmp_path / "cron.lock"
    with Bloqueo(ruta):
        pass
    with Bloqueo(ruta):  # se puede volver a tomar
        pass


def test_la_segunda_corrida_no_espera_y_falla_de_inmediato(tmp_path):
    ruta = tmp_path / "cron.lock"
    with Bloqueo(ruta), pytest.raises(BloqueoOcupado):
        with Bloqueo(ruta):
            pytest.fail("no debería entrar")


def test_se_libera_aunque_haya_una_excepcion(tmp_path):
    ruta = tmp_path / "cron.lock"
    with pytest.raises(RuntimeError), Bloqueo(ruta):
        raise RuntimeError("falló la corrida")
    with Bloqueo(ruta):
        pass


def test_usa_flock_no_bloqueante(tmp_path):
    ruta = tmp_path / "cron.lock"
    with Bloqueo(ruta):
        with open(ruta, "w") as otro, pytest.raises(BlockingIOError):
            fcntl.flock(otro, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_crea_el_archivo_si_no_existe(tmp_path):
    ruta = tmp_path / "nuevo.lock"
    assert not ruta.exists()
    with Bloqueo(ruta):
        assert ruta.exists()
