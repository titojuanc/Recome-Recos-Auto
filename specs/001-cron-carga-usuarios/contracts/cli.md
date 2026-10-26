# Contrato: línea de comandos y códigos de salida

Módulo: `python -m recos_auto.cron`

## Comandos

| Comando | Qué hace |
|---|---|
| `run` | Ejecuta una corrida completa. Es lo que Supercronic dispara a la hora programada y lo que se usa para una corrida manual. |
| `run --date YYYY-MM-DD` | Igual, pero usando esa fecha (y su módulo del día) en vez de hoy. Pensado para pruebas y recuperación. |
| `bootstrap <ruta-crontab>` | Valida el entorno, escribe el crontab y registra la zona y la próxima ejecución. Lo usa el entrypoint del contenedor. |

### Corrida manual en el contenedor

```bash
docker exec <contenedor> python -m recos_auto.cron run
docker exec <contenedor> python -m recos_auto.cron run --date 2026-10-07
```

Una corrida manual aplica las mismas reglas que la programada (bloqueo, reintentos, identidad determinística).

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | Corrida completa sin fallos. |
| 1 | Error fatal o corrida interrumpida por señal. |
| 2 | Corrida terminada, pero con usuarios no publicados. |
| 75 | No se ejecutó: ya hay otra corrida en curso. |
| 78 | Configuración inválida o incompleta (lista las variables faltantes). |

## Eventos de log relevantes (JSON, una línea cada uno)

`bootstrap_ok`, `corrida_iniciada`, `pagina_leida`, `usuario_omitido`, `publicacion_reintentada`, `publicacion_fallida`, `corrida_omitida_por_bloqueo`, `corrida_interrumpida`, `corrida_finalizada`, `corrida_omitida_al_arrancar`.

Ningún evento incluye `nombre`, `email`, claves ni la URL de RabbitMQ.
