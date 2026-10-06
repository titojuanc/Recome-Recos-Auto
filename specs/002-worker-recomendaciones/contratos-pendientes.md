# Contratos pendientes de confirmar (T049)

| Tema | Estado | Qué falta |
|------|--------|-----------|
| api-general: `recommendation_id` en la respuesta | Rama `feature/recos-auto-usuarios-contacto` (commit `57fefd4`), sin mergear ni pushear | Mergear; el worker lo exige (FR-025) |
| Cola de salida | Se asume `notificaciones` (configurable con `RABBITMQ_QUEUE_NOTIFICACIONES`) | Confirmar nombre y que la declara Recome-Notificaciones (quorum) |
| Versión de RabbitMQ | Probado con 3.13 | Confirmar la de producción (`x-delivery-limit` exige quorum) |
| Clave de servicio | Se reutiliza `X-Internal-API-Key` | Decidir si cron y worker tendrán clave propia |
| `consumer_timeout` | No se probó el vencimiento real (30 min) | Opcional: prueba larga |
