FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Sistem bağımlılıkları (requests vs. için güvenli)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fly varsayılan port (Flask health/webhook için)
ENV PORT=8080

# ❗ Gunicorn YOK
# ❗ Tek process: Telegram bot + Flask
CMD ["python", "main.py"] 
