# Implementation Plan: Cron de carga diaria de usuarios

**Branch**: `001-cron-carga-usuarios` | **Date**: 2026-10-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-cron-carga-usuarios/spec.md`

## Summary

Un contenedor que ejecuta **Supercronic** (cron para contenedores) como proceso principal. Todos los días a las 12:00 (UTC-3) dispara un comando Python de una sola pasada (`python -m recos_auto.cron run`) que:

1. calcula la fecha de corrida (UTC-3) y el módulo del día (alternancia día por medio, sin estado);
2. recorre **todas** las páginas de `GET /internal/v1/notification-targets` de api-general (con reintentos acotados);
3. publica un mensaje persistente por usuario válido en `recos-auto.usuarios` (RabbitMQ existente), con confirmación del broker e identidad determinística (usuario + fecha + módulo);
4. emite un resumen estructurado de la corrida y termina con un código de salida que refleja el resultado.

El cron no guarda estado entre corridas (sin base de datos ni volúmenes): la repetición segura sale de la identidad determinística de los mensajes. Toda la configuración viene de variables de entorno, lo que lo hace desplegable en Dokploy sin archivos montados.

## Technical Context

**Language/Version**: Python 3.12 (imagen `python:3.12-slim`; compatible con 3.11+ como Notificaciones)
**Primary Dependencies**: `pika` (RabbitMQ, igual que Notificaciones), `httpx` (cliente HTTP con timeouts y transporte simulable en tests), `pydantic[email]` (validación del mensaje, igual que Notificaciones). Programación: **Supercronic v0.2.49** (binario externo con checksum fijado).
**Storage**: N/A. Único artefacto local: un archivo de bloqueo en `/tmp` (por contenedor) y el crontab generado al arrancar en `/tmp`.
**Testing**: pytest + pytest-mock; `httpx.MockTransport` para api-general; RabbitMQ real vía docker compose (se saltea si no está disponible, como Notificaciones); ruff para lint.
**Target Platform**: Contenedor Linux (amd64 y arm64) en Dokploy; docker compose para desarrollo local.
**Project Type**: Servicio batch (CLI de una pasada + scheduler de contenedor). El worker (feature 002) vivirá en el mismo repo y comparte `common/`.
**Performance Goals**: 10.000 usuarios en < 15 min (SC-004). Estimación: 20 páginas de 500 + 10.000 publicaciones con confirmación síncrona (~decenas de ms cada una) = pocos minutos.
**Constraints**: sin puertos, sin volúmenes, sin archivos montados (FR-021); logs a stdout sin datos personales (FR-017); una sola réplica; cierre ordenado ante SIGTERM (FR-024).
**Scale/Scope**: hasta decenas de miles de usuarios; sin paralelismo en esta versión (Principio IX).

## Constitution Check

*GATE: debe pasar antes de la investigación (Fase 0). Re-verificado tras el diseño (Fase 1).*

| Principio | Estado | Cómo se cumple |
|---|---|---|
| I. Responsabilidad acotada | PASS | El cron solo lista y encola. No recomienda, no notifica, no persiste datos de usuario. |
| II. Solo api-general y RabbitMQ | PASS | Únicos clientes externos: `api_general.py` y `publicador.py`. Ningún acceso a otras bases ni a recomendaciones. |
| III. Contratos externos | PASS | Mensaje validado con pydantic y con un schema JSON versionado en `contracts/` antes de publicar; contrato de api-general documentado como copia derivada. |
| IV. Ejecución diaria idempotente | PASS | `message_id` = UUIDv5(usuario, fecha, módulo); módulo calculado desde la fecha; mensajes con TTL de 2 h (los vencidos van a la dead-letter, 7 días). |
| V. Errores sin avisar al usuario | PASS | El cron no envía notificaciones; los fallos terminan con código ≠ 0 y resumen. |
| VI. Convención RabbitMQ | PASS | Cola quorum durable, DLX/DLQ y `x-delivery-limit` 5, declaradas desde un módulo compartido con el worker. |
| VII. Test-first y contract testing | PASS | Estrategia en la sección de pruebas; reloj inyectable. |
| VIII. Observabilidad y seguridad | PASS con nota | Resumen estructurado por corrida como fuente de métricas. No hay endpoint `/metrics` porque FR-021 prohíbe puertos; la alerta de "corrida ausente" queda para Dokploy (ver research D9). |
| IX. Simplicidad | PASS | Un solo proceso Python de una pasada, sin base de datos, sin paralelismo. Ver Complexity Tracking por Supercronic. |

## Project Structure

### Documentation (this feature)

```text
specs/001-cron-carga-usuarios/
├── plan.md              # Este archivo
├── research.md         # Decisiones y alternativas descartadas
├── data-model.md       # Entidades, validaciones y estados
├── quickstart.md       # Desarrollo local, pruebas, operación y despliegue en Dokploy
├── contracts/
│   ├── mensaje-usuario.schema.json       # Contrato cron -> worker (lo produce esta feature)
│   ├── api-general-notification-targets.md  # Contrato consumido (copia derivada; custodia api-general)
│   ├── cli.md                            # Comandos y códigos de salida
│   └── entorno.md                        # Variables de entorno
└── tasks.md             # Lo genera /speckit.tasks (no es parte de este comando)
```

### Source Code (repository root)

```text
src/recos_auto/
├── __init__.py
├── common/                    # Compartido con el worker (feature 002)
│   ├── config.py              # Config.from_env: valida y lista TODAS las faltantes; repr sin secretos
│   ├── logs.py                # Logs JSON a stdout; filtra PII; silencia loggers de httpx/pika
│   ├── topology.py            # Declaración idempotente de cola, DLX y DLQ (única fuente de verdad)
│   └── mensajes.py            # MensajeUsuario (pydantic) y message_id determinístico
└── cron/
    ├── __main__.py            # CLI: `run [--date]` y `bootstrap`
    ├── bootstrap.py           # Valida entorno, genera /tmp/crontab, loguea zona y próxima ejecución
    ├── modulo.py              # Módulo del día (alternancia sin estado)
    ├── api_general.py         # Cliente paginado con reintentos y guardas de paginación
    ├── publicador.py          # pika con confirms, mandatory y reconexión
    ├── bloqueo.py             # flock no bloqueante (una corrida a la vez por contenedor)
    └── corrida.py             # Orquestación, contadores, resumen y código de salida

docker/cron/
├── Dockerfile                 # python:3.12-slim + tzdata + Supercronic fijado por checksum; usuario no root
└── entrypoint.sh              # bootstrap -> supercronic como hijo; trap de SIGTERM reenvía la señal al job y a supercronic

tests/
├── unit/                      # modulo, mensaje_id, config, paginación, reintentos, deduplicación, bloqueo
├── contract/                  # schema del mensaje, respuesta de api-general, topología vs Notificaciones
└── integration/               # RabbitMQ real + api-general simulada; arranque del contenedor

docker-compose.yml             # Desarrollo local: rabbitmq + api-general simulada + cron
docker-compose.test.yml        # Solo RabbitMQ para tests de integración
.env.example                   # Variables sin valores reales
pyproject.toml                 # ruff + pytest
requirements.txt / requirements-dev.txt
README.md
```

**Structure Decision**: un único paquete `recos_auto` con `common/` y `cron/`; el worker de la feature 002 agregará `worker/` sin duplicar topología ni mensajes. Se sigue el estilo de Notificaciones (`requirements*.txt`, ruff con línea de 100, pytest con `unit/contract/integration`).

## Complexity Tracking

| Desvío | Por qué hace falta | Alternativa más simple descartada porque |
|---|---|---|
| Binario externo Supercronic | Es el "cron del contenedor" que pidió el equipo: respeta TZ vía `CRON_TZ`, no solapa corridas (el reenvío de SIGTERM al job lo hace el entrypoint: verificado que Supercronic no lo reenvía), hereda variables de entorno y registra códigos de salida. | Un bucle propio en Python o APScheduler obliga a escribir y probar la lógica de agenda y de señales; el cron de Debian purga el entorno y no escribe en stdout. Detalle en `research.md` (D1). |
