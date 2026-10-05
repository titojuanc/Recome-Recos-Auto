# Feature Specification: Worker de recomendaciones automáticas

**Feature Branch**: `002-worker-recomendaciones`
**Created**: 2026-10-05
**Status**: Draft
**Input**: User description: "El worker que lee las solicitudes de notificación (los mensajes de usuario que publica el cron de la feature 001) y se las da a la API de recomendaciones: por cada usuario obtiene su recomendación del día y deja lista la notificación para que Recome-Notificaciones la envíe."

## Clarifications

### Session 2026-10-05

- Q: ¿Qué idiomas soporta el contenido de la notificación? → A: Solo español; se ignora el `idioma` del usuario y las plantillas son configurables por variable de entorno.
- Q: ¿Qué hace el worker con un mensaje viejo? → A: Nada extra; procesa todo lo que le llega de la cola y el TTL de 2 h es la única barrera de antigüedad.
- Q: ¿Quién garantiza una sola notificación por usuario y día? → A: Solo el `id_mensaje` determinístico; el worker no guarda estado y Notificaciones deduplica.
- Q: ¿Cómo se toman los mensajes de la cola? → A: Procesamiento concurrente con un número de hilos configurable dentro de la única instancia (no se agregan instancias).
- Q: ¿Cómo se protege el worker de una caída sostenida de api-general? → A: Interruptor de corte: tras N fallos transitorios seguidos pausa el consumo con espera creciente y reanuda; mientras está pausado los mensajes no gastan reintentos.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Convertir un usuario encolado en una notificación (Priority: P1)

Una única instancia del worker toma los mensajes de la cola de usuarios, varios en paralelo según su concurrencia configurada. Por cada uno pide la recomendación del usuario para el módulo del día (película o juego), arma el título y el cuerpo de la notificación y la deja en la cola de Notificaciones, por mail, con una identidad estable.

**Why this priority**: Es la razón de ser del módulo. Sin esto, el cron encola usuarios que nunca reciben nada.

**Independent Test**: Con una api-general simulada que devuelve una recomendación con título, un RabbitMQ real de pruebas y N mensajes de usuario en la cola, arrancar el worker y verificar que la cola de Notificaciones contiene exactamente N notificaciones válidas, una por usuario, y que la cola de usuarios queda vacía.

**Acceptance Scenarios**:

1. **Given** un mensaje de usuario válido con módulo `peliculas`, **When** el worker lo procesa y la recomendación existe, **Then** se publica una notificación de canal `mail` con el email del usuario, el id del usuario como destinatario, y un contenido (título y cuerpo) que menciona el título recomendado y que es una película.
2. **Given** un mensaje con módulo `juegos`, **When** se procesa, **Then** el contenido habla de un juego y no de una película.
3. **Given** un mensaje procesado con éxito, **When** la notificación queda publicada y confirmada por RabbitMQ, **Then** el mensaje de usuario se da por consumido y no vuelve a la cola.
4. **Given** el mismo mensaje de usuario (misma identidad) procesado dos veces, **When** se publica la notificación, **Then** ambas llevan el mismo `id_mensaje`, de modo que Notificaciones descarte la repetida.

---

### User Story 2 - Fallos sin notificar al usuario (Priority: P1)

Si algo falla, el usuario no recibe nada (ni error ni contenido parcial). Los fallos transitorios se reintentan; los definitivos se apartan para análisis; los casos "sin recomendación" se registran con su motivo.

**Why this priority**: Enviar un contenido a medias o un mensaje de error es peor que no enviar. Es una regla no negociable del proyecto.

**Independent Test**: Con la api-general simulada forzando 404, 412, 503 y timeouts, verificar el destino de cada mensaje y que la cola de Notificaciones no recibe nada en ninguno de esos casos.

**Acceptance Scenarios**:

1. **Given** la api-general responde 404 o 412 (el usuario no tiene recomendación disponible), **When** se procesa el mensaje, **Then** no se publica ninguna notificación, se registra el motivo y el mensaje se descarta como resuelto (no se reintenta).
2. **Given** la api-general responde 502/503, timeout o error de red, **When** se procesa el mensaje, **Then** el mensaje vuelve a la cola y se reintenta; tras 5 reintentos fallidos va a la dead-letter.
3. **Given** el mensaje es inválido (no cumple el contrato de la cola de usuarios), **When** el worker lo lee, **Then** no se reintenta, va a la dead-letter y se registra el motivo sin datos personales.
4. **Given** falla la publicación en la cola de Notificaciones (sin ruta, sin confirmación), **When** ocurre, **Then** el mensaje de usuario se reintenta como cualquier fallo transitorio y nunca se da por consumido sin notificación publicada.

---

### User Story 3 - Procesar a todos dentro de la ventana de 2 horas (Priority: P2)

Los mensajes vencen a las 2 horas en la cola de usuarios. El worker debe vaciar la cola de una corrida completa antes de ese plazo, con una sola instancia.

**Why this priority**: Si no alcanza el ritmo, los últimos usuarios de cada corrida no reciben nada (SC-009 de la feature 001). Es la verificación pendiente de esa feature.

**Independent Test**: Encolar 10 000 mensajes con una api-general simulada de latencia realista y medir el tiempo hasta vaciar la cola.

**Acceptance Scenarios**:

1. **Given** 10 000 mensajes en cola, **When** el worker trabaja de forma continua, **Then** todos se procesan en menos de 2 horas desde su publicación.
2. **Given** un mensaje que ya venció, **When** llega a la dead-letter, **Then** el worker no lo procesa ni lo vuelve a encolar; queda a análisis manual.

---

### User Story 4 - Operación, apagado ordenado y observabilidad (Priority: P2)

Quien opera el sistema puede desplegar el worker como contenedor, detenerlo sin perder ni duplicar trabajo, y entender qué pasó con cada usuario a partir de logs y métricas sin datos personales.

**Why this priority**: Sin esto no se puede operar ni auditar en producción.

**Independent Test**: Arrancar el contenedor con variables válidas e inválidas, enviarle SIGTERM durante el procesamiento y revisar los logs.

**Acceptance Scenarios**:

1. **Given** faltan variables obligatorias, **When** arranca, **Then** termina con código de error de configuración y un mensaje que nombra las variables faltantes, sin mostrar valores.
2. **Given** recibe SIGTERM procesando un mensaje, **When** termina, **Then** completa o devuelve ese mensaje, no toma otro y sale limpiamente.
3. **Given** el worker procesó mensajes, **When** se revisan los logs, **Then** hay un resumen con contadores (recibidos, notificados, sin recomendación, reintentados, a dead-letter) y ninguna línea contiene email, nombre ni credenciales.
4. **Given** el RabbitMQ o la api-general no están disponibles al arrancar o se caen durante la ejecución, **When** vuelven, **Then** el worker se reconecta solo y continúa.

---

### Edge Cases

- Mensaje consumido cerca de las 2 h de su publicación: se procesa igual; la única barrera de antigüedad es el TTL de la cola (el worker no compara fechas ni edades).
- Mensaje con módulo o versión desconocidos: se trata como inválido (dead-letter, sin reintento).
- Usuario con cualquier `idioma` (o sin él): el contenido es siempre en español.
- La recomendación llega sin título o con título vacío: no se envía nada; se trata como "sin recomendación" con ese motivo.
- Título con caracteres especiales, muy largo o con marcado: se normaliza y trunca de forma segura en el contenido.
- Mensaje duplicado en la cola (por reejecución del cron): se procesa y publica con el mismo `id_mensaje`; Notificaciones lo descarta.
- La cola de Notificaciones no existe todavía: no se declara desde este módulo; el publicar falla visiblemente y se reintenta.
- El mensaje se publicó en Notificaciones pero el worker cae antes de confirmar el consumo: al reiniciar se reprocesa y la repetición se neutraliza por `id_mensaje`.
- El mismo email repetido para usuarios distintos: se trata cada mensaje por separado; no se deduplica por email.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST consumir la cola de usuarios `recos-auto.usuarios` con una única instancia, procesando varios mensajes en paralelo con un número de hilos configurable (`WORKER_CONCURRENCY`, mínimo 1). No se garantiza el orden entre mensajes.
- **FR-002**: El sistema MUST validar cada mensaje contra el contrato de mensaje de usuario v1 (feature 001) antes de usarlo; los inválidos no se procesan.
- **FR-003**: El sistema MUST obtener la recomendación del usuario y el módulo del mensaje a través de api-general (nunca llamando directo al servicio de recomendaciones ni a otras fuentes), autenticándose con la clave interna.
- **FR-004**: El sistema MUST publicar la notificación en la cola de Notificaciones cumpliendo su contrato vigente: `id_mensaje` entero positivo, `canal` = `mail`, `destinatario` = id numérico del usuario, `mail` = email del usuario y `contenido` con `titulo` y `cuerpo`.
- **FR-005**: El sistema MUST derivar `id_mensaje` de forma determinística a partir de la identidad del mensaje de usuario (usuario, fecha, módulo), de modo que el mismo usuario, día y módulo produzca siempre el mismo valor, y que usuarios o días distintos produzcan valores distintos.
- **FR-006**: El sistema MUST armar `titulo` y `cuerpo` con el título del ítem recomendado, el módulo (película o juego) y un enlace a la página, construido con una plantilla de URL configurable (sin valor fijo en el código). El texto se redacta solo en español y las plantillas de título y cuerpo son configurables por variable de entorno; el `idioma` del usuario se ignora.
- **FR-007**: El sistema MUST dar por consumido un mensaje de usuario solo después de que RabbitMQ confirme la publicación de su notificación, o después de resolverlo sin notificación (sin recomendación, o enviado a dead-letter).
- **FR-008**: El sistema MUST NOT enviar nada al usuario ante ningún error (ni notificación de error ni contenido parcial).
- **FR-009**: Ante 404 o 412 de la recomendación, el sistema MUST NOT publicar notificación, registrar el motivo y dar el mensaje por resuelto sin reintentos.
- **FR-010**: Ante errores transitorios (502, 503, timeouts, errores de red, fallo de publicación), el sistema MUST devolver el mensaje a la cola para reintentarlo, hasta 5 reintentos con el mecanismo nativo de RabbitMQ; agotados, el mensaje va a la dead-letter.
- **FR-011**: Los mensajes inválidos MUST ir directamente a la dead-letter sin reintentos, con el motivo registrado.
- **FR-012**: El sistema MUST declarar la cola de usuarios y su dead-letter reutilizando la misma definición de topología que el cron, con los mismos argumentos (incluidos TTL de 2 h y 7 días); un test de contrato verifica la coincidencia. MUST NOT declarar la cola de Notificaciones, que pertenece a Recome-Notificaciones.
- **FR-013**: El sistema MUST publicar las notificaciones con persistencia, confirmaciones del broker y detección de mensajes sin ruta.
- **FR-014**: El sistema MUST NOT persistir datos de usuario (email, nombre) más allá del mensaje en curso.
- **FR-022**: La unicidad de la notificación por usuario, día y módulo MUST garantizarse únicamente mediante el `id_mensaje` determinístico: el worker no guarda estado de notificaciones previas ni consulta a Notificaciones.
- **FR-023**: Con concurrencia, cada mensaje MUST confirmarse, reintentarse o enviarse a dead-letter de forma independiente; el fallo de uno no afecta a los demás en curso, y el apagado ordenado espera a todos los mensajes en curso.
- **FR-024**: Tras un número configurable de fallos transitorios consecutivos de api-general o de publicación, el sistema MUST pausar el consumo con espera creciente (acotada y configurable) y reanudarlo al recuperarse. Mientras está pausado, no toma mensajes de la cola, de modo que no consumen sus reintentos; los mensajes en curso al abrirse el corte se devuelven a la cola. La pausa se registra en los logs.
- **FR-015**: El sistema MUST tolerar caídas de RabbitMQ y de api-general reconectándose con espera creciente, sin perder mensajes ni terminar.
- **FR-016**: El sistema MUST aplicar un tiempo máximo a cada llamada a api-general y a cada publicación, de modo que un mensaje no bloquee indefinidamente al worker.
- **FR-017**: El sistema MUST atender SIGTERM/SIGINT de forma ordenada: terminar o devolver el mensaje en curso, no tomar otro, cerrar conexiones y salir.
- **FR-018**: El sistema MUST registrar logs estructurados con id de mensaje y de corrida, sin email, nombre ni credenciales, y emitir periódicamente y al apagarse un resumen con contadores (recibidos, notificados, sin recomendación, reintentados, a dead-letter, duración).
- **FR-019**: Toda la configuración (URLs, claves, nombres de colas, plantilla de URL de la página, tiempos, reintentos) MUST venir de variables de entorno; faltantes o inválidas → arranque abortado con código de salida de configuración y mensaje que nombra las variables sin revelar valores. Se provee un archivo de ejemplo sin valores reales.
- **FR-020**: El sistema MUST empaquetarse como imagen de contenedor propia (separada de la del cron) y poder ejecutarse junto al RabbitMQ y a una api-general simulada con docker-compose.
- **FR-021**: El sistema MUST NOT descartar silenciosamente ningún mensaje: todo mensaje termina con notificación publicada, en dead-letter o resuelto con registro explícito del motivo.

### Key Entities

- **Mensaje de usuario**: entrada, publicada por el cron (feature 001). Contiene identificador de mensaje, corrida, fecha, módulo, identificadores del usuario, nombre, email e idioma opcional. Contiene datos personales.
- **Recomendación**: lo que api-general devuelve para un usuario y módulo: ítem, módulo, título y posición. Es el contenido a recomendar.
- **Notificación**: salida hacia Notificaciones: identificador entero estable, canal, destinatario, email y contenido (título y cuerpo).
- **Resultado de procesamiento**: estado final de cada mensaje (notificado, sin recomendación, reintentado, a dead-letter) usado para logs y contadores.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El 100 % de los mensajes válidos con recomendación disponible termina como exactamente una notificación publicada en la cola de Notificaciones (0 faltantes y 0 duplicados con identidad distinta).
- **SC-002**: Reprocesar el mismo mensaje de usuario produce siempre el mismo identificador de notificación (0 identidades distintas).
- **SC-003**: Ante cualquier error, 0 notificaciones de error o parciales llegan a la cola de Notificaciones.
- **SC-004**: Los fallos transitorios simulados se reintentan hasta 5 veces y luego van a dead-letter; el 100 % de los mensajes termina en un estado final registrado.
- **SC-005**: 10 000 mensajes se procesan en menos de 2 horas con una sola instancia (cumple SC-009 de la feature 001).
- **SC-006**: Un SIGTERM detiene el worker en menos de 30 segundos sin pérdida ni duplicación de notificaciones.
- **SC-007**: 0 líneas de log contienen emails, nombres o credenciales, verificado con una corrida completa.
- **SC-008**: Tras una caída y recuperación de RabbitMQ o api-general, el worker vuelve a procesar sin intervención manual.
- **SC-009**: Con api-general caída durante 10 minutos, 0 mensajes llegan a la dead-letter por ese motivo; el consumo se reanuda solo al recuperarse.

## Assumptions

- La API de recomendaciones se consume **a través de api-general** (endpoint de recomendación para notificaciones con título), por mandato de la constitución: api-general es la puerta de entrada única. El worker no llama directo al servicio de recomendaciones.
- El endpoint de api-general está implementado en la rama `feature/recos-auto-usuarios-contacto`, aún sin mergear; hasta entonces se prueba con una api-general simulada.
- El canal es siempre `mail`; push queda fuera de alcance.
- El contenido es solo en español; el texto exacto de título y cuerpo se fija en la planificación y es configurable por variable de entorno.
- La página de destino aún no existe: el enlace se construye con una plantilla de URL configurable y puede quedar con un valor provisional.
- Una sola instancia de worker con concurrencia interna configurable (`WORKER_CONCURRENCY`); no se agregan instancias. El valor por defecto y el modelo de concurrencia se fijan en la planificación. Esto relaja el principio IX de la constitución ("paralelismo solo si se demuestra necesario"), que debe enmendarse en la planificación.
- La cola de Notificaciones ya existe y la administra su equipo; el nombre por defecto es `notificaciones` y se confirmará contra el RabbitMQ real.
- RabbitMQ 3.10 o superior (colas quorum con límite de entregas).
- No existe preferencia de baja: si api-general la agrega, filtra antes del cron.
- Fuera de alcance: el cron, el envío efectivo de mail/push, el cálculo de recomendaciones, y cambios de contrato en api-general o Notificaciones (se proponen al repo custodio).
- Dependencias: feature 001 (contrato del mensaje de usuario y topología compartida), api-general, RabbitMQ y Recome-Notificaciones.
