# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OPENBLAS_NUM_THREADS=1
ENV OMP_NUM_THREADS=1

WORKDIR /app

# OS deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi && \
    pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Prepare writable directories before COPY so code-only rebuilds do not create
# several full filesystem copies on Docker's vfs storage driver.
RUN mkdir -p /app/data/baselines/series /app/logs

# App code; runtime records and local config are excluded by .dockerignore.
COPY . .

EXPOSE 8080
STOPSIGNAL SIGINT

ARG RELEASE_SHA=UNKNOWN
ENV ZEYNAL_RELEASE_SHA=$RELEASE_SHA

CMD ["python", "-u", "main.py"]
