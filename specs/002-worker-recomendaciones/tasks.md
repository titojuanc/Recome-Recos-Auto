# Tasks: Worker de recomendaciones automáticas

**Input**: Documentos de diseño en `/specs/002-worker-recomendaciones/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md
**Tests**: INCLUIDOS. La constitución (Principio VII) exige test-first y contract testing: escribir cada test antes de su implementación y verificar que falla.
**Organization**: Tareas agrupadas por historia de usuario. Mismo paquete `src/recos_auto/` que la feature 001; el código nuevo vive en `src/recos_auto/worker/` y reutiliza `common/`.

## Format: `[ID] [P?] [Story] Descripción con ruta`

- **[P]**: se puede ejecutar en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: US1..US4 según spec.md

---

## Phase 1: Setup

- [ ] T001 Crear el paquete `src/recos_auto/worker/__init__.py` y `tests/` auxiliares sin lógica; agregar al `pyproject.toml` el marcador `worker` si hace falta.
- [ ] T002 [P] Agregar a `tests/conftest.py` los fixtures del worker: `env_worker` (variables mínimas), `config_worker`, `cola_notificaciones` (declara una cola de salida única por test, como lo haría Notificaciones) y `publicar_usuarios(cfg, n)` (publica mensajes de usuario válidos en la cola de entrada).
- [ ] T003 [P] Agregar las variables del worker (`contracts/entorno.md`) a `.env.example` sin valores reales.

---

## Phase 2: Foundational (bloquea todas las historias)

- [ ] T004 [P] Test `tests/unit/test_worker_config.py`: obligatorias faltantes se listan todas sin valores; inválidas (concurrencia < 1, plantillas con llaves desconocidas, números negativos) se nombran; defaults de `contracts/entorno.md`; `repr` sin secretos.
- [ ] T005 `src/recos_auto/worker/config.py`: `ConfigWorker.from_env` (reutiliza `ConfigError`); mover a `common/config.py` las constantes de cola, TTL y `delivery_limit` compartidas con el cron. Hace pasar T004.
- [ ] T006 [P] Test de contrato `tests/contract/test_topologia_worker.py` (FR-012): `ConfigWorker` y la `Config` del cron producen `argumentos_cola_usuarios` y `argumentos_dead_letter` idénticos; con RabbitMQ real, declarar desde ambos es idempotente y no da `PRECONDITION_FAILED`.
- [ ] T007 `src/recos_auto/common/topology.py`: tipar el parámetro con un `Protocol` (`users_queue`, `dead_letter_queue`, `dead_letter_exchange`, `delivery_limit`, `users_message_ttl_ms`, `dead_letter_ttl_ms`) sin cambiar su comportamiento. Los tests de la feature 001 deben seguir en verde. Hace pasar T006.
- [ ] T008 [P] Test `tests/unit/test_notificacion.py`: `id_mensaje` determinístico, positivo, ≤ 2^63 − 1, distinto para usuario/fecha/módulo distintos y nunca 0; contenido con plantillas por defecto para `peliculas` y `juegos`; título con caracteres de control, espacios y > 120 caracteres; `idioma` ignorado; el cuerpo por defecto no contiene el nombre.
- [ ] T009 `src/recos_auto/worker/notificacion.py`: `id_mensaje_para`, `Notificacion` (pydantic, `extra="forbid"`, canal fijo `mail`), `armar_notificacion(mensaje, recomendacion, cfg)`. Hace pasar T008.
- [ ] T010 [P] Test de contrato `tests/contract/test_schema_notificacion.py`: toda `Notificacion` generada valida contra `specs/002-worker-recomendaciones/contracts/mensaje-notificacion.schema.json`; los casos inválidos (sin mail, canal distinto) lo incumplen.
- [ ] T011 [P] Test `tests/unit/test_contadores.py`: incrementos concurrentes desde varios hilos, resumen con todos los campos, sin datos personales.
- [ ] T012 `src/recos_auto/worker/contadores.py`: contadores con lock y `resumen()`. Hace pasar T011.
- [ ] T013 [P] Test `tests/unit/test_recomendaciones.py` y `tests/contract/test_api_recomendacion_contract.py` (con `httpx.MockTransport`): URL, parámetro `module`, header `X-Internal-API-Key`; respuesta 200 válida; clasificación por código (404/412 → sin recomendación; 400 → inválido; 401/403/429/5xx/timeout/red → transitorio); título vacío → sin recomendación; la clave nunca aparece en excepciones ni logs; sin reintentos propios.
- [ ] T014 `src/recos_auto/worker/recomendaciones.py`: cliente de api-general que devuelve un `Resultado` tipado (`Recomendacion` o error clasificado). Hace pasar T013.

**Checkpoint**: base lista (config, topología compartida, notificación, contadores, cliente).

---

## Phase 3: User Story 1 - Convertir un usuario encolado en una notificación (P1) 🎯 MVP

**Independent Test**: N mensajes de usuario en la cola + api simulada + RabbitMQ real → N notificaciones válidas en la cola de salida y la cola de usuarios vacía.

- [ ] T015 [P] [US1] Test `tests/unit/test_procesador.py` (camino feliz): dado un mensaje válido y una recomendación, devuelve `NOTIFICADO` con la notificación correcta para `peliculas` y para `juegos`; el mismo mensaje procesado dos veces produce el mismo `id_mensaje`.
- [ ] T016 [US1] `src/recos_auto/worker/procesador.py`: lógica pura mensaje → `Resultado` (sin pika). Hace pasar T015.
- [ ] T017 [P] [US1] Test `tests/unit/test_worker_publicador.py` y `tests/contract/test_publicacion_notificaciones.py` (RabbitMQ real): publica en el exchange por defecto con routing key = cola de salida, `mandatory`, `delivery_mode=2`, confirms; NO declara la cola de salida; cola inexistente → error transitorio detectable (`UnroutableError`).
- [ ] T018 [US1] `src/recos_auto/worker/publicador.py`: publicación con confirms, `mandatory` y timeout de confirm. Hace pasar T017.
- [ ] T019 [P] [US1] Test de integración `tests/integration/test_worker_flujo.py`: 25 mensajes → 25 notificaciones válidas contra el schema; cola de usuarios vacía; contadores `recibidos=25 notificados=25`; el `ack` ocurre solo tras el confirm (con un publicador que falla, el mensaje no se confirma).
- [ ] T020 [US1] `src/recos_auto/worker/consumidor.py`: un consumidor (un hilo) con conexión propia, `prefetch=1`, declaración de la topología compartida, `ack` tras el confirm. Hace pasar T019.
- [ ] T021 [US1] `src/recos_auto/worker/__main__.py` mínimo: carga config, logs, arranca un consumidor.

**Checkpoint**: el flujo feliz funciona de punta a punta con un solo hilo.

---

## Phase 4: User Story 2 - Fallos sin notificar al usuario (P1)

**Independent Test**: api simulada con 404, 412, 503 y timeouts, y mensajes inválidos: ninguno produce una notificación y cada mensaje termina en un estado final registrado.

- [ ] T022 [P] [US2] Ampliar `tests/unit/test_procesador.py` con la tabla de `research.md` D6: 404/412/título vacío → `SIN_RECOMENDACION(motivo)`; 400, JSON roto, schema inválido, módulo o versión desconocidos → `INVALIDO(motivo)`; 401/403/429/5xx/timeout/red/fallo de publicación → `TRANSITORIO(motivo)`; ningún error produce notificación (SC-003).
- [ ] T023 [US2] Completar `procesador.py` con la clasificación. Hace pasar T022.
- [ ] T024 [P] [US2] Test `tests/unit/test_interruptor.py` con reloj inyectable: abre tras N fallos consecutivos; un éxito reinicia el contador; espera creciente con tope; `SEMIABIERTO` deja pasar una sola prueba; cierra al éxito y reabre con mayor espera al fallo; seguro entre hilos.
- [ ] T025 [US2] `src/recos_auto/worker/interruptor.py`. Hace pasar T024.
- [ ] T026 [P] [US2] Test de integración `tests/integration/test_worker_fallos.py`: 404 y 412 → cola de salida vacía, mensaje confirmado, motivo en logs; 503 persistente (con interruptor deshabilitado por config) → 6 entregas y luego dead-letter; mensaje inválido → dead-letter directo sin reintentos; cola de salida inexistente → reintento y nunca `ack` sin publicar.
- [ ] T027 [US2] Completar `consumidor.py`: `ack` para `NOTIFICADO` y `SIN_RECOMENDACION`, `nack(requeue=False)` para `INVALIDO`, `nack(requeue=True)` para `TRANSITORIO`. Hace pasar T026.
- [ ] T028 [P] [US2] Test de integración `tests/integration/test_worker_corte.py` (SC-009, tiempos reducidos): con api caída y mensajes en cola, el worker registra `corte_abierto`, ningún mensaje llega a dead-letter y el `x-delivery-count` no crece; al volver la api registra `corte_cerrado` y procesa todo; un mensaje retenido más de `BREAKER_MAX_HOLD_S` se devuelve a la cola.
- [ ] T029 [US2] Integrar el interruptor en `consumidor.py`: retención sin confirmar del mensaje en curso, `process_data_events()` para sostener heartbeats durante la espera, tope de retención, reanudación con un único mensaje de prueba. Hace pasar T028.
- [ ] T030 [P] [US2] Test de integración `tests/integration/test_worker_reconexion.py` (FR-015, SC-008): cerrar las conexiones del consumidor desde el broker o reiniciar el contenedor de RabbitMQ de prueba; el worker reconecta con espera creciente y retoma sin intervención; el mensaje en curso se reprocesa sin duplicar la identidad.
- [ ] T031 [US2] Reconexión con espera creciente en `consumidor.py` y en `publicador.py`. Hace pasar T030.

**Checkpoint**: todos los errores terminan sin notificar y sin perder mensajes.

---

## Phase 5: User Story 3 - Procesar a todos dentro de 2 horas (P2)

**Independent Test**: 10 000 mensajes con una api simulada de latencia realista se vacían en menos de 2 h con una instancia.

- [ ] T032 [P] [US3] Test de integración `tests/integration/test_worker_concurrencia.py`: con `WORKER_CONCURRENCY=4` y 200 mensajes, cada mensaje se publica exactamente una vez, hay 4 conexiones distintas, el fallo de un mensaje no afecta a los demás en curso y los contadores suman lo recibido; con `WORKER_CONCURRENCY=1` el comportamiento es secuencial. Además: el worker no consume la dead-letter.
- [ ] T033 [US3] `__main__.py`: lanzar `WORKER_CONCURRENCY` hilos, cada uno con su conexión, canal y cliente HTTP; el interruptor y los contadores se comparten. Hace pasar T032.
- [ ] T034 [P] [US3] Test de rendimiento `tests/integration/test_worker_rendimiento.py` (marcador `lento`): 10 000 mensajes con latencia simulada de la api; todos procesados en menos de 2 h (SC-005) y 0 duplicados. Anotar en el reporte la latencia máxima tolerable por llamada.

**Checkpoint**: SC-005 verificado y SC-009 de la feature 001 cerrado.

---

## Phase 6: User Story 4 - Operación, apagado ordenado y observabilidad (P2)

**Independent Test**: arrancar el contenedor con variables válidas e inválidas, enviarle SIGTERM durante el procesamiento y revisar los logs.

- [ ] T035 [P] [US4] Test `tests/unit/test_worker_main.py`: variables faltantes → exit 78 y mensaje que nombra las variables sin valores; `--help`/argumentos.
- [ ] T036 [P] [US4] Test de integración `tests/integration/test_worker_senales.py`: SIGTERM real sobre un subproceso con mensajes en curso; termina en < 30 s, no toma otro mensaje, no pierde ni duplica notificaciones, y emite el resumen final.
- [ ] T037 [US4] Apagado ordenado en `__main__.py` y `consumidor.py`: `threading.Event`, terminar o devolver el mensaje en curso (incluidos los retenidos por el corte), cerrar conexiones, plazo `SHUTDOWN_TIMEOUT_S`. Hace pasar T035 y T036.
- [ ] T038 [P] [US4] Test `tests/integration/test_worker_pii_logs.py` (SC-007): una corrida completa con fallos de todos los tipos no deja emails, nombres, claves ni URL de RabbitMQ en los logs.
- [ ] T039 [US4] Logs estructurados por mensaje (`message_id`, `corrida_id`, `modulo`, `resultado`, `motivo`) y resumen periódico (`SUMMARY_INTERVAL_S`) y final con contadores. Hace pasar T038.
- [ ] T040 [US4] `docker/worker/Dockerfile`: `python:3.12-slim`, usuario no root, `ENTRYPOINT ["python","-m","recos_auto.worker"]` (PID 1 recibe las señales), sin puertos ni volúmenes.
- [ ] T041 [US4] `docker-compose.yml`: agregar el servicio `worker` y un servicio auxiliar que declara la cola `notificaciones` (reemplaza a Recome-Recos-Notificaciones en el entorno local); `stop_grace_period: 30s`.
- [ ] T042 [P] [US4] Test `tests/integration/test_worker_contenedor.py` (marcador `contenedor`): construir la imagen; sin variables → exit 78; con variables válidas procesa mensajes; `docker stop` termina en < 30 s.
- [ ] T043 [US4] Actualizar `README.md` con el worker (ejecución, variables, interruptor, comandos de prueba).

---

## Phase 7: Polish y verificación transversal

- [ ] T044 Ejecutar `ruff check` y `ruff format`; toda la suite (`pytest -q`) incluyendo las pruebas del cron.
- [ ] T045 Ejecutar el flujo de `quickstart.md` (secciones 1 a 3) y registrar los resultados.
- [ ] T046 Verificar SC-003 con un test transversal: con todos los modos de fallo activos, la cola de salida recibe 0 mensajes de error o parciales.
- [ ] T047 Verificar que `common/topology.py` sigue dando los mismos argumentos que usa el cron (tests de la feature 001 en verde) y que el worker no declara nunca la cola de salida.
- [ ] T048 Actualizar `research.md` y `spec.md` con lo aprendido (por ejemplo, la latencia tolerable medida en T034 y el comportamiento real del `consumer_timeout`).
- [ ] T049 Confirmar el contrato con api-general y con Notificaciones cuando estén disponibles (rama sin mergear, nombre de la cola de salida, versión de RabbitMQ) y anotar las diferencias.

---

## Dependencies & Execution Order

- **Setup → Foundational → historias**: Foundational bloquea todo.
- **US1** requiere Foundational. **US2** extiende `procesador.py` y `consumidor.py` de US1. **US3** requiere `consumidor.py` completo (US1 + US2). **US4** requiere `__main__.py` de US3 para el apagado con hilos.
- Dentro de cada fase: el test (marcado [P] cuando es un archivo nuevo) va antes que su implementación y debe fallar primero.
- Tareas que tocan el mismo archivo (`consumidor.py`: T020, T027, T029, T031; `__main__.py`: T021, T033, T037) son secuenciales entre sí.

## Parallel Example

Tras el Checkpoint de Foundational: T015, T017 y T019 (tests de US1) en paralelo; luego T016, T018 y T020 en ese orden.

## Implementation Strategy

1. **MVP**: Setup + Foundational + US1 (flujo feliz con un hilo).
2. Agregar US2 (fallos, interruptor, reconexión): sin esto no se debe habilitar el worker en producción.
3. US3 (concurrencia y rendimiento) y US4 (operación y contenedor).
4. Polish y verificación contra los sistemas reales cuando existan.
