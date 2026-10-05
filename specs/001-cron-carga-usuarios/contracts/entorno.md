# Contrato: variables de entorno del cron

Toda la configuración viene del entorno (Dokploy, docker compose o `.env` local). Los valores de ejemplo no son secretos.

## Obligatorias (sin valor por defecto)

| Variable | Ejemplo | Descripción |
|---|---|---|
| `API_GENERAL_BASE_URL` | `https://api.recome.example/api/v1` | URL base de api-general, con el `context-path`. |
| `API_GENERAL_API_KEY` | `prod.xxxxxxxx` | Clave de servicio con formato `<entorno>.<secreto>`. **Secreto.** |
| `RABBITMQ_URL` | `amqp://usuario:clave@rabbit:5672/` | Conexión al RabbitMQ existente. **Secreto** (lleva credenciales). |

## Opcionales (con valor por defecto)

| Variable | Defecto | Descripción |
|---|---|---|
| `RUN_SCHEDULE` | `0 12 * * *` | Expresión cron de 5 campos. |
| `RUN_TIMEZONE` | `America/Argentina/Buenos_Aires` | Zona IANA para el horario, la fecha de corrida y el módulo del día. |
| `MODULE_REFERENCE_DATE` | `2026-10-05` | Día en que toca `peliculas`; desde ahí se alterna día por medio. |
| `API_GENERAL_PAGE_SIZE` | `200` | Entre 1 y 500. |
| `API_GENERAL_TIMEOUT_S` | `10` | Timeout por pedido. |
| `API_GENERAL_MAX_RETRIES` | `3` | Reintentos por página ante errores transitorios. |
| `API_GENERAL_RETRY_BACKOFF_S` | `1` | Espera inicial; se duplica en cada reintento. |
| `API_GENERAL_MAX_PAGES` | `1000` | Tope de seguridad contra paginación infinita. |
| `RABBITMQ_USERS_QUEUE` | `recos-auto.usuarios` | Cola de usuarios (routing key igual al nombre, exchange por defecto). |
| `RABBITMQ_DELIVERY_LIMIT` | `5` | `x-delivery-limit` de la cola; debe coincidir con el worker. |
| `RABBITMQ_USERS_MESSAGE_TTL_MS` | `7200000` | TTL (2 h) de los mensajes de la cola de usuarios; los vencidos pasan a la dead-letter. Debe coincidir con el worker. |
| `RABBITMQ_DEAD_LETTER_TTL_MS` | `604800000` | TTL (7 días) de la dead-letter. Debe coincidir con el worker. |
| `PUBLISH_MAX_RETRIES` | `3` | Reintentos por mensaje no confirmado. |
| `PUBLISH_RETRY_BACKOFF_S` | `0.5` | Espera inicial; se duplica en cada reintento. |
| `MAX_CONSECUTIVE_PUBLISH_FAILURES` | `5` | Fallos seguidos que abortan la corrida. |
| `LOG_LEVEL` | `INFO` | Nivel de logs. |

## Reglas

- Si falta alguna obligatoria, el arranque termina con código 78 y lista **todas** las faltantes, sin imprimir valores.
- Valores fuera de rango o mal formados (zona inexistente, cron inválido, fecha mal escrita) también terminan con 78 y nombran la variable.
- `API_GENERAL_API_KEY` y `RABBITMQ_URL` nunca se escriben en logs ni en el crontab.
