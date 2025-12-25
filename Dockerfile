# Python 3 tabanlı bir imaj kullanıyoruz (örnek olarak slim sürümü)
FROM python:3.11-slim

# Çalışma dizinini oluştur ve ayarla
WORKDIR /app

# Python bağımlılıklarını yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
COPY . .

# Uygulamanın dinleyeceği portu belirt (Fly.io iç port 8080 kullanır)
EXPOSE 8080

# Uygulamayı başlat
CMD ["python", "main.py"]
