# Tasks: Cron de carga diaria de usuarios

**Input**: Documentos de diseño en `/specs/001-cron-carga-usuarios/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md
**Tests**: INCLUIDOS. La constitución (Principio VII) exige test-first y contract testing; escribir cada test antes de su implementación y verificar que falla.
**Organization**: Tareas agrupadas por historia de usuario. Paquete único `src/recos_auto/` (ver plan.md).

## Format: `[ID] [P?] [Story] Descripción con ruta`

- **[P]**: se puede ejecutar en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: US1..US4 según spec.md

---

## Phase 1: Setup

**Purpose**: Estructura e infraestructura base del proyecto

- [ ] T001 Crear la estructura de directorios y los `__init__.py` de `src/recos_auto/`, `src/recos_auto/common/`, `src/recos_auto/cron/`, `tests/unit/`, `tests/contract/`, `tests/integration/`, `docker/cron/` según plan.md
- [ ] T002 Crear `pyproject.toml` con ruff (línea de 100), pytest (`pythonpath = src`, markers `integration`) y metadatos del paquete
- [ ] T003 [P] Crear `requirements.txt` (`pika`, `httpx`, `pydantic[email]`) y `requirements-dev.txt` (`pytest`, `pytest-mock`, `ruff`, `jsonschema`)
- [ ] T004 [P] Crear `.env.example` con todas las variables de `contracts/entorno.md` (sin valores reales) y `.gitignore` (`.env`, `__pycache__`, `.venv`)
- [ ] T005 [P] Crear `docker-compose.test.yml` con solo RabbitMQ 3.13 (management) para los tests de integración

---

## Phase 2: Foundational (bloquea todas las historias)

**Purpose**: Configuración, logs, mensaje y topología compartidos con el worker (feature 002)

**⚠️ CRITICAL**: Ninguna historia puede empezar hasta completar esta fase

- [ ] T006 Crear `tests/conftest.py` con fixtures: reloj inyectable, `httpx.MockTransport` de api-general, conexión RabbitMQ real que se saltea (`skip`) si no hay broker, y cola temporal por test
- [ ] T007 [P] Test de `Config.from_env` en `tests/unit/test_config.py`: lista TODAS las obligatorias faltantes, rangos (`API_GENERAL_PAGE_SIZE` 1–500), zona/cron/fecha inválidos nombran la variable, `repr` sin secretos (FR-020)
- [ ] T008 [P] Test del filtro de logs en `tests/unit/test_logs.py`: JSON por línea a stdout, nunca emite email, nombre, claves ni URL con credenciales (FR-017)
- [ ] T009 [P] Test de `MensajeUsuario` y `message_id` en `tests/unit/test_mensajes.py`: UUIDv5 determinístico por `user_id|fecha|modulo`, validación de campos, nombres con acentos/emojis intactos (FR-008, FR-012)
- [ ] T010 [P] Test de contrato del mensaje en `tests/contract/test_schema_mensaje.py`: el mensaje generado valida contra `specs/001-cron-carga-usuarios/contracts/mensaje-usuario.schema.json`
- [ ] T011 [P] Test de contrato de topología en `tests/contract/test_topologia.py` (marker `integration`): declaración idempotente, redeclarar con otro `x-delivery-limit` falla con `PRECONDITION_FAILED`, tras 5 reintentos con `nack(requeue)` el mensaje llega a `recos-auto.usuarios.dead-letter`; un mensaje con TTL vencido pasa a la dead-letter (usar TTL corto en el test) y la dead-letter declara su propio TTL de 7 días (FR-013, FR-014)
- [ ] T012 Implementar `src/recos_auto/common/config.py` (`Config.from_env`, errores agregados, `repr` sin secretos) — hace pasar T007
- [ ] T013 [P] Implementar `src/recos_auto/common/logs.py` (logs JSON a stdout, filtro de PII, silencia loggers de httpx/pika) — hace pasar T008
- [ ] T014 [P] Implementar `src/recos_auto/common/mensajes.py` (`MensajeUsuario` pydantic, `message_id` UUIDv5 con namespace fijo) — hace pasar T009 y T010
- [ ] T015 Implementar `src/recos_auto/common/topology.py`: declara cola quorum durable `recos-auto.usuarios`, DLX fanout `recos-auto.usuarios.dlx` y DLQ `recos-auto.usuarios.dead-letter` con `x-delivery-limit`, TTL de 2 h en la cola y TTL de 7 días en la dead-letter; única fuente de verdad para cron y worker — hace pasar T011

**Checkpoint**: Base lista; las historias pueden empezar

---

## Phase 3: User Story 2 - Alternar el módulo día por medio (Priority: P1)

**Goal**: El módulo del día se calcula de forma determinística (`peliculas`/`juegos`) y es el mismo para toda la corrida.

**Independent Test**: Serie de fechas consecutivas alterna; misma fecha da el mismo resultado; cambio de mes/año sin saltos.

### Tests for User Story 2 ⚠️

- [ ] T025 [P] [US2] Test en `tests/unit/test_modulo.py`: referencia 2026-10-05 → peliculas, juegos, peliculas; fecha anterior a la referencia (2026-10-04 → juegos); cambio 31/12→1/1 y año bisiesto; idempotente por fecha (FR-009)

### Implementation for User Story 2

- [ ] T026 [US2] Implementar `src/recos_auto/cron/modulo.py`: `modulo_para(fecha, referencia)` pura, `(fecha - referencia).days % 2` — hace pasar T025
- [ ] T027 [US2] Verificar en `tests/unit/test_corrida.py` que todos los mensajes de una corrida llevan el mismo `modulo` y que `--date` cambia el módulo (FR-003, FR-009)

**Checkpoint**: Módulo determinístico listo; US1 puede usarlo

---

## Phase 4: User Story 1 - Encolar a todos los usuarios cada día a las 12:00 (Priority: P1) 🎯 MVP

**Goal**: Una corrida recorre todas las páginas de api-general y publica un mensaje por usuario válido en `recos-auto.usuarios`.

**Independent Test**: api-general simulada con N usuarios en varias páginas + RabbitMQ real: la cola contiene exactamente N mensajes válidos, sin worker.

### Tests for User Story 1 ⚠️ (escribir primero, deben fallar)

- [ ] T016 [P] [US1] Test del cliente paginado en `tests/unit/test_api_general.py`: recorre todas las páginas, `next_page_token` repetido corta con error, tope `API_GENERAL_MAX_PAGES`, página sin usuarios válidos pero con token nuevo continúa (FR-004)
- [ ] T017 [P] [US1] Test de contrato de la respuesta en `tests/contract/test_api_general_contract.py` contra `contracts/api-general-notification-targets.md` (campos `recommendation_id`, `user_id`, `nombre`, `email`, `idioma`, `next_page_token`; header `X-Internal-API-Key`)
- [ ] T018 [P] [US1] Test del publicador en `tests/unit/test_publicador.py`: propiedades `delivery_mode=2`, `content_type`, `message_id`; `mandatory=True`; `UnroutableError` se trata como fallo (FR-010)
- [ ] T019 [P] [US1] Test de orquestación en `tests/unit/test_corrida.py`: omite usuarios sin `recommendation_id`/`user_id`/`email` (FR-006), deduplica por `user_id` (FR-007), invariante `recibidos = publicados + omitidos + repetidos + fallidos`, 0 usuarios termina bien
- [ ] T020 [US1] Test de integración en `tests/integration/test_corrida_rabbit.py`: 250 usuarios en 3 páginas dejan 250 mensajes válidos en la cola; api-general vacía deja 0 mensajes

### Implementation for User Story 1

- [ ] T021 [P] [US1] Implementar `src/recos_auto/cron/api_general.py`: cliente `httpx` paginado con autenticación `X-Internal-API-Key`, guardas de paginación y timeouts (sin reintentos todavía; se agregan en US3) — hace pasar T016, T017
- [ ] T022 [P] [US1] Implementar `src/recos_auto/cron/publicador.py`: pika con `confirm_delivery`, `mandatory`, persistente, exchange por defecto y routing key = nombre de la cola — hace pasar T018
- [ ] T023 [US1] Implementar `src/recos_auto/cron/corrida.py`: orquesta fecha en UTC-3, módulo (usa `modulo_para` de T026), lectura de páginas, validación, deduplicación, publicación, contadores y evento `corrida_finalizada`; recibe el reloj como parámetro inyectable (FR-018) — hace pasar T019, T020
- [ ] T024 [US1] Implementar `src/recos_auto/cron/__main__.py` con el comando `run [--date YYYY-MM-DD]` (fecha mal formada → código 78) y salida 0 en éxito (códigos restantes en US3)

**Checkpoint**: MVP completo (US2 + US1); se prueba sin worker

---

## Phase 5: User Story 3 - Soportar fallos sin perder ni duplicar trabajo (Priority: P2)

**Goal**: Reintentos acotados, bloqueo de corridas simultáneas, códigos de salida y cierre ordenado; relanzar no cambia la identidad de los mensajes.

**Independent Test**: api-general falla en la página 2 o RabbitMQ no confirma; verificar reintentos, resultado y que relanzar produce los mismos `message_id`.

### Tests for User Story 3 ⚠️

- [ ] T028 [P] [US3] Test de reintentos en `tests/unit/test_api_general_reintentos.py`: 5xx/timeouts/red reintentan con backoff y luego siguen; 401/403 fallan sin reintentar (FR-005)
- [ ] T029 [P] [US3] Test del publicador en `tests/unit/test_publicador_reintentos.py`: reintento por mensaje no confirmado, `fallidos` se cuenta sin PII, `MAX_CONSECUTIVE_PUBLISH_FAILURES` aborta la corrida
- [ ] T030 [P] [US3] Test de bloqueo en `tests/unit/test_bloqueo.py`: `flock` no bloqueante; la segunda corrida devuelve código 75 y registra `corrida_omitida_por_bloqueo` (FR-011)
- [ ] T031 [P] [US3] Test de códigos de salida en `tests/unit/test_codigos_salida.py`: 0 éxito, 1 error fatal/interrumpida, 2 parcial, 75 bloqueo, 78 configuración (`contracts/cli.md`)
- [ ] T032 [US3] Test de integración en `tests/integration/test_idempotencia.py`: relanzar la misma fecha publica los mismos `message_id`; fallo en página 2 con éxito al reintentar no duplica páginas previas
- [ ] T033 [US3] Test de señales en `tests/integration/test_senales.py`: SIGTERM durante la corrida termina el mensaje en curso, registra `corrida_interrumpida` y sale con código 1 (FR-024)

### Implementation for User Story 3

- [ ] T034 [US3] Agregar reintentos con backoff exponencial a `src/recos_auto/cron/api_general.py` (transitorios sí, 401/403 no) — hace pasar T028
- [ ] T035 [US3] Agregar reintentos por mensaje y aborto por fallos consecutivos a `src/recos_auto/cron/publicador.py` — hace pasar T029
- [ ] T036 [P] [US3] Implementar `src/recos_auto/cron/bloqueo.py` (`flock` sobre `/tmp`) — hace pasar T030
- [ ] T037 [US3] Integrar bloqueo, `resultado` (`exito|parcial|error|interrumpida|omitida_por_bloqueo`), manejo de SIGTERM/SIGINT y códigos de salida en `src/recos_auto/cron/corrida.py` y `src/recos_auto/cron/__main__.py` — hace pasar T031, T032, T033

**Checkpoint**: Corrida robusta y repetible

---

## Phase 6: User Story 4 - Desplegar y operar en Dokploy (Priority: P2)

**Goal**: Imagen que corre Supercronic, configurable solo por variables de entorno, con corrida manual y arranque ordenado.

**Independent Test**: Construir la imagen, iniciarla solo con variables de entorno, ver zona y próxima ejecución, correr `run` manualmente y fallar con mensaje claro si falta una variable.

### Tests for User Story 4 ⚠️

- [ ] T038 [P] [US4] Test de `bootstrap` en `tests/unit/test_bootstrap.py`: genera el crontab con `CRON_TZ=<RUN_TIMEZONE>` y `RUN_SCHEDULE` sin escribir secretos, registra `bootstrap_ok` con zona y próxima ejecución, registra `corrida_omitida_al_arrancar` si ya pasó la hora de hoy (FR-001, FR-025), falta de variables termina con 78 (FR-020)
- [ ] T039 [US4] Test de arranque de contenedor en `tests/integration/test_contenedor.py`: construye la imagen, falta una variable → sale con 78 y la nombra; con todas, queda activo; `docker stop` termina en pocos segundos; `docker exec ... run` ejecuta una corrida; con `RUN_SCHEDULE` a 1 minuto verifica el disparo (SC-003); `docker stop` ejercita el `trap` del entrypoint (FR-024) (FR-019, FR-021)

### Implementation for User Story 4

- [ ] T040 [US4] Implementar `src/recos_auto/cron/bootstrap.py` y el subcomando `bootstrap <ruta-crontab>` en `src/recos_auto/cron/__main__.py` — hace pasar T038
- [ ] T041 [P] [US4] Crear `docker/cron/entrypoint.sh`: ejecuta `bootstrap`, lanza `supercronic -split-logs` como hijo, `trap` de SIGTERM que envía `pkill -TERM -f "python -m recos_auto.cron"` y luego `kill -TERM` a Supercronic (Supercronic no reenvía la señal; ver research.md)
- [ ] T042 [US4] Crear `docker/cron/Dockerfile`: `python:3.12-slim` + `tzdata` + Supercronic v0.2.49 con checksum sha1 fijado por arquitectura (amd64 `e63c11a9726b775a6a11801e81af4f3fb926aa68`, arm64 `0b6c5bb743e0b0dafed1132198c81807927ac413`), usuario no root, sin puertos ni volúmenes, `supercronic -test` se ejecuta en `bootstrap` (T040) sobre el crontab generado — hace pasar T039
- [ ] T043 [P] [US4] Crear una api-general simulada en `docker/mock-api-general/` (servicio HTTP mínimo con `GET /internal/v1/notification-targets` paginado) para desarrollo local (FR-023)
- [ ] T044 [US4] Crear `docker-compose.yml` con `rabbitmq`, `mock-api-general` y `cron` usando solo variables de entorno; documentar cómo reutilizar la red del stack `e2e-local` (ver quickstart.md)
- [ ] T045 [P] [US4] Crear `README.md` con desarrollo local, pruebas, despliegue en Dokploy, corrida manual (`docker exec <contenedor> python -m recos_auto.cron run [--date]`) y troubleshooting de `PRECONDITION_FAILED` (FR-022)

**Checkpoint**: Imagen lista para Dokploy

---

## Phase 7: Polish & Cross-Cutting

- [ ] T046 [P] Test de PII en `tests/integration/test_pii_logs.py`: una corrida completa no deja emails, nombres ni claves en la salida (SC-007)
- [ ] T047 [P] Prueba de rendimiento en `tests/integration/test_rendimiento.py`: 10.000 usuarios en menos de 15 min (SC-004), marcada como lenta
- [ ] T048 Revisar que el cron no envía notificaciones ni accede a otros servicios (SC-008, Principio II) con una búsqueda de imports/clientes en `src/`
- [ ] T049 Pasar `ruff check` y `ruff format --check`; corregir hallazgos
- [ ] T050 Ejecutar la validación de `specs/001-cron-carga-usuarios/quickstart.md` de punta a punta contra el stack local y ajustar el documento
- [ ] T051 Actualizar `research.md` (D1 "a verificar") con el resultado de T039 si hubiera diferencias

---

## Dependencies & Execution Order

- **Setup (Phase 1)** → **Foundational (Phase 2)** → historias.
- **US2 (T025–T027)** va antes que US1 porque `corrida.py` (T023) usa `modulo_para` (T026).
- **US1** es independiente de US3 y US4 una vez hechas la Phase 2 y US2.
- **US3** extiende `api_general.py`, `publicador.py` y `corrida.py` de US1 (mismos archivos: no en paralelo con US1).
- **US4** depende de `__main__.py`/`corrida.py` (US1) y de `config.py`; `bootstrap` y Docker no tocan la lógica de la corrida.
- **Polish** al final.

### Parallel Opportunities

- Phase 1: T003, T004, T005.
- Phase 2: tests T007–T011 en paralelo; luego T013, T014 en paralelo (T012 y T015 tras sus tests).
- US1: tests T016–T019 en paralelo; luego T021 y T022 en paralelo.
- US3: tests T028–T031 en paralelo; T036 en paralelo con T034/T035.
- US4: T041, T043 y T045 en paralelo.

### Parallel Example: User Story 1

```text
Task: "Test del cliente paginado en tests/unit/test_api_general.py"
Task: "Test de contrato en tests/contract/test_api_general_contract.py"
Task: "Test del publicador en tests/unit/test_publicador.py"
Task: "Test de orquestación en tests/unit/test_corrida.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Phase 1 y Phase 2.
2. US2 (módulo) y US1 (corrida feliz).
3. **Validar**: 250 usuarios → 250 mensajes con un RabbitMQ real, sin worker.

### Incremental Delivery

1. MVP (US1 + US2) → demo con `docker compose` local.
2. US3 → robustez y repetibilidad.
3. US4 → imagen operable en Dokploy.
4. Polish.

## Notes

- Verificar que cada test falle antes de implementar.
- Un commit por tarea o grupo lógico.
- El `id_mensaje` entero que exige Notificaciones lo deriva el worker (feature 002), no el cron.
- Resolver antes de la corrida real: confirmar nombres de cola contra el RabbitMQ real, la clave del título en el catálogo y si el cron usa una clave de servicio propia.
