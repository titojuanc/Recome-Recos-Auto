FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd -r -u 10001 recos
COPY src ./src
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
USER recos

# exec form: python es PID 1 y recibe SIGTERM directamente (apagado ordenado).
ENTRYPOINT ["python", "-m", "recos_auto.worker"]
