# Contrato: variables de entorno del worker

Los valores son de ejemplo; los secretos solo por entorno. Si falta alguna obligatoria o una es inválida, el proceso termina con código 78 nombrando las variables (sin valores).

## Obligatorias
| Variable | Descripción |
|---|---|
| `API_GENERAL_BASE_URL` | Incluye `/api/v1` (igual que el cron). |
| `API_GENERAL_API_KEY` | Clave interna (secreto). |
| `RABBITMQ_URL` | `amqp://usuario:clave@host:5672/%2F` (secreto). |

## Opcionales
| Variable | Defecto | Descripción |
|---|---|---|
| `RABBITMQ_USERS_QUEUE` | `recos-auto.usuarios` | Misma que el cron. |
| `RABBITMQ_DELIVERY_LIMIT` | `5` | Igual que el cron (topología compartida). |
| `RABBITMQ_USERS_MESSAGE_TTL_MS` | `7200000` | Igual que el cron. |
| `RABBITMQ_DEAD_LETTER_TTL_MS` | `604800000` | Igual que el cron. |
| `RABBITMQ_QUEUE_NOTIFICACIONES` | `notificaciones` | Cola de salida (no se declara). |
| `WORKER_CONCURRENCY` | `4` | Hilos, mínimo 1. |
| `API_GENERAL_TIMEOUT_S` | `10` | Timeout por llamada. |
| `PUBLISH_CONFIRM_TIMEOUT_S` | `10` | Espera del confirm del broker. |
| `BREAKER_FAILURES` | `5` | Fallos transitorios seguidos para abrir el corte. |
| `BREAKER_BACKOFF_S` | `5` | Espera inicial del corte (se duplica). |
| `BREAKER_BACKOFF_MAX_S` | `60` | Tope de la espera. |
| `BREAKER_MAX_HOLD_S` | `600` | Máximo de retención de un mensaje sin confirmar. |
| `NOTIF_TITULO_TEMPLATE` | `Tu recomendación de hoy: {titulo}` | Variables: `titulo`, `modulo`. |
| `NOTIF_CUERPO_TEMPLATE` | `Hoy te recomendamos {que_es}: {titulo}. Mirala acá: {url}` | Variables: `titulo`, `modulo`, `que_es`, `url`. |
| `NOTIF_URL_TEMPLATE` | `https://recome.example/{modulo}/{item_id}` | Provisional; la página no existe aún. |
| `SHUTDOWN_TIMEOUT_S` | `25` | Plazo de apagado. |
| `SUMMARY_INTERVAL_S` | `60` | Período del resumen de contadores. |
| `LOG_LEVEL` | `INFO` | |
