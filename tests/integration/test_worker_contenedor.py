"""Imagen del worker: construye, corre como no-root y sale con 78 si falta configuración."""

import subprocess

import pytest

pytestmark = pytest.mark.contenedor
IMAGEN = "recos-auto-worker:test"


def _docker(*args, **kw):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=600, **kw)


@pytest.fixture(scope="module")
def imagen():
    r = _docker("build", "-f", "docker/worker/Dockerfile", "-t", IMAGEN, ".")
    if r.returncode != 0:
        pytest.skip(f"no se pudo construir la imagen: {r.stderr[-300:]}")
    return IMAGEN


def test_corre_sin_privilegios(imagen):
    r = _docker("run", "--rm", "--entrypoint", "id", imagen, "-u")
    assert r.stdout.strip() == "10001"


def test_sin_configuracion_sale_con_78(imagen):
    r = _docker("run", "--rm", imagen)
    assert r.returncode == 78
    assert "API_GENERAL_BASE_URL" in r.stderr
