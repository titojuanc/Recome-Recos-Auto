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
