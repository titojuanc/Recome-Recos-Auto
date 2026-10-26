# Quickstart: validar el worker

Prerrequisitos: Docker, `.venv` con `requirements-dev.txt` (ver README).

## 1. Pruebas
```bash
docker compose -f docker-compose.test.yml up -d --wait
.venv/bin/python -m pytest -q                      # unit + contract + integración
.venv/bin/python -m pytest -q -m lento tests/integration/test_worker_rendimiento.py
docker compose -f docker-compose.test.yml down
```
Esperado: todo en verde; el test de rendimiento procesa 10 000 mensajes en < 2 h (con la api simulada, en segundos).

## 2. Flujo completo local
```bash
docker compose up --build        # rabbitmq + mock-api + cron + worker
docker compose exec cron python -m recos_auto.cron run
docker compose logs -f worker
```
Esperado: el cron encola 25 usuarios; el worker registra 25 `notificado` y el resumen `recibidos=25 notificados=25`. La cola `notificaciones` (declarada por el entorno de prueba) contiene 25 mensajes válidos según [contracts/mensaje-notificacion.schema.json](./contracts/mensaje-notificacion.schema.json).

## 3. Fallos
- Parar `mock-api` 1 minuto con mensajes en cola: el worker registra `corte_abierto`, no manda mensajes a dead-letter; al volver registra `corte_cerrado` y retoma.
- `docker compose stop worker`: termina en < 30 s con el resumen final.
- Quitar `API_GENERAL_API_KEY`: el contenedor sale con 78 y nombra la variable.

Variables: [contracts/entorno.md](./contracts/entorno.md). Modelo: [data-model.md](./data-model.md).
