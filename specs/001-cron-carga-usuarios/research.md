# Research: Cron de carga diaria de usuarios

Cada decisión indica qué se eligió, por qué y qué se descartó.

## D1. Scheduler: Supercronic dentro del contenedor

- **Decisión**: Supercronic v0.2.49 como proceso hijo del entrypoint (que es PID 1), con un crontab generado al arrancar:
  `CRON_TZ=<zona>` + `<RUN_SCHEDULE> python -m recos_auto.cron run`.
- **Por qué**: está hecho para contenedores. Hereda las variables de entorno (el cron clásico las purga), escribe en stdout/stderr, hace apagado ordenado con SIGTERM/SIGINT, registra el código de salida de cada corrida, no lanza una segunda instancia del mismo trabajo mientras la anterior corre, soporta `CRON_TZ` y no ejecuta corridas perdidas al arrancar (coincide con FR-025: una corrida perdida se recupera a mano).
- **Descartado**:
  - *Cron de Debian/Alpine*: purga el entorno, requiere archivos de entorno y redirecciones, y no maneja bien las señales.
  - *APScheduler / bucle propio en Python*: viable y evita un binario, pero hay que escribir y probar agenda, zona horaria y señales. Se prefiere una herramienta probada.
  - *Programador del propio Dokploy*: no se asume porque Dokploy todavía no existe en el entorno; el contenedor debe funcionar igual con docker compose.
- **Binario fijado**: `supercronic-linux-amd64` y `supercronic-linux-arm64` v0.2.49 con SHA1 publicados en la release (amd64 `e63c11a9726b775a6a11801e81af4f3fb926aa68`, arm64 `0b6c5bb743e0b0dafed1132198c81807927ac413`). El Dockerfile elige según `TARGETARCH` y verifica el checksum.
- **Trade-off conocido**: Supercronic envuelve la salida del trabajo en su propio formato (`level=info msg="..." channel=stdout`), de modo que cada línea JSON queda como texto dentro de ese envoltorio. Sigue siendo legible y filtrable en los logs de Dokploy. Se usa `-split-logs` para separar niveles.
- **Verificado**: Supercronic NO reenvía SIGTERM al trabajo en curso; el entrypoint lo resuelve con un `trap` (ver "Verificaciones empíricas" al final).

## D2. Horario y zona horaria configurables

- **Decisión**: variables `RUN_SCHEDULE` (expresión cron de 5 campos, por defecto `0 12 * * *`) y `RUN_TIMEZONE` (por defecto `America/Argentina/Buenos_Aires`). `bootstrap` genera `/tmp/crontab` y ejecuta `supercronic -test` para validarlo antes de arrancar.
- **Por qué**: el crontab no expande variables de entorno, así que se genera al arrancar. La fecha de corrida y el módulo se calculan con `zoneinfo` y la misma zona, no con la del servidor (SC-003).
- **Dato**: Argentina no tiene horario de verano, así que no hay saltos de hora; igualmente se usa el nombre de zona IANA y no un desfase fijo.
- **Imagen**: lleva `tzdata` del sistema (lo necesita Supercronic) y el paquete `tzdata` de pip no hace falta porque la imagen ya lo incluye.

## D3. Una sola corrida a la vez (FR-011)

- **Decisión**: `fcntl.flock` no bloqueante sobre `/tmp/recos-auto-cron.lock`. Si ya está tomado, la corrida registra el motivo y sale con código 75.
- **Por qué**: Supercronic ya evita solapar el trabajo programado, pero una corrida manual (`docker exec`) es otro proceso del mismo contenedor y sí podría pisarse. El archivo de bloqueo en `/tmp` cubre eso sin volumen, y el sistema operativo lo libera si el proceso muere.
- **Límite**: el bloqueo es por contenedor. Por eso se exige **una sola réplica**; si durante un redespliegue conviven dos contenedores a las 12:00, la identidad determinística (D5) y la deduplicación del consumidor evitan el doble envío.

## D4. Cliente de api-general

- **Decisión**: `httpx.Client` con timeout, encabezado `X-Internal-API-Key` y reintentos propios acotados con espera creciente: se reintenta ante errores de red, timeouts y 5xx (también 429); 401, 403, 404 y 400 fallan de inmediato.
- **URL base**: incluye el `context-path` de api-general (`.../api/v1`); el endpoint es `/internal/v1/notification-targets`.
- **Clave**: el endpoint quedó dentro de la familia de rutas de sincronización de api-general, así que la clave debe tener el formato `<entorno>.<secreto>` y coincidir con el entorno configurado allá. Se documenta en el quickstart.
- **Paginación**: se procesa página por página (no se acumula todo en memoria). Guardas: un `next_page_token` repetido, o superar `API_GENERAL_MAX_PAGES`, aborta con error claro. Una página con 0 usuarios válidos pero con un token **nuevo** es legítima (api-general descarta del resultado a quienes no tienen email, y puede pasar en una página entera), así que se continúa. Esto matiza el caso borde de la spec sobre páginas vacías.
- **Descartado**: `requests` (sin transporte simulable tan directo) y acumular todos los usuarios antes de publicar (más memoria y pierde progreso parcial).

## D5. Identidad determinística del mensaje (FR-012)

- **Decisión**: `message_id` = UUIDv5 con un espacio de nombres fijo sobre `"{user_id}|{fecha}|{modulo}"`, enviado como propiedad AMQP `message_id` y como campo del cuerpo. No depende del identificador de corrida.
- **Por qué**: reejecutar el mismo día produce el mismo `message_id` para cada usuario; el worker (feature 002) deriva de ahí el `id_mensaje` entero que exige Notificaciones.
- **Pendiente para la feature 002**: definir cómo se convierte a entero positivo de hasta 63 bits; aquí solo se garantiza que la entrada es estable.

## D6. Publicación en RabbitMQ

- **Decisión**: `pika.BlockingConnection`, `confirm_delivery()`, `mandatory=True`, `delivery_mode=2`, exchange por defecto con routing key igual al nombre de la cola, `content_type=application/json`. Si la publicación falla (`NackError`, `UnroutableError`, desconexión) se reintenta con espera creciente y reconexión; superados los reintentos del mensaje se cuenta como fallido.
- **Corte anticipado**: tras `MAX_CONSECUTIVE_PUBLISH_FAILURES` fallos seguidos (por defecto 5) se aborta la corrida; así una caída de RabbitMQ no genera miles de reintentos inútiles. La conexión se abre al iniciar para fallar rápido si el broker no está (edge case de la spec).
- **Confirmación síncrona**: es la opción más simple y suficiente para decenas de miles de mensajes; confirmar por lotes queda como optimización si se midiera necesaria.

## D7. Topología compartida con el worker (FR-013)

- **Decisión**: `common/topology.py` declara la cola `recos-auto.usuarios` (quorum, durable), `x-dead-letter-exchange` = `recos-auto.usuarios.dlx` (fanout), `x-delivery-limit` = 5, y la cola `recos-auto.usuarios.dead-letter` enlazada a ese DLX. `x-message-ttl` = 2 h (7.200.000 ms) en la cola de usuarios y 7 días (604.800.000 ms) en la dead-letter (FR-014); el worker debe declarar los mismos valores.
- **Por qué**: RabbitMQ rechaza redeclarar una cola con argumentos distintos (`PRECONDITION_FAILED`). Un único módulo evita que cron y worker se desalineen; un test de contrato lo compara contra la convención de Notificaciones (`<cola>.dlx`, `<cola>.dead-letter`, quorum, `x-delivery-limit`).
- **Si falla la declaración**: la corrida aborta con un mensaje que indica que la cola existe con otros parámetros y no la modifica.

## D8. Módulo del día (FR-009)

- **Decisión**: `("peliculas", "juegos")[(fecha - MODULE_REFERENCE_DATE).days % 2]`. El `%` de Python es correcto también para fechas anteriores a la referencia.
- **Por qué**: es puro, sin estado y reproducible; el valor por defecto de la referencia es `2026-10-05` (lunes, `peliculas`).

## D9. Observabilidad sin puertos

- **Decisión**: logs JSON de una línea por evento a stdout, con un evento final `corrida_finalizada` que incluye los contadores y la duración. Los loggers de `httpx` y `pika` se fijan en WARNING para que no escriban URLs ni parámetros de conexión; el repr de la configuración oculta secretos. Los eventos de usuario llevan `user_id` y nunca `nombre` ni `email`.
- **Métricas**: el resumen de corrida es la fuente; no hay `/metrics` porque FR-021 no admite puertos.
- **Alerta de corrida ausente**: queda fuera de esta feature. Con la opción A de FR-025 una caída a las 12:00 solo se nota por logs; cuando exista Dokploy se recomienda una alerta externa sobre la ausencia del evento `corrida_finalizada` en el día. El arranque registra `corrida_omitida_al_arrancar` si ya pasó el horario y no hubo corrida programada.
- **Descartado**: Prometheus pushgateway u otros servicios nuevos (Principio IX).

## D10. Códigos de salida

| Código | Significado |
|---|---|
| 0 | Corrida completa sin fallos |
| 1 | Error fatal (api-general inaccesible tras reintentos, RabbitMQ caído, cola con parámetros distintos, token repetido) |
| 2 | Corrida terminada con usuarios no publicados (fallos individuales) |
| 75 | Ya hay otra corrida en curso (no se ejecutó) |
| 78 | Configuración inválida o incompleta |

Cualquier código distinto de 0 queda registrado por Supercronic como fallo del trabajo y es visible en los logs.

## D11. Cierre ordenado (FR-024)

- **Decisión**: el comando captura SIGTERM/SIGINT, termina de publicar el mensaje en curso, cierra la conexión, registra `corrida_interrumpida` con los contadores y sale con código 1. La señal le llega porque `entrypoint.sh` la reenvía (D1).
- **Por qué**: un reintento manual o la corrida siguiente completan el trabajo sin duplicar, gracias a D5.

## D12. Seguridad de la imagen

- Usuario no root, sin puertos ni volúmenes, sin secretos en la imagen ni en el crontab (el crontab solo contiene zona, horario y el comando).
- Sistema de archivos de solo escritura posible: solo se escribe en `/tmp`.
- `HEALTHCHECK` ligero: el proceso `supercronic` sigue vivo.

---

## Verificaciones empíricas (stack de PruebaVisualModulosNotiyArchivos + pruebas locales)

**D1 (actualizada) — Supercronic NO reenvía SIGTERM al job en curso.** Esperó a que el job terminara
(22 s). Solución verificada: `docker/cron/entrypoint.sh` corre Supercronic como hijo, captura
`SIGTERM` con `trap`, envía `pkill -TERM -f "python -m recos_auto.cron"` y luego `kill -TERM` a
Supercronic. Resultado: cierre en ~1 s, el job recibe la señal y sale limpio (código 0).
El wrapper es PID 1 (aviso "process reaping disabled" aceptable: el job no deja huérfanos).

**D1 — Zona horaria.** `CRON_TZ=America/Argentina/Buenos_Aires` en la crontab funciona con el
sistema en UTC (próxima corrida 12:00 -03:00). Sin `CRON_TZ` corre a las 12:00 UTC. `supercronic -test`
valida la crontab (usar en CI). No ejecuta corridas perdidas al arrancar (coherente con FR-025).
Con `-split-logs` cada línea queda envuelta en `level=info msg=... channel=stdout`; el parser de
logs debe tolerarlo.

**D6/D7 — RabbitMQ 3.13 + pika 1.4.4.**
- Cola quorum + DLX: publicar con `confirm_delivery` funciona.
- Publicar con `mandatory=True` a una cola inexistente lanza `UnroutableError` (se detecta).
- Redeclarar con distintos `x-delivery-limit` falla con `406 PRECONDITION_FAILED`; idéntica es
  idempotente → `topology.py` compartido entre cron y worker es obligatorio.
- `nack(requeue=True)` repetido con `x-delivery-limit=5`: 6 entregas en total y luego va a la
  dead-letter (1 original + 5 reintentos).

**Convención de la cola `notificaciones` (ejemplo del repo de prueba).** La declara el worker de
Notificaciones (quorum + DLX + TTL). Quien produzca hacia ella NO debe declararla (provoca
`PRECONDITION_FAILED`); publica por exchange por defecto, routing key = nombre de la cola,
`delivery_mode=2`. Aplica al worker de la feature 002 (usar `mandatory=True`).

**D5 — `id_mensaje` (pendiente para feature 002).** Notificaciones deduplica con
`id_mensaje INTEGER PRIMARY KEY` (SQLite, 64 bits con signo). api-general usa
`Math.abs(hashCode())` (32 bits). El worker debe derivar un entero positivo de 63 bits del UUIDv5
(`int.from_bytes(uuid.bytes[:8]) & 0x7FFF_FFFF_FFFF_FFFF`), determinista por usuario/fecha/módulo.
