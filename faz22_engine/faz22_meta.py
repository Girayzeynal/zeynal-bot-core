"""
faz22_meta.py – ortam konfigürasyonlarını (tokenlar ve API anahtarları) yükler.
"""
import os

# .env dosyası desteğini varsa yükle; yoksa hatayı yut
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # python-dotenv kurulu değilse sorun değil; Fly.io secrets üzerinden okumaya devam edilir
    pass

# Telegram bot token'ı
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# The Odds API anahtarı
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# API-Sports / API‑Basketball anahtarı
API_SPORT_KEY = os.getenv("API_SPORT_KEY", "")

# Odds API için varsayılan parametreler
DEFAULT_REGION = "us"
DEFAULT_MARKET = "h2h"

class Config:
    ENV = "production"
    DEBUG = False
    # Gerekirse burada SECRET_KEY tanımlanabilir
    # SECRET_KEY = os.getenv("SECRET_KEY", "change_this_secret") 
