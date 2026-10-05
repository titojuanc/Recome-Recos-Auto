# Data Model: Worker de recomendaciones

El worker no persiste nada. Estas son las estructuras en memoria y en tránsito.

## MensajeUsuario (entrada, existente en `common/mensajes.py`)
Contrato v1 de la feature 001: `version`, `message_id` (UUID), `corrida_id`, `fecha`, `modulo` (`peliculas|juegos`), `recommendation_id` (UUID), `user_id` (int ≥ 1), `nombre`, `email`, `idioma` (opcional, ignorado). Contiene datos personales: no se loguea.

## Recomendacion (respuesta de api-general)
| Campo | Tipo | Regla |
|---|---|---|
| `item_id` | UUID | requerido |
| `module` | `peliculas` \| `juegos` | debe coincidir con el pedido |
| `titulo` | str | no vacío tras recortar; si no, "sin recomendación" |
| `position` | int | informativo |

## Notificacion (salida, espejo del contrato de Notificaciones)
| Campo | Valor |
|---|---|
| `id_mensaje` | entero positivo de 63 bits derivado de `message_id` (research D4) |
| `canal` | `"mail"` (fijo) |
| `destinatario` | `user_id` |
| `mail` | `email` del mensaje de usuario |
| `contenido.titulo` / `contenido.cuerpo` | armados desde plantillas (research D5) |
Sin `push_sub`, `adjunto` ni `callback_url`. Modelo con `extra="forbid"`.

## Resultado (decisión del procesador)
Enumeración: `NOTIFICADO`, `SIN_RECOMENDACION(motivo)`, `INVALIDO(motivo)`, `TRANSITORIO(motivo)`.
Mapeo a RabbitMQ: `NOTIFICADO` y `SIN_RECOMENDACION` → `ack`; `INVALIDO` → `nack(requeue=False)`; `TRANSITORIO` → retención o `nack(requeue=True)`.

## EstadoInterruptor
`CERRADO` → (N fallos seguidos) → `ABIERTO` → (espera) → `SEMIABIERTO` → éxito → `CERRADO` / fallo → `ABIERTO` (espera ×2, tope). Campos: fallos consecutivos, espera actual, instante de reapertura.

## Contadores
`recibidos`, `notificados`, `sin_recomendacion`, `invalidos`, `reintentados`, `pausas_del_corte`, `inicio`. Todos con lock.
