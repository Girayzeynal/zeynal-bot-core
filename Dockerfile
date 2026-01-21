FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# OS deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# 🔴 KRİTİK SATIR (BU YOKSA OLMAZ)
COPY data/baselines /app/data/baselines

# Writable dirs
RUN mkdir -p /app/logs

EXPOSE 8080
STOPSIGNAL SIGINT

CMD ["python", "-u", "main.py"]
