# Data Model: Cron de carga diaria de usuarios

El cron **no persiste nada**. Estas entidades viven en memoria durante una corrida, salvo el mensaje, que viaja por RabbitMQ.

## Corrida

Una ejecución completa del cron para una fecha.

| Campo | Tipo | Notas |
|---|---|---|
| `corrida_id` | string (UUID4 corto) | Generado al iniciar; solo para trazabilidad en logs y en el mensaje. No forma parte de la identidad del mensaje. |
| `fecha` | date (zona `RUN_TIMEZONE`) | Por defecto hoy en esa zona; `--date` la reemplaza en corridas manuales. |
| `modulo` | `peliculas` \| `juegos` | Derivado de `fecha` y `MODULE_REFERENCE_DATE`. |
| `inicio` / `fin` | datetime con zona | |
| `paginas` | int | Páginas leídas de api-general. |
| `recibidos` | int | Usuarios devueltos por api-general (incluye omitidos y repetidos). |
| `publicados` | int | Mensajes confirmados por el broker. |
| `omitidos` | int | Registros inválidos (falta `recommendation_id`, `user_id` o `email`, o email mal formado). |
| `repetidos` | int | Usuarios ya vistos en la misma corrida; no se vuelven a publicar. |
| `fallidos` | int | Mensajes que no se pudieron publicar tras los reintentos. |
| `resultado` | `exito` \| `parcial` \| `error` \| `interrumpida` \| `omitida_por_bloqueo` | Determina el código de salida (ver `contracts/cli.md`). |

**Invariante**: `recibidos = publicados + omitidos + repetidos + fallidos` cuando la corrida termina sin abortar.

### Estados

```text
iniciada --(bloqueo tomado)--> en_curso --(todas las páginas procesadas)--> exito | parcial
    |                              |
    |                              +--(error fatal)--> error
    |                              +--(SIGTERM/SIGINT)--> interrumpida
    +--(bloqueo ocupado)--> omitida_por_bloqueo
```

## Usuario destinatario (entrada)

Registro recibido de api-general en `items[]` (contrato en `contracts/api-general-notification-targets.md`).

| Campo | Tipo | Validación |
|---|---|---|
| `recommendation_id` | UUID | Obligatorio. |
| `user_id` | entero positivo | Obligatorio. Se usa luego como `destinatario` de la notificación. |
| `nombre` | string | Obligatorio y no vacío. Se conserva tal cual (acentos, emojis). |
| `email` | string con formato de email | Obligatorio. |
| `idioma` | string o null | Opcional. Se reenvía si viene. |

Un registro que falla la validación se **omite**: se cuenta en `omitidos` y se registra solo `user_id` (si existe) y el motivo, nunca nombre ni email.

**Unicidad**: dentro de una corrida, `user_id` identifica al usuario; si aparece otra vez se cuenta en `repetidos`.

## Mensaje de usuario (salida)

Lo que se publica en `recos-auto.usuarios`. Schema en `contracts/mensaje-usuario.schema.json`.

| Campo | Tipo | Origen |
|---|---|---|
| `version` | entero (`1`) | Versión del contrato. |
| `message_id` | UUIDv5 | Determinístico: `uuid5(NAMESPACE, "{user_id}|{fecha}|{modulo}")`. También va como propiedad AMQP `message_id`. |
| `corrida_id` | string | De la corrida. |
| `fecha` | `YYYY-MM-DD` | De la corrida. |
| `modulo` | `peliculas` \| `juegos` | De la corrida. |
| `recommendation_id` | UUID | Del usuario. |
| `user_id` | entero positivo | Del usuario. |
| `nombre` | string | Del usuario. |
| `email` | string | Del usuario. |
| `idioma` | string \| null | Del usuario. |

**Propiedades AMQP**: `delivery_mode=2` (persistente), `content_type=application/json`, `message_id` igual al del cuerpo.

**Datos personales**: `nombre` y `email` están en el cuerpo. Por eso no se loguean y la cola no es accesible fuera del equipo que administra RabbitMQ.

## Módulo del día

Función pura `modulo_para(fecha, referencia) -> "peliculas" | "juegos"`:

```text
dias = (fecha - referencia).days
modulo = "peliculas" si dias % 2 == 0, si no "juegos"
```

Ejemplos con referencia 2026-10-05: 2026-10-05 → peliculas, 2026-10-06 → juegos, 2026-10-07 → peliculas, 2026-10-04 → juegos.

## Configuración

Ver `contracts/entorno.md`. `Config.from_env()` valida todo junto y, si faltan variables obligatorias, falla **una sola vez** listando todas las faltantes (sin imprimir valores).

## Evento de resumen (log)

Línea JSON `evento = "corrida_finalizada"` con: `corrida_id`, `fecha`, `modulo`, `paginas`, `recibidos`, `publicados`, `omitidos`, `repetidos`, `fallidos`, `duracion_s`, `resultado`. Sin datos personales.
