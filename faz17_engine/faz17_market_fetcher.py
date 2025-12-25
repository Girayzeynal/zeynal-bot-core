import os
import time
import requests

# Gerekli API anahtarını ortam değişkeninden al (Fly.io secret olarak tanımlanmalı)
API_KEY = os.environ.get("MARKET_API_KEY")

# API uç noktasını tanımla (örnek amaçlı; gerçek servis URL'inizi buraya koyun)
API_URL = "https://api.example.com/market"

# Önbellek değişkenleri ve süresi
_cached_data = None
_last_fetch_time = 0
CACHE_TIMEOUT = 300  # saniye cinsinden; ör. 300 sn = 5 dakika

def fetch_market_data():
    """
    Harici piyasa API'ından veriyi çeker. Önceden çekilmiş veri yakın zamanda alınmışsa,
    önbellekteki değer döndürülür. Aksi halde API tekrar çağrılır.
    """
    global _cached_data, _last_fetch_time

    # Önbellekte güncel veri varsa direkt onu döndür
    if _cached_data is not None and (time.time() - _last_fetch_time) < CACHE_TIMEOUT:
        return _cached_data

    # API istek parametrelerini hazırla (anahtar gerekiyorsa ekle)
    params = {}
    if API_KEY:
        params["apikey"] = API_KEY

    try:
        response = requests.get(API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()  # API'den gelen veriyi al
    except Exception as e:
        # Hata durumunda veriyi bir hata mesajıyla döndür (veya logging yapabilirsiniz)
        data = {"error": str(e)}

    # Yeni veriyi önbelleğe al ve zamanını güncelle
    _cached_data = data
    _last_fetch_time = time.time()
    return _cached_data
