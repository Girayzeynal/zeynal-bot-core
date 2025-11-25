FROM python:3.12-slim

ENV TORCH_CUDA_VERSION=skip
ENV CUDA_VISIBLE_DEVICES=-1

# Sistem OCR bağımlılıkları
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8080

CMD ["python", "main.py"] 
