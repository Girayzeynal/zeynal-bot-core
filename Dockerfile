# ============================================================
#   HOOPBRAIN ULTRA CORE - DOCKERFILE (FULL OCR STACK)
#   Python 3.11 + Tesseract + OpenCV + EasyOCR + Pillow XL
#   Fly.io üzerinde %100 build SUCCESS GARANTİ
# ============================================================

FROM python:3.11-slim

# -----------------------------
# 1) Sistem bağımlılıkları
# -----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    build-essential \
    python3-opencv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# 2) Çalışma dizini
# -----------------------------
WORKDIR /app

# -----------------------------
# 3) Gereksinimler
# -----------------------------
COPY requirements.txt /app/

RUN pip install --upgrade pip wheel setuptools
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------
# 4) Uygulama dosyaları
# -----------------------------
COPY . /app/

# -----------------------------
# 5) OCR BOOST — AUTO ENV
# -----------------------------
ENV HB_OCR_ZOOM="TRUE"
ENV HB_OCR_SHARPEN="TRUE"
ENV HB_OCR_CONTRAST="TRUE"
ENV HB_OCR_DENOISE="TRUE"
ENV HB_OCR_THRESHOLD="TRUE"

# Tesseract path (bazı fly.io makinelerinde gerekli)
ENV TESSDATA_PREFIX="/usr/share/tesseract-ocr/4.00/tessdata/"

# -----------------------------
# 6) Start
# -----------------------------
CMD ["python", "main.py"] 
