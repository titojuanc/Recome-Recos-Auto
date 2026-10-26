# Contrato consumido: api-general `notification-targets`

> **Copia derivada.** El custodio del contrato es `recome-api-general`. Está implementado en la rama `feature/recos-auto-usuarios-contacto` (pendiente de merge). Cualquier cambio se propone allá.

## Pedido

```text
GET {API_GENERAL_BASE_URL}/internal/v1/notification-targets?page_size=<1..500>[&page_token=<token>]
X-Internal-API-Key: <clave de servicio>
```

- `API_GENERAL_BASE_URL` incluye el `context-path` de api-general (por ejemplo `https://host/api/v1`).
- La clave tiene el formato `<entorno>.<secreto>` y debe corresponder al entorno configurado en api-general (misma regla que las rutas de sincronización).
- `page_size` por defecto 100; máximo 500. `page_token` es opaco para el cliente (hoy es el último id numérico visto).

## Respuesta 200

```json
{
  "items": [
    {
      "recommendation_id": "3f2b8c1e-5a4d-4c53-9f0a-1d2e3f4a5b6c",
      "user_id": 42,
      "nombre": "Ana",
      "email": "ana@example.com",
      "idioma": "es"
    }
  ],
  "next_page_token": "42"
}
```

| Campo | Notas |
|---|---|
| `items[].recommendation_id` | UUID público. |
| `items[].user_id` | Entero. |
| `items[].nombre` / `email` | api-general ya omite a los usuarios sin email. |
| `items[].idioma` | Puede ser `null`. |
| `next_page_token` | `null` o ausente en la última página. |

### Reglas que el cliente debe respetar

- Una página puede traer `items` vacío y aun así un `next_page_token` **nuevo** (todos los usuarios de ese tramo no tenían email): se continúa.
- Un `next_page_token` igual al anterior, o superar `API_GENERAL_MAX_PAGES`, es un error: se aborta.
- Solo se listan usuarios con rol de usuario final y no eliminados.

## Errores

| Estado | Tratamiento |
|---|---|
| 400 (token inválido) | Error fatal, sin reintento. |
| 401 / 403 | Error fatal, sin reintento (clave ausente, inválida o vencida). |
| 404 | Error fatal, sin reintento (ruta no desplegada). |
| 429 / 5xx / timeout / red | Reintento acotado con espera creciente; luego error fatal. |
