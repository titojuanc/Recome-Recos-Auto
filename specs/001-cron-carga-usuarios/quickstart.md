# Quickstart: Cron de carga diaria de usuarios

Guía para desarrollar, probar, operar y desplegar el cron. Los comandos de `src/` y `docker/` describen el resultado de implementar este plan (aún no existen: los crea `/speckit.tasks` + `/speckit.implement`).

## 1. Desarrollo local

Requisitos: Python 3.12, Docker con Compose.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # completar API_GENERAL_API_KEY y demás
docker compose -f docker-compose.test.yml up -d    # RabbitMQ (panel en http://localhost:15672, guest/guest)
```

## 2. Pruebas

```bash
pytest tests/unit          # módulo del día, identidad del mensaje, config, paginación, reintentos, bloqueo
pytest tests/contract      # schema del mensaje, respuesta de api-general, topología vs. Notificaciones
pytest tests/integration   # RabbitMQ real + api-general simulada (se saltean si no hay RabbitMQ)
ruff check .
```

Orden de trabajo (Principio VII): escribir el test, verlo fallar, implementar.

## 3. Stack local completo (cron + RabbitMQ + api-general simulada)

```bash
docker compose up --build
```

Levanta RabbitMQ, una api-general simulada con unos usuarios de prueba y el contenedor del cron. Para no esperar a las 12:00:

```bash
docker compose exec cron python -m recos_auto.cron run
```

Verificar en el panel de RabbitMQ (`recos-auto.usuarios`) que hay un mensaje por usuario válido.

Para probar el horario sin esperar, definir `RUN_SCHEDULE="* * * * *"` en el `.env` local (corre cada minuto).

## 4. Verificaciones manuales de la spec

| Quiero comprobar | Cómo |
|---|---|
| Alternancia de módulo | `run --date 2026-10-05`, `--date 2026-10-06`, `--date 2026-10-07` y mirar `modulo` en los mensajes: `peliculas`, `juegos`, `peliculas`. |
| Idempotencia | Correr dos veces la misma fecha y comparar los `message_id` por usuario: son idénticos. |
| Variables faltantes | Quitar `RABBITMQ_URL` y arrancar: termina con código 78 y la lista de faltantes, sin valores. |
| Una corrida a la vez | Lanzar dos `run` simultáneos: el segundo sale con código 75. |
| Sin datos personales en logs | Correr y buscar un email de prueba en la salida (`docker compose logs cron \| grep ana@`): sin resultados. |

## 5. Operación

- **Ver actividad**: logs del contenedor. Buscar el evento `corrida_finalizada` (contadores y resultado) y `bootstrap_ok` (zona y próxima ejecución).
- **Corrida manual / recuperación** (FR-002, FR-003, FR-025): `python -m recos_auto.cron run [--date YYYY-MM-DD]` desde la consola del contenedor. Es seguro repetirla.
- **Si el contenedor estuvo caído a las 12:00**: al volver no recupera la corrida del día. Ver el evento `corrida_omitida_al_arrancar` y lanzar la corrida a mano.
- **Códigos de salida**: ver `contracts/cli.md`.

## 6. Despliegue en Dokploy

> Dokploy todavía no existe en el entorno del equipo. Los pasos describen la configuración que el contenedor necesita; se validarán cuando esté disponible.

1. Crear una aplicación desde este repositorio usando `docker/cron/Dockerfile`, con el repositorio raíz como contexto de build.
2. Cargar las variables de `contracts/entorno.md` en la configuración de la aplicación. Las obligatorias son `API_GENERAL_BASE_URL`, `API_GENERAL_API_KEY` y `RABBITMQ_URL`; las dos últimas son secretos.
3. **No** publicar puertos y **no** montar volúmenes.
4. Fijar **una sola réplica** (el bloqueo de corrida es por contenedor).
5. Subir el tiempo de gracia de parada para que una corrida en curso pueda cerrar ordenadamente (ver `research.md`, D1 y D11).
6. Desplegar y comprobar en los logs que aparece `bootstrap_ok` con la zona `America/Argentina/Buenos_Aires` y la próxima ejecución a las 12:00.
7. Antes del primer día real, lanzar una corrida manual y comprobar los mensajes en `recos-auto.usuarios`.

### Requisitos en otros sistemas

- **api-general**: la rama `feature/recos-auto-usuarios-contacto` debe estar integrada y desplegada, y debe existir una clave de servicio `<entorno>.<secreto>` para el cron.
- **RabbitMQ**: el usuario configurado en `RABBITMQ_URL` debe poder declarar colas y exchanges en su vhost. El nombre `recos-auto.usuarios` se confirma contra el RabbitMQ real antes del primer despliegue.
- **Redespliegue**: un redespliegue que deje dos contenedores vivos a las 12:00 puede duplicar la corrida; la identidad determinística evita el doble envío en el worker.

---

## Probar contra el stack compartido (PruebaVisualModulosNotiyArchivos/e2e-local)

- Levantar: `./start_local.sh` (RabbitMQ 5672/15672, Mailpit 8025, api-general 8080, red
  `recome-e2e-local-net`). Estado: `./status_local.sh`.
- Variables del cron: `RABBITMQ_URL=amqp://guest:guest@localhost:5672/`,
  `API_GENERAL_BASE_URL=http://localhost:8080/api/v1`, `API_GENERAL_API_KEY=e2e-local-shared-service-api-key`
  (header `X-Internal-API-Key`). La rama de api-general con `/internal/v1/notification-targets`
  debe ser la compilada por ese stack.
- Conflicto de puertos: no levantar a la vez `docker-compose.test.yml` de este repo y el stack
  anterior (ambos usan 5672/15672); usar uno u otro, o unir el contenedor del cron a la red
  `recome-e2e-local-net`.
- `PRECONDITION_FAILED` al arrancar = la cola ya existe con otros argumentos; borrarla desde
  http://localhost:15672 o revisar `topology.py`.
- Hasta que exista el worker (feature 002), los mensajes quedan en `recos-auto.usuarios` y se
  ven en la consola de administración.
