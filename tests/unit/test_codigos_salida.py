"""Códigos de salida de `python -m recos_auto.cron run` (contracts/cli.md)."""

from __future__ import annotations

import json
import signal

import pytest

from recos_auto.cron import __main__ as cli
from recos_auto.cron.api_general import ApiGeneralError, Pagina
from recos_auto.cron.bloqueo import Bloqueo
from recos_auto.cron.publicador import PublicacionError


def _usuario(i: int) -> dict:
    return {
        "recommendation_id": f"00000000-0000-0000-0000-{i:012d}",
        "user_id": i,
        "nombre": f"Usuario {i}",
        "email": f"u{i}@example.com",
    }


class ApiFalsa:
    comportamiento = "ok"

    def __init__(self, cfg, **_):
        pass

    def cerrar(self):
        pass

    def paginas(self):
        if self.comportamiento == "error":
            raise ApiGeneralError("api-general respondió 503", estado=503, transitorio=True)
        yield Pagina(1, [_usuario(1), _usuario(2)])
        if self.comportamiento == "sigterm":
            signal.raise_signal(signal.SIGTERM)
        yield Pagina(2, [_usuario(3), _usuario(4)])


class PublicadorFalso:
    fallan: set[int] = set()
    instancias: list[PublicadorFalso] = []

    def __init__(self, cfg, **_):
        self.publicados: list[int] = []
        PublicadorFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def publicar(self, mensaje):
        if mensaje.user_id in self.fallan:
            raise PublicacionError("el broker no confirmó la publicación (NackError)")
        self.publicados.append(mensaje.user_id)


@pytest.fixture
def entorno(monkeypatch, env_base, tmp_path):
    for nombre, valor in env_base.items():
        monkeypatch.setenv(nombre, valor)
    monkeypatch.setattr(cli, "ApiGeneral", ApiFalsa)
    monkeypatch.setattr(cli, "Publicador", PublicadorFalso)
    ApiFalsa.comportamiento = "ok"
    PublicadorFalso.fallan = set()
    PublicadorFalso.instancias = []
    return tmp_path / "cron.lock"


def _correr(ruta, *argumentos) -> int:
    return cli.main(["run", *argumentos], ruta_bloqueo=ruta)


def test_exito_es_0(entorno):
    assert _correr(entorno) == 0
    assert PublicadorFalso.instancias[0].publicados == [1, 2, 3, 4]


def test_parcial_es_2(entorno):
    PublicadorFalso.fallan = {2}
    assert _correr(entorno) == 2


def test_error_fatal_es_1(entorno):
    ApiFalsa.comportamiento = "error"
    assert _correr(entorno) == 1


def test_interrumpida_por_sigterm_es_1_y_no_sigue(entorno):
    ApiFalsa.comportamiento = "sigterm"
    anterior = signal.getsignal(signal.SIGTERM)
    assert _correr(entorno) == 1
    assert PublicadorFalso.instancias[0].publicados == [1, 2]  # nada de la página 2
    assert signal.getsignal(signal.SIGTERM) is anterior  # restaura el handler


def test_bloqueo_ocupado_es_75_y_se_registra(entorno, capsys):
    with Bloqueo(entorno):
        assert _correr(entorno) == 75
    assert "corrida_omitida_por_bloqueo" in capsys.readouterr().out
    assert PublicadorFalso.instancias == []


def test_falta_configuracion_es_78_y_lista_las_variables(entorno, monkeypatch, capsys):
    monkeypatch.delenv("API_GENERAL_API_KEY")
    monkeypatch.delenv("RABBITMQ_URL")
    assert _correr(entorno) == 78
    err = capsys.readouterr().err
    assert "API_GENERAL_API_KEY" in err
    assert "RABBITMQ_URL" in err


def test_fecha_mal_formada_es_78(entorno, capsys):
    assert _correr(entorno, "--date", "05/10/2026") == 78
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_fecha_explicita_define_el_modulo_en_el_resumen(entorno, capsys):
    assert _correr(entorno, "--date", "2026-10-06") == 0
    lineas = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    final = next(x for x in lineas if x["evento"] == "corrida_finalizada")
    assert final["fecha"] == "2026-10-06"
    assert final["modulo"] == "juegos"


def test_el_resumen_final_no_tiene_datos_personales(entorno, capsys):
    _correr(entorno)
    salida = capsys.readouterr().out
    assert "u1@example.com" not in salida
    assert "Usuario 1" not in salida
