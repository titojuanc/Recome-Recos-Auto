# Research: Worker de recomendaciones automáticas

## D1. La "API de recomendaciones" se consume vía api-general
- **Decisión**: `GET {API_GENERAL_BASE_URL}/internal/v1/notification-recommendations/{recommendation_id}?module=peliculas|juegos` con `X-Internal-API-Key`.
- **Por qué**: Principio II (api-general es la puerta de entrada única). El endpoint ya devuelve `item_id`, `module`, `titulo` y `position`, y propaga 404/412/503 del servicio de recomendaciones; 502 si el ítem no está en el catálogo o no tiene título.
- **Alternativa descartada**: llamar directo al servicio de recomendaciones; viola la constitución y no devuelve título.
- **Pendiente**: el endpoint está en la rama `feature/recos-auto-usuarios-contacto` de api-general, sin mergear.

## D2. Concurrencia: un hilo = una conexión
- **Decisión**: `WORKER_CONCURRENCY` hilos (por defecto 4), cada uno con su conexión `BlockingConnection`, canal con confirms y `prefetch_count=1`, y su propio `httpx.Client`.
- **Por qué**: pika `BlockingConnection` no es thread-safe. Una conexión por hilo evita acks cruzados entre hilos (`add_callback_threadsafe`) y mantiene cada mensaje con un único dueño. Con quorum queues y prefetch 1 el reparto entre consumidores es parejo.
- **Alternativas**: (a) un consumidor con pool de hilos de trabajo y `add_callback_threadsafe` para ack/publicar: más piezas y más riesgo de carreras; (b) `asyncio` + `aio-pika`: dependencia nueva sin necesidad.
- **Presupuesto**: 10 000 mensajes / 7 200 s = 0,72 s por mensaje en total. Con 4 hilos, cada llamada puede tardar hasta ~2,9 s. Se mide en SC-005.

## D3. Interruptor de corte (clarificación 5)
- **Decisión**: estado compartido con lock: `cerrado` → `abierto` tras `BREAKER_FAILURES` (5) fallos transitorios **consecutivos** (el éxito reinicia el contador). Abierto: ningún hilo toma ni procesa mensajes; espera creciente `BREAKER_BACKOFF_S` (5 s, ×2, tope 60 s). Pasada la espera pasa a `semiabierto`: un solo hilo prueba con un mensaje; si tiene éxito se cierra, si falla se reabre con más espera.
- **Retención sin confirmar**: un mensaje entregado a un hilo cuando el corte abre se **retiene sin `ack` ni `nack`** y se reintenta en el lugar al reanudar. Retener no incrementa el `delivery-count` de la quorum queue; solo lo hace un `nack(requeue)`. Así se cumple SC-009 (002). Mientras espera, el hilo llama `connection.process_data_events()` para sostener los heartbeats.
- **Límite**: el `consumer_timeout` de las quorum queues (por defecto 30 min en RabbitMQ 3.8.15+) cierra el canal si un mensaje queda sin confirmar más de ese tiempo. La retención máxima por mensaje se acota a `BREAKER_MAX_HOLD_S` (por defecto 1500 s, validado < 1800 s); superado, se hace `nack(requeue)` normal.
- **Verificado (RabbitMQ 3.13, pika 1.4.4, quorum queue con `x-delivery-limit=5`, 2026-10-05)**:
  - Retener un mensaje 40 s sin `ack` ni `nack`, con `process_data_events()` sosteniendo los heartbeats: **no** incrementa `x-delivery-count` (el header ni aparece en la primera entrega).
  - Un `nack(requeue=True)` posterior lo deja en `count=1`; cada devolución suma 1. Con 6 entregas en total (1 + 5 reintentos) el mensaje pasa a la dead-letter.
  - **Perder la conexión con el mensaje retenido SÍ suma 1** (`count=2` en el experimento); cerrar solo el canal también suma 1.
  - **Consecuencia**: la retención protege a los mensajes mientras la api está caída, pero cada reconexión o apagado con un mensaje retenido le cuesta un reintento. Los hilos NO deben reconectar en bucle con mensajes retenidos; y en el apagado ordenado conviene terminar el mensaje en curso antes que devolverlo, cuando sea posible.
- **Ajuste a la spec (aplicado)**: FR-024 decía que los mensajes en curso se devolvían a la cola; el diseño los retiene (mejor para SC-009 (002)) y FR-024 ya fue corregido.

## D4. `id_mensaje`
- **Decisión**: `int.from_bytes(UUID(message_id).bytes[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF`; si da 0, se usa 1. `message_id` ya es UUIDv5 de `user_id|fecha|modulo` (feature 001), por lo que es estable por usuario, fecha y módulo.
- **Por qué**: Notificaciones usa `id_mensaje INTEGER PRIMARY KEY` (64 bits con signo) y exige entero. 63 bits dan colisión despreciable para decenas de miles de ids por día.

## D5. Contenido (clarificación 1: solo español)
- **Decisión**: dos plantillas configurables con `str.format`: `NOTIF_TITULO_TEMPLATE` (por defecto `"Tu recomendación de hoy: {titulo}"`) y `NOTIF_CUERPO_TEMPLATE` (por defecto `"Hoy te recomendamos {que_es}: {titulo}. Mirala acá: {url}"`).
  - `que_es` = `"una película"` o `"un juego"` según el módulo. El contenido por defecto no usa el nombre del usuario, para no depender de datos personales.
  - `{url}` = `NOTIF_URL_TEMPLATE` (por defecto `https://recome.example/{modulo}/{item_id}`; valor provisional, la página aún no existe).
  - El título del ítem se recorta, se eliminan caracteres de control y se trunca a 120 caracteres.
- **Por qué**: Notificaciones solo exige `titulo` y `cuerpo` strings. Plantillas por entorno cumplen "texto configurable" sin código nuevo.

## D6. Clasificación de resultados
| Respuesta / situación | Resultado | Acción sobre el mensaje |
|---|---|---|
| 200 con título | notificado | publicar → confirm → `ack` |
| 200 sin título o vacío | sin recomendación | `ack`, log con motivo |
| 404, 412 | sin recomendación | `ack`, log con motivo (sin reintento) |
| 400 | contrato roto | `nack(requeue=False)` (dead-letter) + log de error |
| 401, 403 | configuración (clave) | transitorio: reintento y cuenta para el interruptor; log de error |
| 502, 503, 5xx, timeout, red | transitorio | interruptor + `nack(requeue=True)`/retención |
| 429 | transitorio | igual que 5xx |
| Mensaje inválido (JSON o schema) | inválido | `nack(requeue=False)` (dead-letter) + log |
| Publicación sin ruta/sin confirm | transitorio | `nack(requeue=True)`; cuenta para el interruptor |
- **Sobre 401/403**: reintentar no los arregla, pero mandar a dead-letter a todos por una clave mal puesta pierde el día. Se tratan como transitorios y el interruptor frena el consumo para que se corrija la clave sin gastar reintentos.
- **Dead-letter directa**: `nack(requeue=False)` dead-letterea por el DLX configurado en la cola (`x-dead-letter-exchange`), sin código adicional.

## D7. Publicación hacia Notificaciones
- Exchange por defecto (`""`), routing key = `RABBITMQ_QUEUE_NOTIFICACIONES` (por defecto `notificaciones`), `mandatory=True`, `delivery_mode=2`, `content_type=application/json`, publisher confirms. No se declara la cola (la administra Notificaciones; redeclararla provoca `PRECONDITION_FAILED`). Se detecta `UnroutableError` como fallo transitorio. Validado en la feature 001 con pika 1.4.4 y RabbitMQ 3.13.
- Reconexión: ante pérdida de conexión el hilo reconecta con espera creciente; el mensaje en curso se reprocesa al reconectar (RabbitMQ lo reentrega) y la repetición se neutraliza con `id_mensaje`.

## D8. Apagado ordenado
- SIGTERM/SIGINT levantan un `threading.Event`. Cada hilo termina el mensaje en curso (o lo devuelve con `nack(requeue=True)` si está retenido por el corte), cierra su conexión y sale. Plazo total: `SHUTDOWN_TIMEOUT_S` (25 s, menor que el `stop_grace_period` de 30 s). Pasado el plazo se sale con código 1.
- Sin Supercronic, el proceso es el PID 1 del contenedor; se usa `exec` en el entrypoint (o `CMD` directo) para recibir la señal.

## D9. Configuración y topología compartida
- `ConfigWorker.from_env` es independiente de `Config` del cron (que exige variables de horario). Comparten los nombres y defaults de cola, TTL y `delivery_limit` mediante constantes en `common/config.py`.
- `declarar_topologia` pasa a tipar su parámetro con un `Protocol` (`users_queue`, `dead_letter_queue`, `dead_letter_exchange`, `delivery_limit`, `users_message_ttl_ms`, `dead_letter_ttl_ms`), sin cambiar su comportamiento. Test de contrato: ambas configuraciones generan `argumentos_cola_usuarios` idénticos.

## D10. Logs y contadores
- Un logger por flujo `worker`; campos: `message_id`, `corrida_id`, `modulo`, `resultado`, `motivo`, `intento`. Nunca `email`, `nombre` ni credenciales (ya lo filtra `common/logs.py`).
- Contadores con lock: recibidos, notificados, sin_recomendacion, reintentados, a_dead_letter (inválidos), pausas_del_corte. Resumen cada `SUMMARY_INTERVAL_S` (60 s) y al apagar. Los mensajes que llegan a dead-letter por límite de reintentos los decide el broker; el worker los cuenta al ver `redelivered` con `x-delivery-count` ≥ límite (informativo).

## D11. Docker
- Imagen propia `docker/worker/Dockerfile` (python:3.12-slim, usuario no root, `ENTRYPOINT ["python","-m","recos_auto.worker"]`). Compose: `worker` + mock de Notificaciones (cola declarada por un script de arranque del test, como haría Notificaciones).

## D12. Que cada usuario reciba SU recomendación (FR-025)
- api-general ahora devuelve `recommendation_id` en la respuesta (commit `57fefd4` en la rama `feature/recos-auto-usuarios-contacto`, sin mergear), de modo que el worker verifica de quién es la recomendación.
- La integridad se apoya en: (1) el par `recommendation_id`/`email` llega junto en el mismo registro de api-general y el cron lo copia sin transformarlo; (2) el worker usa solo datos del mensaje en curso, sin caché ni estado compartido (cliente HTTP por hilo); (3) se verifica que `recommendation_id` y `module` de la respuesta coinciden con el pedido; si no, no se notifica y el mensaje va a dead-letter.
- **Límite conocido**: un email cambiado en api-general entre la corrida y el procesamiento (hasta 2 h) se notifica al mail anterior; es aceptable por el TTL.
