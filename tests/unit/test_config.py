from __future__ import annotations

from datetime import date

import pytest

from recos_auto.common.config import Config, ConfigError


def test_defaults(env_base):
    cfg = Config.from_env(env_base)
    assert cfg.run_schedule == "0 12 * * *"
    assert cfg.run_timezone == "America/Argentina/Buenos_Aires"
    assert cfg.module_reference_date == date(2026, 10, 5)
    assert cfg.page_size == 200
    assert cfg.users_queue == "recos-auto.usuarios"
    assert cfg.dead_letter_queue == "recos-auto.usuarios.dead-letter"
    assert cfg.dead_letter_exchange == "recos-auto.usuarios.dlx"
    assert cfg.delivery_limit == 5
    # TTL: 2 h en la cola de usuarios y 7 días en la dead-letter (FR-014)
    assert cfg.users_message_ttl_ms == 7_200_000
    assert cfg.dead_letter_ttl_ms == 604_800_000


def test_lista_todas_las_obligatorias_faltantes():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({})
    assert set(exc.value.faltantes) == {
        "API_GENERAL_BASE_URL",
        "API_GENERAL_API_KEY",
        "RABBITMQ_URL",
    }
    for nombre in exc.value.faltantes:
        assert nombre in str(exc.value)


def test_el_error_no_imprime_valores(env_base):
    env = dict(env_base, API_GENERAL_PAGE_SIZE="999999")
    with pytest.raises(ConfigError) as exc:
        Config.from_env(env)
    assert "API_GENERAL_PAGE_SIZE" in str(exc.value)
    assert "999999" not in str(exc.value)


@pytest.mark.parametrize("valor", ["0", "501", "abc", ""])
def test_page_size_fuera_de_rango(env_base, valor):
    with pytest.raises(ConfigError) as exc:
        Config.from_env(dict(env_base, API_GENERAL_PAGE_SIZE=valor))
    assert "API_GENERAL_PAGE_SIZE" in exc.value.invalidas


def test_page_size_limites_validos(env_base):
    assert Config.from_env(dict(env_base, API_GENERAL_PAGE_SIZE="1")).page_size == 1
    assert Config.from_env(dict(env_base, API_GENERAL_PAGE_SIZE="500")).page_size == 500


@pytest.mark.parametrize(
    ("variable", "valor"),
    [
        ("RUN_TIMEZONE", "Mars/Olympus"),
        ("RUN_SCHEDULE", "esto no es cron"),
        ("RUN_SCHEDULE", "0 12 * *"),
        ("MODULE_REFERENCE_DATE", "05/10/2026"),
        ("API_GENERAL_BASE_URL", "no-es-url"),
        ("RABBITMQ_URL", "http://no-es-amqp"),
        ("RABBITMQ_DELIVERY_LIMIT", "0"),
        ("RABBITMQ_USERS_MESSAGE_TTL_MS", "-5"),
    ],
)
def test_valores_invalidos_nombran_la_variable(env_base, variable, valor):
    with pytest.raises(ConfigError) as exc:
        Config.from_env(dict(env_base, **{variable: valor}))
    assert variable in exc.value.invalidas


def test_agrega_todos_los_errores_juntos(env_base):
    env = {"API_GENERAL_BASE_URL": "x"}
    env["RUN_TIMEZONE"] = "Mars/Olympus"
    with pytest.raises(ConfigError) as exc:
        Config.from_env(env)
    assert "API_GENERAL_API_KEY" in exc.value.faltantes
    assert "RABBITMQ_URL" in exc.value.faltantes
    assert "RUN_TIMEZONE" in exc.value.invalidas
    assert "API_GENERAL_BASE_URL" in exc.value.invalidas


def test_repr_sin_secretos(env_base):
    cfg = Config.from_env(env_base)
    texto = repr(cfg) + str(cfg)
    assert "secreto" not in texto
    assert "local.clave-de-prueba" not in texto
    assert "usuario:secreto" not in texto


def test_ttl_configurable(env_base):
    cfg = Config.from_env(dict(env_base, RABBITMQ_USERS_MESSAGE_TTL_MS="2000"))
    assert cfg.users_message_ttl_ms == 2000
