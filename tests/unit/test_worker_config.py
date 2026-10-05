"""ConfigWorker: variables obligatorias, defaults y validaciones (contracts/entorno.md)."""

import pytest

from recos_auto.common.config import Config, ConfigError
from recos_auto.worker.config import ConfigWorker

BASE = {
    "API_GENERAL_BASE_URL": "http://api.test/api/v1",
    "API_GENERAL_API_KEY": "local.clave-secreta",
    "RABBITMQ_URL": "amqp://usuario:secreto@rabbit.test:5672/",
}


def test_defaults_del_contrato():
    cfg = ConfigWorker.from_env(BASE)
    assert cfg.users_queue == "recos-auto.usuarios"
    assert cfg.notificaciones_queue == "notificaciones"
    assert cfg.concurrency == 4
    assert cfg.delivery_limit == 5
    assert cfg.users_message_ttl_ms == 7_200_000
    assert cfg.dead_letter_ttl_ms == 604_800_000
    assert cfg.breaker_failures == 5
    assert cfg.breaker_backoff_s == 5
    assert cfg.breaker_backoff_max_s == 60
    assert cfg.breaker_max_hold_s == 1500
    assert cfg.api_timeout_s == 10
    assert cfg.shutdown_timeout_s == 25
    assert cfg.summary_interval_s == 60
    assert cfg.log_level == "INFO"


def test_faltantes_se_listan_todas_sin_valores():
    with pytest.raises(ConfigError) as error:
        ConfigWorker.from_env({})
    mensaje = str(error.value)
    for nombre in BASE:
        assert nombre in mensaje


@pytest.mark.parametrize(
    ("variable", "valor"),
    [
        ("WORKER_CONCURRENCY", "0"),
        ("WORKER_CONCURRENCY", "x"),
        ("BREAKER_FAILURES", "-1"),
        ("BREAKER_MAX_HOLD_S", "1800"),
        ("BREAKER_MAX_HOLD_S", "5000"),
        ("API_GENERAL_TIMEOUT_S", "0"),
        ("NOTIF_TITULO_TEMPLATE", "Hola {desconocida}"),
        ("NOTIF_CUERPO_TEMPLATE", "{titulo} {nope}"),
        ("NOTIF_URL_TEMPLATE", "https://x/{titulo}"),
        ("NOTIF_TITULO_TEMPLATE", "llave sin cerrar {titulo"),
        ("RABBITMQ_URL", "http://no-es-amqp"),
        ("LOG_LEVEL", "VERBOSE"),
    ],
)
def test_invalidas_se_nombran(variable, valor):
    with pytest.raises(ConfigError) as error:
        ConfigWorker.from_env(dict(BASE, **{variable: valor}))
    assert variable in error.value.invalidas
    assert valor not in str(error.value) or valor in {"0", "x", "-1"}


def test_breaker_failures_cero_deshabilita():
    cfg = ConfigWorker.from_env(dict(BASE, BREAKER_FAILURES="0"))
    assert cfg.breaker_failures == 0


def test_repr_no_contiene_secretos():
    texto = repr(ConfigWorker.from_env(BASE))
    assert "local.clave-secreta" not in texto
    assert "secreto" not in texto


def test_topologia_identica_a_la_del_cron():
    """FR-012: las colas se declaran con los mismos argumentos que el cron."""
    from recos_auto.common.topology import argumentos_cola_usuarios, argumentos_dead_letter

    worker = ConfigWorker.from_env(BASE)
    cron = Config.from_env(BASE)
    assert argumentos_cola_usuarios(worker) == argumentos_cola_usuarios(cron)
    assert argumentos_dead_letter(worker) == argumentos_dead_letter(cron)
    assert worker.dead_letter_queue == cron.dead_letter_queue
    assert worker.dead_letter_exchange == cron.dead_letter_exchange
