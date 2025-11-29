# ============================================================
# HOOPBRAIN ULTRA CORE - DOCKERFILE (FLY.IO PERFECT BUILD)
# Python 3.11 + EasyOCR + Tesseract + OpenCV-Headless + Gunicorn
# ============================================================

FROM python:3.11-slim

# ------------------------------------------------------------
# 1) SYSTEM DEPS (Tesseract + Minimal libs)
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# 2) WORKDIR
# ------------------------------------------------------------
WORKDIR /app

# ------------------------------------------------------------
# 3) PYTHON DEPS
# ------------------------------------------------------------
COPY requirements.txt /app/

RUN pip install --upgrade pip setuptools wheel

# OpenCV (headless) pip’ten kurulacak → %100 Fly.io uyumlu
RUN pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------
# 4) APP FILES
# ------------------------------------------------------------
COPY . /app/

# ------------------------------------------------------------
# 5) OCR BOOST PARAMS
# ------------------------------------------------------------
ENV HB_OCR_ZOOM="TRUE"
ENV HB_OCR_SHARPEN="TRUE"
ENV HB_OCR_CONTRAST="TRUE"
ENV HB_OCR_DENOISE="TRUE"
ENV HB_OCR_THRESHOLD="TRUE"

# Tesseract path
ENV TESSDATA_PREFIX="/usr/share/tesseract-ocr/4.00/tessdata"

# ------------------------------------------------------------
# 6) RUN (Fly.io ile tam uyumlu)
# ------------------------------------------------------------
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "main:app"] 
