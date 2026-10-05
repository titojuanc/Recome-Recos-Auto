# Recome-Recos-Auto

Cron diario (12:00, UTC-3) que pide a api-general los usuarios con contacto y publica un
mensaje por usuario en la cola RabbitMQ `recos-auto.usuarios`. No envía nada a los usuarios:
un worker aparte (feature 002) consume la cola.

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
docker compose -f docker-compose.test.yml up -d --wait   # RabbitMQ para tests
.venv/bin/python -m pytest -q                            # suite (excluye `lento`)
.venv/bin/python -m pytest -q -m lento                   # rendimiento (10 000 usuarios)
docker compose -f docker-compose.test.yml down
```

## Ejecución local completa

```bash
docker compose up --build
# corrida manual:
docker compose exec cron python -m recos_auto.cron run [--date YYYY-MM-DD]
```

## Variables de entorno

Ver `.env.example` y `specs/001-cron-carga-usuarios/contracts/entorno.md`.
Obligatorias: `API_GENERAL_BASE_URL` (incluye `/api/v1`), `API_GENERAL_API_KEY`, `RABBITMQ_URL`.

## Códigos de salida

| Código | Significado |
|--------|-------------|
| 0 | éxito |
| 1 | error o interrumpida |
| 2 | parcial |
| 75 | otra corrida en curso (lock) |
| 78 | configuración inválida |

Las alertas son solo logs y código de salida. Los logs no contienen PII ni credenciales.

## Worker (feature 002)

Consume `recos-auto.usuarios`, pide la recomendación del día a api-general
(`GET /internal/v1/notification-recommendations/{recommendation_id}?module=...`) y publica una
notificación por mail en la cola `notificaciones` (que declara Recome-Notificaciones, no el worker).

```bash
python -m recos_auto.worker          # o: docker compose up --build worker
```

- `WORKER_CONCURRENCY` (4): hilos, cada uno con su conexión y `prefetch=1`.
- Circuito de corte: `BREAKER_FAILURES` (5, `0` lo desactiva), `BREAKER_BACKOFF_S`,
  `BREAKER_BACKOFF_MAX_S`, `BREAKER_MAX_HOLD_S` (1500, debe ser < 1800).
- Destinos: notificado o sin recomendación (404/412) → ack; inválido (400, mensaje malformado) →
  dead-letter; fallo transitorio → se retiene/reintenta (máx. 5 entregas).
- SIGTERM: termina el mensaje en curso (`SHUTDOWN_TIMEOUT_S`, 25 s). Cada `SUMMARY_INTERVAL_S`
  emite un resumen con los mensajes pendientes.
- Salida: 0 ok, 75 apagado forzado, 78 configuración inválida.

Variables: `.env.example` y `specs/002-worker-recomendaciones/contracts/entorno.md`.
Tests de contenedor: `pytest -m contenedor`.
