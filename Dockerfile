# Zeynal Core AI — Fly.io Custom Build (ENGINEERING MODE)

FROM python:3.12-slim

# 🧱 CUDA/Torch GPU bağımlılıklarını %100 blokla (Fly.io CPU ortamı için şart)
ENV TORCH_CUDA_VERSION=skip
ENV CUDA_VISIBLE_DEVICES=-1

# ---------------------------------------------------
# Sistem paketlerini kur
# ---------------------------------------------------
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------
# Çalışma dizini
# ---------------------------------------------------
WORKDIR /app

# ---------------------------------------------------
# Gereksinimleri kopyala
# ---------------------------------------------------
COPY requirements.txt /app/requirements.txt

# ---------------------------------------------------
# Python paketlerini kur
# ---------------------------------------------------
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------
# Uygulama dosyalarını kopyala
# ---------------------------------------------------
COPY . /app

# HTTP port
EXPOSE 8080

# ---------------------------------------------------
# Bot çalıştır
# ---------------------------------------------------
CMD ["python", "main.py"] 
