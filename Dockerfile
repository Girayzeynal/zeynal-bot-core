# Python 3.11 tabanlı slim imaj
FROM python:3.11-slim

# Çalışma dizini
WORKDIR /app

# Bağımlılıkları yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
COPY . .

# Fly.io iç portu
EXPOSE 8080

# Uygulama başlangıç komutu
CMD ["python", "main.py"]

CMD ["bash", "./entrypoint.sh"]
