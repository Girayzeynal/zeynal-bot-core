FROM python:3.11-slim

# ----------------------------
# Python runtime flags
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

# Writable dirs (volume + local)
RUN mkdir -p /data/baselines /app/logs

# ----------------------------
# Fly
# ----------------------------
EXPOSE 8080
STOPSIGNAL SIGINT

CMD ["python", "-u", "main.py"]
