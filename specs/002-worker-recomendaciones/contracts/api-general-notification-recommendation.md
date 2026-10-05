# Contrato consumido: recomendación para notificar (api-general)

> Copia derivada. La custodia es de `recome-api-general` (rama `feature/recos-auto-usuarios-contacto`, sin mergear). Un cambio se propone allí; nunca se modifica aquí.

`GET {API_GENERAL_BASE_URL}/internal/v1/notification-recommendations/{recommendation_id}?module=peliculas|juegos`

Header: `X-Internal-API-Key: <API_GENERAL_API_KEY>`

## 200
```json
{ "item_id": "uuid", "module": "peliculas", "titulo": "…", "position": 1 }
```

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

El worker no reintenta dentro del cliente: los reintentos son los de RabbitMQ (hasta 5).
