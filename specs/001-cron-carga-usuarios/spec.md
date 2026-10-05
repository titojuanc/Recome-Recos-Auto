# Feature Specification: Cron de carga diaria de usuarios

**Feature Branch**: `001-cron-carga-usuarios`
**Created**: 2026-10-05
**Status**: Draft
**Input**: User description: "Un cron, en un contenedor apto para Dokploy, que cada día a las 12:00 (UTC-3) pide a api-general todos los usuarios (id, nombre, mail), y los encola uno por uno en el RabbitMQ existente para que otro worker los procese."

## Clarifications

### Session 2026-10-05

- Q: ¿Se encola a todos los usuarios o se respeta una preferencia de baja? → A: Hoy no existe preferencia de baja; se encola a todos los usuarios con email y queda como supuesto explícito y fuera de alcance.
- Q: ¿Qué pasa con los mensajes que quedan mucho tiempo en la cola? → A: Si pasan más de 2 horas en la cola, se descartan (TTL de 2 h; van a la dead-letter). Revierte la decisión anterior de no descartar por antigüedad.
- Q: ¿Qué pasa con los mensajes de la dead-letter? → A: La dead-letter también tiene TTL (7 días) y se vacía sola.
- Q: ¿Cuándo se fijan la fecha y el módulo de una corrida? → A: Una sola vez al iniciar la corrida (UTC-3); no cambian aunque cruce la medianoche.
- Q: ¿Cómo se entera alguien de que una corrida falló o no corrió? → A: Solo por logs y código de salida, con revisión manual; la alerta automática queda para cuando exista Dokploy.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Encolar a todos los usuarios cada día a las 12:00 (Priority: P1)

Todos los días a las 12:00 (UTC-3) el sistema obtiene la lista completa de usuarios con email desde api-general y publica un mensaje por usuario en la cola de usuarios de RabbitMQ, indicando además qué módulo (películas o juegos) corresponde recomendar ese día. Un worker posterior (otra feature) consume esos mensajes.

**Why this priority**: Es el disparador de todo el flujo de recomendaciones automáticas. Sin esta pieza no se genera ninguna notificación.

**Independent Test**: Con una api-general simulada que devuelve N usuarios en varias páginas y un RabbitMQ real de pruebas, ejecutar una corrida y verificar que la cola contiene exactamente N mensajes válidos, uno por usuario, sin necesidad de que exista el worker.

**Acceptance Scenarios**:

1. **Given** api-general devuelve 250 usuarios en 3 páginas, **When** se ejecuta una corrida, **Then** la cola de usuarios recibe 250 mensajes, cada uno con `recommendation_id`, `user_id`, `nombre`, `email`, la fecha de corrida y el módulo del día.
2. **Given** el reloj marca las 12:00 en UTC-3, **When** el contenedor está en ejecución, **Then** la corrida se dispara automáticamente una vez, sin intervención manual.
3. **Given** el servidor del contenedor está en UTC, **When** llega la hora, **Then** la corrida se dispara a las 12:00 de UTC-3 (15:00 UTC) y no a las 12:00 UTC.
4. **Given** api-general no tiene usuarios, **When** se ejecuta una corrida, **Then** no se publica ningún mensaje y la corrida termina correctamente registrando 0 usuarios.

---

### User Story 2 - Alternar el módulo recomendado día por medio (Priority: P1)

El mensaje de cada usuario incluye el módulo a recomendar ese día. El módulo alterna día por medio: un día `peliculas`, al siguiente `juegos`, y así sucesivamente. Todos los usuarios de una misma corrida reciben el mismo módulo.

**Why this priority**: El worker pide la recomendación según este módulo. Sin él no se puede pedir la recomendación correcta.

**Independent Test**: Calcular el módulo para una serie de fechas consecutivas y verificar la alternancia; repetir la misma fecha y verificar que da el mismo resultado.

**Acceptance Scenarios**:

1. **Given** una fecha de referencia configurada como día de `peliculas`, **When** se calcula el módulo para ese día, el siguiente y el subsiguiente, **Then** resulta `peliculas`, `juegos`, `peliculas`.
2. **Given** una corrida ya realizada hoy, **When** se vuelve a ejecutar el mismo día, **Then** el módulo es el mismo que en la primera corrida.
3. **Given** un cambio de mes o de año (por ejemplo 31/12 a 1/1), **When** se calcula el módulo, **Then** la alternancia continúa sin saltos ni repeticiones.

---

### User Story 3 - Soportar fallos sin perder ni duplicar trabajo (Priority: P2)

Si api-general o RabbitMQ fallan durante una corrida, el cron reintenta de forma acotada. Si no logra completar, termina con error visible y se puede relanzar manualmente sin que los usuarios ya encolados reciban doble recomendación.

**Why this priority**: Es crítico para la confiabilidad, pero el flujo feliz (P1) entrega el valor principal.

**Independent Test**: Simular que api-general falla en la página 2, y por separado que RabbitMQ no confirma una publicación; verificar los reintentos, el resultado final y que relanzar la corrida no genera mensajes con identidad distinta para los mismos usuarios y fecha.

**Acceptance Scenarios**:

1. **Given** api-general responde con error temporal en una página, **When** el reintento tiene éxito, **Then** la corrida continúa y termina completa sin duplicar los mensajes de páginas anteriores.
2. **Given** api-general sigue fallando tras agotar los reintentos, **When** termina la corrida, **Then** el proceso finaliza con error, registra cuántos usuarios se alcanzaron a encolar y no envía nada a los usuarios.
3. **Given** RabbitMQ no confirma la recepción de un mensaje, **When** se agotan los reintentos para ese mensaje, **Then** se registra como fallido (sin datos personales) y el resumen de la corrida lo cuenta.
4. **Given** una corrida ya completó para la fecha de hoy, **When** se relanza manualmente, **Then** los mensajes publicados tienen la misma identidad (usuario + fecha + módulo) que los de la primera corrida, de modo que el consumidor pueda descartar duplicados.
5. **Given** una corrida ya está en ejecución, **When** se dispara otra al mismo tiempo, **Then** la segunda no se ejecuta y lo registra.

---

### User Story 4 - Desplegar y operar en Dokploy (Priority: P2)

Quien opera el sistema puede desplegar el cron como contenedor en Dokploy usando solo variables de entorno, ver su actividad en los logs del contenedor y lanzar una corrida manual cuando haga falta (para probar o recuperar una corrida perdida).

**Why this priority**: Sin un despliegue operable el cron no llega a producción, pero depende de que la lógica (P1) exista.

**Independent Test**: Construir la imagen, iniciarla con solo variables de entorno y verificar que arranca, que registra su próxima ejecución programada, que una corrida manual funciona y que falla de inmediato y con mensaje claro si falta una variable obligatoria.

**Acceptance Scenarios**:

1. **Given** la imagen y un conjunto completo de variables de entorno, **When** se inicia el contenedor, **Then** queda activo, registra su zona horaria y la próxima ejecución, y no requiere volúmenes ni archivos adicionales.
2. **Given** falta una variable obligatoria, **When** se inicia el contenedor, **Then** termina inmediatamente indicando cuál falta, sin imprimir valores secretos.
3. **Given** el contenedor está activo, **When** el operador ejecuta el comando de corrida manual, **Then** se realiza una corrida completa y se registra su resumen.
4. **Given** el contenedor se reinicia (por un nuevo despliegue), **When** vuelve a estar activo, **Then** retoma la programación diaria desde la siguiente 12:00 sin ejecutar corridas duplicadas ni recuperar automáticamente la corrida perdida.

---

### Edge Cases

- Una corrida tarda tanto que se acerca la hora de la siguiente: no se solapan (FR-011).
- api-general devuelve un `next_page_token` repetido o inválido, o se supera el tope de páginas: la corrida termina sin bucle infinito y con error claro. Una página sin usuarios válidos pero con un token nuevo es legítima y la corrida continúa.
- api-general devuelve un usuario sin `email` o sin `recommendation_id`: se omite, se cuenta y se registra sin datos personales; no aborta la corrida.
- api-general devuelve el mismo usuario en dos páginas: se publica un solo mensaje por usuario en la corrida.
- RabbitMQ no está disponible al iniciar la corrida: la corrida falla con error claro tras los reintentos.
- La cola ya tiene mensajes sin consumir: se siguen agregando; los que superen 2 horas se descartan y van a la dead-letter. Si el worker no logra procesar a todos en 2 horas, los últimos de la corrida vencen sin enviarse.
- Zona horaria del servidor distinta de UTC-3: la hora de disparo y la fecha de corrida se calculan en UTC-3 de forma explícita.
- Un nombre con caracteres especiales (acentos, emojis) viaja sin corromperse.

## Requirements *(mandatory)*

### Functional Requirements

**Programación**

- **FR-001**: El sistema MUST disparar una corrida automáticamente todos los días a las 12:00 en UTC-3 (`America/Argentina/Buenos_Aires`), con la zona horaria definida de forma explícita y configurable, sin depender de la zona del servidor.
- **FR-002**: El sistema MUST permitir lanzar una corrida manual mediante un comando, con las mismas reglas que una corrida programada.
- **FR-003**: El lanzamiento manual MUST permitir indicar la fecha de corrida (para pruebas y recuperación); por defecto usa la fecha actual en UTC-3.
- **FR-011**: El sistema MUST impedir que dos corridas se ejecuten al mismo tiempo; la segunda no se ejecuta y se registra el motivo.

**Obtención de usuarios**

- **FR-004**: El sistema MUST obtener los usuarios desde api-general paginando hasta recorrer TODOS (`GET /internal/v1/notification-targets` con `page_size` y `page_token`), autenticándose con la clave de servicio configurada.
- **FR-005**: El sistema MUST reintentar de forma acotada una página fallida por errores transitorios (red, timeouts, 5xx) antes de abandonar la corrida, y MUST NOT reintentar errores no transitorios (por ejemplo 401 o 403): falla de inmediato con error claro.
- **FR-006**: El sistema MUST omitir, contando y registrando sin datos personales, a todo usuario recibido sin `recommendation_id`, `user_id` o `email`, o con un `email` mal formado.
- **FR-007**: El sistema MUST publicar como máximo un mensaje por usuario por corrida, aunque api-general lo devuelva repetido.

**Mensaje a la cola de usuarios**

- **FR-008**: El sistema MUST publicar un mensaje por usuario con: `recommendation_id` (UUID), `user_id` (numérico), `nombre`, `email`, `fecha` de corrida (en UTC-3), `modulo` (`peliculas` o `juegos`) e identificador de corrida. Incluye `idioma` cuando api-general lo informa.
- **FR-009**: El sistema MUST determinar el módulo de forma determinística a partir de la fecha de corrida, alternando día por medio entre `peliculas` y `juegos` desde una fecha de referencia configurable, sin guardar estado entre corridas. Todos los mensajes de una corrida MUST llevar el mismo módulo: la fecha de corrida (UTC-3) y el módulo se fijan una sola vez al iniciar la corrida y no cambian aunque la corrida cruce la medianoche.
- **FR-010**: El sistema MUST publicar los mensajes de forma persistente y con confirmación de recepción del broker, reintentando de forma acotada los no confirmados y contando los que fallen definitivamente.
- **FR-012**: Los mensajes de una misma combinación (usuario, fecha, módulo) MUST tener la misma identidad entre corridas y reejecuciones, para que el consumidor pueda detectar duplicados.
- **FR-013**: El sistema MUST declarar de forma idempotente la cola de usuarios (`recos-auto.usuarios`) y su dead-letter (`recos-auto.usuarios.dead-letter`) con la convención de Notificaciones (durables, mensajes persistentes, límite de entregas de 5, dead-letter), idéntica a la declaración del worker; si la cola ya existe con parámetros distintos, la corrida MUST fallar con error claro.
- **FR-014**: Todo mensaje que permanezca más de 2 horas en la cola de usuarios MUST descartarse (TTL de 2 h = 7.200.000 ms, configurable, mismo valor que declare el worker). Un mensaje vencido no se procesa ni se reenvía; al vencer pasa a la dead-letter (`recos-auto.usuarios.dead-letter`) para poder auditarlo. La dead-letter también tiene TTL (7 días = 604.800.000 ms, configurable, igual en cron y worker) para que no acumule datos personales indefinidamente. Los mensajes pendientes menores a 2 h se mantienen y se procesan cuando les toque.

**Resultado, errores y observabilidad**

- **FR-015**: Al terminar cada corrida el sistema MUST registrar un resumen con: identificador de corrida, fecha, módulo, usuarios recibidos, publicados, omitidos, repetidos, fallidos, páginas leídas, duración y resultado.
- **FR-016**: Si la corrida no puede completarse, el proceso MUST terminar con código de salida distinto de cero y mensaje de error claro; MUST NOT enviar nada a los usuarios (el cron no envía notificaciones). En esta versión la única señal de fallo es el log (evento `corrida_finalizada` con su resultado) y el código de salida; no se envían avisos por RabbitMQ ni por mail. La alerta automática (por ejemplo por corrida ausente) se evalúa cuando exista Dokploy.
- **FR-017**: Los logs MUST ser estructurados, salir por la salida estándar del contenedor y MUST NOT contener emails, nombres, claves ni URLs con credenciales.
- **FR-018**: El sistema MUST poder verificarse sin esperar al horario real, permitiendo inyectar el reloj en las pruebas.

**Contenedor y despliegue (Dokploy)**

- **FR-019**: El sistema MUST entregarse como imagen de contenedor que ejecuta el cron internamente (el contenedor permanece activo y dispara la corrida a la hora programada).
- **FR-020**: Toda la configuración MUST provenir de variables de entorno: URL y clave de servicio de api-general, URL de RabbitMQ, nombres de cola/exchange/routing key, tamaño de página, zona horaria, hora de ejecución, fecha de referencia de alternancia y parámetros de reintento. Si faltan variables obligatorias, el sistema MUST fallar de inmediato indicando cuáles.
- **FR-021**: El contenedor MUST NOT requerir volúmenes persistentes, puertos expuestos ni archivos de configuración montados.
- **FR-022**: El repositorio MUST incluir un archivo de ejemplo de variables de entorno (sin valores reales) y documentación de despliegue y operación en Dokploy, incluyendo cómo lanzar una corrida manual desde la consola del contenedor.
- **FR-023**: Mientras Dokploy no esté disponible, el sistema MUST poder ejecutarse localmente con docker-compose junto a un RabbitMQ y una api-general simulada.
- **FR-024**: Ante una señal de apagado (por ejemplo en un nuevo despliegue), el contenedor MUST detenerse de forma ordenada: termina el mensaje que está publicando y registra que la corrida quedó incompleta.
- **FR-025**: Ante un reinicio, el sistema MUST retomar la programación diaria desde la siguiente 12:00 (UTC-3), sin ejecutar corridas duplicadas por el solo hecho de reiniciar. Si el contenedor estuvo caído a las 12:00, la corrida de ese día MUST NOT ejecutarse automáticamente al volver: se recupera únicamente con una corrida manual (FR-002, FR-003), que es segura de repetir por la identidad determinística de los mensajes (FR-012). El arranque MUST registrar si se omitió la corrida del día para que sea visible para quien opera.

### Key Entities

- **Corrida**: una ejecución completa del cron para una fecha. Tiene identificador, fecha (UTC-3), módulo del día, inicio y fin, contadores (recibidos, publicados, omitidos, fallidos) y resultado.
- **Usuario destinatario**: dato recibido de api-general: `recommendation_id` (UUID), `user_id` (numérico), `nombre`, `email`, `idioma` (opcional). Contiene datos personales: nunca se persiste ni se loguea.
- **Mensaje de usuario**: lo que se publica por cada destinatario: los datos del usuario más `fecha`, `modulo` e identificador de corrida. Es el contrato con el worker de la feature siguiente.
- **Módulo del día**: `peliculas` o `juegos`, calculado a partir de la fecha y de la fecha de referencia configurada.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En una corrida exitosa, el 100% de los usuarios válidos devueltos por api-general tiene exactamente un mensaje en la cola de usuarios.
- **SC-002**: Reejecutar la corrida del mismo día produce mensajes con la misma identidad (usuario, fecha, módulo): 0 mensajes con identidad distinta para el mismo usuario y día.
- **SC-003**: La corrida se dispara dentro de los 60 segundos posteriores a las 12:00 UTC-3, cualquiera sea la zona horaria del servidor.
- **SC-004**: Una corrida de 10.000 usuarios termina en menos de 15 minutos en condiciones normales.
- **SC-005**: Ante una falla temporal de api-general o RabbitMQ que se recupera dentro de los reintentos, la corrida termina completa sin intervención manual.
- **SC-006**: Un operador puede desplegar el contenedor y lanzar una corrida manual siguiendo solo la documentación, en menos de 30 minutos.
- **SC-007**: Ningún log de una corrida contiene emails, nombres ni claves (verificado con una corrida de prueba y búsqueda de esos valores en la salida).
- **SC-008**: 0 notificaciones se envían directamente desde este cron.

## Assumptions

- api-general expone `GET /internal/v1/notification-targets` (implementado en la rama `feature/recos-auto-usuarios-contacto` de recome-api-general, pendiente de merge). La corrida real requiere ese merge y su despliegue.
- La clave de servicio (`X-Internal-API-Key`) la provee quien administra api-general y se configura por variable de entorno.
- El RabbitMQ es el existente del sistema y lo administra el equipo. Los nombres de cola se confirman contra el RabbitMQ real.
- El día de `peliculas` por defecto es el 2026-10-05 (lunes); es configurable. Desde esa fecha se alterna día por medio.
- La cola de usuarios descarta los mensajes con más de 2 horas (TTL por defecto de 2 h); el worker debe declarar el mismo TTL, porque una cola con otros argumentos falla con `PRECONDITION_FAILED`. El valor es configurable. La dead-letter retiene los mensajes 7 días y los elimina sola.
- Escala esperada: hasta decenas de miles de usuarios; no se requiere paralelismo en el cron en esta versión.
- No existe hoy una preferencia de baja de recomendaciones automáticas: se encola a todos los usuarios con email. Si se agrega en api-general, deberá filtrarla api-general (el cron no filtra) y revisarse este supuesto.
- Fuera de alcance: el worker que consume la cola, el armado de la notificación, el envío por mail/push y el endpoint de recomendaciones de api-general.
- Dokploy todavía no existe; hasta entonces se valida con docker-compose local y se deja documentado el despliegue previsto.
- El cron no guarda estado entre corridas: la repetición se maneja por la identidad determinística de los mensajes.
- Una corrida perdida (contenedor caído a las 12:00) no se recupera sola en esta versión; se relanza a mano. La recuperación automática se evaluará cuando exista Dokploy y se pueda medir cuán seguido ocurre.
