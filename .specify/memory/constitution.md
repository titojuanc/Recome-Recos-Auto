# Recome-Recos-Auto Constitution

## Contexto del sistema

RecoMe se compone de repos separados:

- **api-general** (Java/Maven): puerta de entrada única, custodio de los contratos compartidos y dueño de los datos de usuario (nombre, email) y del catálogo (títulos).
- **recomendaciones** (Python): sirve recomendaciones precomputadas. No conoce emails ni títulos. Lo consume api-general.
- **Recome-Notificaciones** (Python + pika): worker que consume mensajes de RabbitMQ y envía mail/push.
- **Recome-Recos-Auto** (este repo): automatiza el envío diario de una recomendación a cada usuario. Se compone de DOS procesos:
  1. **Cron** (contenedor con cron): una vez por día, a las 12:00 (UTC-3), pagina TODOS los usuarios desde api-general (`GET /internal/v1/notification-targets`: `recommendation_id` UUID, `user_id` numérico, `nombre`, `email`, `idioma`) y publica un mensaje por usuario en la cola interna de usuarios.
  2. **Worker** (una sola instancia): consume la cola de usuarios, pide a api-general la recomendación ya con título (`GET /internal/v1/notification-recommendations/{recommendation_id}?module=`), arma el contenido y publica la notificación en la cola de Notificaciones.

Flujo: `Cron -> api-general -> RabbitMQ (recos-auto.usuarios) -> Worker -> api-general (-> recomendaciones + catálogo) -> RabbitMQ (notificaciones) -> Recome-Notificaciones`.

El RabbitMQ es el ya existente del sistema y lo administra el equipo; no se levanta uno propio en producción.

## Core Principles

### I. Responsabilidad acotada (NON-NEGOTIABLE)
Este repo solo orquesta (cron, encolado, consumo, armado del contenido, publicación). NO calcula recomendaciones, NO envía mail/push y NO guarda datos de usuario de forma persistente. El cron solo lista y encola usuarios; el worker solo transforma un usuario en una notificación.

### II. Cero acceso directo a bases de datos y a servicios ajenos no autorizados (NON-NEGOTIABLE)
Este repo habla únicamente con api-general (HTTP) y con RabbitMQ. NO llama directo a la API de recomendaciones (api-general es la puerta de entrada única) y NO lee bases de datos ni Redis de otros módulos.

### III. Contratos externos como fuente de verdad
- **Notificación** (cola de Notificaciones): debe cumplir el schema vigente (`id_mensaje` entero, `canal`, `destinatario` entero, `mail` si canal=`mail`, `contenido{titulo,cuerpo}`). `destinatario` es solo para trazabilidad/logging, no es dato de contacto. El canal por defecto es `mail`.
- **Mensaje de usuario** (cola interna): contiene `recommendation_id` (UUID), `user_id` (numérico), `nombre` y `email`. Contiene datos personales: no se loguean y la cola tiene TTL acotado.
- **Identificadores**: api-general entrega AMBOS ids por usuario; este repo no los traduce ni los deriva. `recommendation_id` se usa para pedir la recomendación; `user_id` va en `destinatario`.
- **Contratos con api-general** (implementados en la rama `feature/recos-auto-usuarios-contacto` de recome-api-general, pendiente de merge): `GET /internal/v1/notification-targets` y `GET /internal/v1/notification-recommendations/{recommendation_id}?module=peliculas|juegos`, ambos con header `X-Internal-API-Key`. El segundo devuelve `item_id`, `module`, `titulo` y `position`, y propaga los códigos 404/412/503 de recomendaciones.
- Un cambio de contrato se propone al repo custodio (api-general); nunca se modifica unilateralmente aquí. Se valida contra el schema ANTES de publicar y no se rellenan campos con valores inventados.

### IV. Ejecución diaria confiable e idempotente (NON-NEGOTIABLE)
- Cron a las 12:00 en UTC-3 (`America/Argentina/Buenos_Aires`), zona horaria explícita y configurable.
- **Alternancia de módulo**: el módulo recomendado alterna día por medio entre `peliculas` y `juegos` (ej.: lunes película, martes juego, miércoles película...). Se calcula de forma determinística a partir de la fecha (UTC-3), sin guardar estado, para que una reejecución del mismo día recomiende el mismo módulo.
- `id_mensaje` determinístico: hash de (usuario, fecha) mapeado a entero, para que Notificaciones descarte duplicados si una corrida se repite.
- Los mensajes de la cola de usuarios que pasen más de 2 horas sin consumirse se descartan (TTL de 2 h) y van a la dead-letter, que los retiene 7 días. Los menores a 2 h se procesan cuando les toque.
- El fallo de un usuario nunca aborta al resto.

### V. Manejo de errores: silencio hacia el usuario, resolución interna (NON-NEGOTIABLE)
- Ante un error NO se envía nada al usuario (ni notificación de error ni contenido parcial); el problema se resuelve internamente.
- El worker reintenta hasta 5 veces con el mecanismo nativo de RabbitMQ (nack/requeue con `x-delivery-limit` = 5); agotados los reintentos, el mensaje va a dead-letter para análisis y reproceso manual.
- Respuestas 404 o 412 (sin recomendación disponible) NO generan notificación y se registran con su motivo. Errores transitorios (503, 502, timeouts) se reintentan.
- Nada se pierde en silencio: todo mensaje termina publicado, en dead-letter, o descartado con registro explícito.

### VI. RabbitMQ: convención de Notificaciones
Colas durables (quorum), mensajes persistentes, `x-delivery-limit`, `x-message-ttl` configurable y dead-letter exchange/cola (`<cola>.dead-letter`), publisher confirms activados. Nombres acordados (todos configurables por variable de entorno):
- Cola de usuarios: `recos-auto.usuarios`, routing key `recos-auto.usuarios`, exchange por defecto.
- Dead-letter de usuarios: `recos-auto.usuarios.dead-letter`.
- Cola de salida: la que consume Notificaciones (`RABBITMQ_QUEUE_NOTIFICACIONES`, por defecto `notificaciones`), publicando con el exchange por defecto y routing key igual al nombre de la cola. A confirmar contra el RabbitMQ real.

### VII. Test-First y Contract Testing (NON-NEGOTIABLE)
Ciclo rojo-verde-refactor. Obligatorios: tests unitarios (paginación, alternancia de módulo, hash de `id_mensaje`, armado de contenido, política de reintentos), contract tests contra el schema de notificación y contra los endpoints de api-general, e integración con RabbitMQ real (Docker) y api-general simulada. El reloj es inyectable para probar el disparo de las 12:00.

### VIII. Observabilidad y seguridad
Logs estructurados con id de corrida y de usuario, sin email ni nombre. Métricas por corrida (usuarios listados, encolados, notificados, sin recomendación, reintentados, en dead-letter, duración) y alerta si la corrida no ocurre o la cola se acumula. Secretos solo por variables de entorno (`.env.example` sin valores reales). Sin endpoints accesibles desde frontends.

### IX. Simplicidad
YAGNI: un cron y un worker Python (pika + cliente HTTP), una instancia de worker, sin frameworks ni servicios adicionales sin justificación escrita. Paralelismo y limitación de velocidad solo si se demuestra necesario.

## Contenido de la notificación

Armado por el worker: `titulo` y `cuerpo` con el título del ítem, el módulo (películas o juegos) y un enlace a la página (aún no existe; configurable mediante plantilla de URL, sin hardcodear). El idioma y el texto exacto se fijan en la spec.

## Stack tecnológico

- Python 3.11+, pika, httpx/requests, pytest, ruff.
- Docker: una imagen para el cron (con cron dentro del contenedor) y una para el worker. Se prevé desplegar en Dokploy, que todavía no está disponible; hasta entonces se ejecuta con docker-compose.
- Configuración operativa obligatoria desde el entorno.

## Flujo de desarrollo

- Spec-Kit: spec, plan, tasks, implementación. Commits pequeños que referencian la tarea.
- Cambios en otros repos van en ramas aparte y se mergean por separado.
- Antes de merge: tests y lint en verde, contract tests pasando, documentación actualizada.
- Idioma: documentación y commits en español; identificadores alineados con los repos hermanos.

## Governance

Esta constitución prevalece sobre otras prácticas del repo. Las enmiendas requieren documentar el motivo, actualizar la versión (semver) y revisar la coherencia con las constituciones de api-general y Notificaciones. Todo PR verifica el cumplimiento de los principios I-IX.

**Version**: 2.3.0 | **Ratified**: 2026-10-05 | **Last Amended**: 2026-10-05
