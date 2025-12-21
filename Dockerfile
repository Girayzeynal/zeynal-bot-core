FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fly varsayılan port: 8080
ENV PORT=8080

CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app", "--workers", "1", "--threads", "8", "--timeout", "60"]
