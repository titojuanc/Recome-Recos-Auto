# Implementation Plan: Worker de recomendaciones automáticas

**Branch**: `002-worker-recomendaciones` | **Date**: 2026-10-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-worker-recomendaciones/spec.md`

## Summary

Un contenedor con un proceso Python de larga duración (`python -m recos_auto.worker`) que consume la cola `recos-auto.usuarios` y, por cada mensaje de usuario (contrato v1 de la feature 001):

1. valida el mensaje;
2. pide a api-general la recomendación (`GET /internal/v1/notification-recommendations/{recommendation_id}?module=`), que ya devuelve el título;
3. arma la notificación (`id_mensaje` determinístico de 63 bits, canal `mail`, título y cuerpo en español desde plantillas configurables);
4. la publica en la cola de Notificaciones (sin declararla, `mandatory`, confirms, persistente);
5. confirma (`ack`) el mensaje de usuario solo después del confirm del broker, o lo resuelve sin notificar (404/412 → `ack` con motivo; inválido → dead-letter; transitorio → `nack` con requeue hasta el límite de 5).

La concurrencia es de **N hilos** (`WORKER_CONCURRENCY`, por defecto 4), cada uno con su **propia conexión y canal** (pika no es thread-safe) y `prefetch=1`. Un **interruptor de corte** compartido pausa el consumo ante fallos transitorios sostenidos, reteniendo los mensajes sin confirmar para no gastar sus reintentos. Sin estado persistente.

## Technical Context

**Language/Version**: Python 3.12 (igual que el cron; compatible con 3.11+)
**Primary Dependencies**: `pika` 1.4.x (consumo y publicación, un hilo = una conexión), `httpx` (cliente de api-general, un cliente por hilo), `pydantic[email]` (validación del mensaje de usuario y de la notificación). Sin dependencias nuevas respecto a la feature 001.
**Storage**: N/A. Sin base de datos, sin volúmenes, sin archivos.
**Testing**: pytest + pytest-mock; `httpx.MockTransport`; RabbitMQ real vía `docker-compose.test.yml` (se saltea si no hay broker); ruff.
**Target Platform**: Contenedor Linux (amd64/arm64), Dokploy a futuro; docker compose hoy.
**Project Type**: Servicio de larga duración (consumidor), una sola réplica.
**Performance Goals**: 10 000 mensajes en < 2 h (SC-005): presupuesto de 0,72 s por mensaje en serie; con 4 hilos, ~2,9 s por mensaje por hilo.
**Constraints**: sin puertos ni endpoints; logs a stdout sin PII; cierre ordenado ante SIGTERM en < 30 s; una sola réplica.
**Scale/Scope**: decenas de miles de mensajes por día, en una ráfaga diaria.

## Constitution Check

*GATE: debe pasar antes de la investigación (Fase 0). Re-verificado tras el diseño (Fase 1).*

| Principio | Estado | Cómo se cumple |
|---|---|---|
| I. Responsabilidad acotada | PASS | Solo transforma un usuario en una notificación. No calcula recomendaciones, no envía mail/push, no persiste datos. |
| II. Solo api-general y RabbitMQ | PASS | Un cliente HTTP (a api-general) y pika. El "API de recomendaciones" se consume por api-general, nunca directo. |
| III. Contratos externos | PASS | Entrada validada con el schema `mensaje-usuario` de la feature 001; salida validada con un modelo espejo del contrato de Notificaciones (`extra=forbid`) antes de publicar; el contrato de api-general se documenta como copia derivada. |
| IV. Ejecución diaria idempotente | PASS | `id_mensaje` = entero de 63 bits derivado del `message_id` (UUIDv5); reprocesar produce el mismo valor. |
| V. Errores sin avisar al usuario | PASS | Ningún camino de error publica nada. 404/412 se registran; transitorios se reintentan; agotados van a dead-letter. |
| VI. Convención RabbitMQ | PASS | Topología de usuarios desde `common/topology.py`; no declara la cola de Notificaciones; confirms y persistencia. |
| VII. Test-first y contract testing | PASS | Ver "Estrategia de pruebas". |
| VIII. Observabilidad y seguridad | PASS con nota | Logs estructurados y resumen con contadores. Sin `/metrics` (sin puertos). |
| IX. Simplicidad | **VIOLACIÓN JUSTIFICADA** | Concurrencia interna con N hilos (decisión de clarificación 4). Ver Complexity Tracking; el principio IX ya fue enmendado (constitución v2.4.0). |

## Project Structure

### Documentation (this feature)

```text
specs/002-worker-recomendaciones/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── api-general-notification-recommendation.md  # contrato consumido (copia derivada)
│   ├── mensaje-notificacion.schema.json            # contrato producido (espejo del de Notificaciones)
│   └── entorno.md                                  # variables de entorno
└── tasks.md                                        # lo genera /speckit.tasks
```

### Source Code (repository root)

```text
src/recos_auto/
├── common/                  # EXISTENTE: se reutiliza
│   ├── topology.py          # cambio mínimo: acepta cualquier config con los atributos de cola (Protocol)
│   ├── mensajes.py          # MensajeUsuario (validación de entrada)
│   └── logs.py
└── worker/                  # NUEVO
    ├── __main__.py          # arranque, señales, hilos, código de salida
    ├── config.py            # ConfigWorker.from_env (valida y lista variables faltantes)
    ├── consumidor.py        # bucle por hilo: conexión propia, prefetch 1, ack/nack
    ├── procesador.py        # lógica pura: mensaje -> Resultado (sin pika)
    ├── recomendaciones.py   # cliente de api-general (sin reintentos propios)
    ├── notificacion.py      # id_mensaje, modelo y armado del contenido
    ├── publicador.py        # publicación a Notificaciones (mandatory + confirms)
    ├── interruptor.py       # interruptor de corte compartido entre hilos
    └── contadores.py        # contadores con lock y resumen periódico
docker/worker/
├── Dockerfile               # python:3.12-slim, usuario no root
docker-compose.yml           # se agrega el servicio `worker` y un mock de Notificaciones
tests/
├── unit/                    # procesador, notificacion, interruptor, config, recomendaciones
├── contract/                # notificación vs schema, topología compartida vs cron, api-general
└── integration/             # RabbitMQ real + api simulada: flujo, fallos, corte, SIGTERM, 10k
```

**Structure Decision**: mismo repo y mismo paquete `recos_auto`, con `worker/` separado de `cron/` y `common/` compartido (como anticipó la feature 001). La lógica de decisión (`procesador.py`) no conoce pika, lo que permite probarla sin broker.

## Estrategia de pruebas (Principio VII)

- **Unit**: `id_mensaje` (determinismo, rango positivo de 63 bits, distintos para distintos usuarios/fechas/módulos); armado de contenido (título con caracteres raros, truncado); clasificación de errores (404/412 → resuelto; 5xx/timeout/red → transitorio; 400/401/403 → fallo de configuración); interruptor (apertura, espera creciente, cierre); config.
- **Contract**: notificación publicada válida contra `mensaje-notificacion.schema.json`; `ConfigWorker` produce los mismos argumentos de cola que el cron (`topology`); respuesta de api-general contra el contrato.
- **Integración** (RabbitMQ real + api simulada): flujo completo N mensajes → N notificaciones; 404/412 sin notificación; 503 → reintentos → dead-letter tras 5; mensaje inválido directo a dead-letter; corte de api-general 10 min simulados (SC-009, con tiempos reducidos); SIGTERM; reconexión; 10 000 mensajes (marcada `lento`).

## Complexity Tracking

| Violación | Por qué se necesita | Alternativa más simple descartada porque |
|---|---|---|
| Concurrencia interna de N hilos (Principio IX) | Decisión del usuario en clarificación 4; da margen para cumplir SC-005 si api-general responde lento. | Procesamiento secuencial: alcanza solo si cada llamada tarda < 0,7 s, sin margen ante picos. Se mantiene `WORKER_CONCURRENCY=1` como valor válido para volver a secuencial. |
| Interruptor de corte (clarificación 5) | Con reintentos inmediatos de RabbitMQ, una caída corta agotaría los 5 reintentos de cientos de mensajes. | Reintentos con espera por mensaje: bloquea hilos y no protege a la api caída de más carga. |
