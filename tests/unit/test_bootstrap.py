import logging

from recos_auto.cron import bootstrap as bs
from recos_auto.cron.__main__ import main


def test_crontab_usa_zona_y_horario(config, tmp_path):
    ruta = tmp_path / "crontab"
    bs.generar_crontab(config, ruta)
    lineas = ruta.read_text().splitlines()
    assert lineas[0] == f"CRON_TZ={config.run_timezone}"
    assert lineas[1] == f"{config.run_schedule} python -m recos_auto.cron run"


def test_crontab_no_contiene_secretos(config, tmp_path):
    ruta = tmp_path / "crontab"
    bs.generar_crontab(config, ruta)
    texto = ruta.read_text()
    assert config.api_general_api_key not in texto
    assert config.rabbitmq_url not in texto


def test_bootstrap_loguea_y_no_corre(config, tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        bs.preparar(config, tmp_path / "crontab")
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "bootstrap_ok" in texto
    assert "corrida_omitida_al_arrancar" in texto
    assert any(getattr(r, "campos", {}).get("zona") == config.run_timezone for r in caplog.records)


def test_bootstrap_sin_variables_sale_con_78(monkeypatch, tmp_path):
    for nombre in ("API_GENERAL_BASE_URL", "API_GENERAL_API_KEY", "RABBITMQ_URL"):
        monkeypatch.delenv(nombre, raising=False)
    assert main(["bootstrap", str(tmp_path / "crontab")]) == 78
    assert not (tmp_path / "crontab").exists()
