#!/bin/sh
# Valida config, genera el crontab y lanza Supercronic como hijo.
# Supercronic no reenvía SIGTERM al job en curso, así que se hace aquí (FR-024).
set -u

CRONTAB=/tmp/crontab

python -m recos_auto.cron bootstrap "$CRONTAB" || exit $?

supercronic -split-logs "$CRONTAB" &
SUPER=$!

detener() {
    pkill -TERM -f "python -m recos_auto.cron run" 2>/dev/null
    kill -TERM "$SUPER" 2>/dev/null
}
trap detener TERM INT

wait "$SUPER"
STATUS=$?
# un `wait` interrumpido por la señal devuelve >128; esperar al cierre real
wait "$SUPER" 2>/dev/null
exit "$STATUS"
