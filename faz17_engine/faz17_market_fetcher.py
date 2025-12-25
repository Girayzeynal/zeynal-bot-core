import os
import time
import requests

# Odds API anahtarı – Fly.io secrets üzerinden tanımlanmalı
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

# Basketbol (NBA) için Odds API uç noktası
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"

# Basit önbellek (maç anahtarı → veri) ve süre ayarı
_cached_data = {}
_CACHE_TIMEOUT = 60  # saniye

def fetch_market_data(league: str, date_str: str, home: str, away: str):
    """
    Belirtilen maç için market (oran) verilerini çeker. Kısa süreli önbellek kullanır.
    Geri dönüş JSON veri ya da hata durumunda {'error': ...} sözlüğüdür.
    """
    cache_key = f"{league}:{date_str}:{home}:{away}"
    now = time.time()

    # Önce önbelleğe bak
    if cache_key in _cached_data:
        cached = _cached_data[cache_key]
        if now - cached["time"] < _CACHE_TIMEOUT:
            return cached["data"]

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
    }

    try:
        resp = requests.get(ODDS_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        data = {"error": str(e)}

    # Önbelleğe kaydet
    _cached_data[cache_key] = {"time": now, "data": data}
    return data 
