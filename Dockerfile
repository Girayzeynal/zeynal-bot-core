FROM python:3.11-slim

WORKDIR /app

# Sistem bağımlılıkları (numpy/pandas için yeterli)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "main.py"]
