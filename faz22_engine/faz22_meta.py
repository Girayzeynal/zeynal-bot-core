"""
faz22_meta.py – ortam konfigürasyonlarını (tokenlar ve API anahtarları) yükler ve Flask ayarlarını tutar.
"""

import os
from dotenv import load_dotenv

# .env dosyası varsa yükle
load_dotenv()

# Ortam değişkenleri veya varsayılan değerler
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
# The Odds API anahtarı (örneğin free plan veya premium plan)
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
# API‑Sports anahtarı – maç istatistikleri için kullanılır
API_SPORT_KEY = os.getenv("API_SPORT_KEY", "")

# Odds API sorguları için varsayılan bölge ve market
DEFAULT_REGION = "us"
DEFAULT_MARKET = "h2h"

# Flask uygulaması için konfigürasyon sınıfı
class Config:
    ENV = "production"
    DEBUG = False
    # Gerekirse gizli bir SECRET_KEY tanımlanabilir (örn. oturum yönetimi için)
    # SECRET_KEY = os.getenv("SECRET_KEY", "change_this_secret") 
