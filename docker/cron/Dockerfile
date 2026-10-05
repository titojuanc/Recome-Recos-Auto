FROM python:3.12-slim

ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.49
ARG SHA1_AMD64=e63c11a9726b775a6a11801e81af4f3fb926aa68
ARG SHA1_ARM64=0b6c5bb743e0b0dafed1132198c81807927ac413

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates tzdata procps \
    && SHA=$([ "$TARGETARCH" = "arm64" ] && echo "$SHA1_ARM64" || echo "$SHA1_AMD64") \
    && curl -fsSLo /usr/local/bin/supercronic \
       "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH:-amd64}" \
    && echo "${SHA}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY docker/cron/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && useradd -r -u 10001 recos
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
USER recos

ENTRYPOINT ["/entrypoint.sh"]
