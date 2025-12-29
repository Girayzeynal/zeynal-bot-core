FROM python:3.11-slim

# Çalışma dizini
WORKDIR /app

# Sistem bağımlılıkları
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Proje dosyaları
COPY . .

# 🔴 KRİTİK SATIR – entrypoint.sh dosyasını KOPYALA
COPY entrypoint.sh entrypoint.sh

# entrypoint çalıştırma izni
RUN chmod +x entrypoint.sh

# 🚀 FINAL START
CMD ["bash", "./entrypoint.sh"] 
