# Contrato consumido: recomendación para notificar (api-general)

> Copia derivada. La custodia es de `recome-api-general` (rama `feature/recos-auto-usuarios-contacto`, sin mergear). Un cambio se propone allí; nunca se modifica aquí.

`GET {API_GENERAL_BASE_URL}/internal/v1/notification-recommendations/{recommendation_id}?module=peliculas|juegos`

Header: `X-Internal-API-Key: <API_GENERAL_API_KEY>`

## 200
```json
{ "recommendation_id": "uuid", "item_id": "uuid", "module": "peliculas", "titulo": "…", "position": 1, "catalog_item_id": 123,
  "push_sub": { "endpoint": "https://…", "keys": { "p256dh": "…", "auth": "…" } } }
```

`catalog_item_id` es el id del ítem en el catálogo (el de `/catalogo/:itemId` en el frontend); `item_id` es el UUID del motor de recomendaciones y **no** sirve para armar el link. Si falta, el worker cae en `item_id`.

`push_sub` es opcional (ausente o `null` si el usuario no activó las notificaciones push). Si viene, el worker publica `canal=push` con el mail como respaldo; si viene mal formado se ignora y el aviso sale por mail.

## Errores y tratamiento
| Código | Origen | Tratamiento del worker |
|---|---|---|
| 400 | `module` inválido | inválido → dead-letter |
| 401 / 403 | clave incorrecta | transitorio (interruptor), log de error |
| 404 | el usuario no tiene recomendación | sin recomendación, `ack` |
| 412 | recomendaciones aún no disponibles para el usuario | sin recomendación, `ack` |
| 502 | ítem fuera del catálogo o sin título | transitorio |
| 503 | servicio de recomendaciones caído | transitorio |
| timeout / red / 5xx / 429 | — | transitorio |

`recommendation_id` repite el del pedido (agregado en api-general, commit `57fefd4` de la rama `feature/recos-auto-usuarios-contacto`). El worker lo compara con el de su mensaje: si difiere, o si `module` no coincide, no notifica y el mensaje va a dead-letter.

El worker no reintenta dentro del cliente: los reintentos son los de RabbitMQ (hasta 5).
