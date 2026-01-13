FROM python:3.11-slim

# ----------------------------
# System
# ----------------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ----------------------------
# OS dependencies
# ----------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------
# Python deps
# ----------------------------
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ----------------------------
# App
# ----------------------------
COPY . .

# Writable dirs (Fly FS / future volume)
RUN mkdir -p /app/data /app/logs

# ----------------------------
# Fly
# ----------------------------
EXPOSE 8080

# SIGTERM/SIGINT düzgün işləsin
STOPSIGNAL SIGINT

CMD ["python", "-u", "main.py"] 
