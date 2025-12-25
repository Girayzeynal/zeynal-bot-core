"""
providers.py – harici servislerle (Odds API, Telegram API ve API‑Sports) iletişim fonksiyonlarını içerir.
"""

import requests
from faz22_engine import faz22_meta as meta

# Taban URL'ler
TELEGRAM_API_URL = f"https://api.telegram.org/bot{meta.TELEGRAM_TOKEN}"
ODDS_API_URL = "https://api.the-odds-api.com/v4"
# API‑Sports için temel URL (gerekirse versiyon ve uç nokta ayarlanmalı)
SPORT_API_URL = "https://api-sports.io/v3"

def get_sports():
    """
    Odds API üzerinden mevcut sporları listeler (JSON) ya da hata durumunda None döndürür.
    """
    url = f"{ODDS_API_URL}/sports/?apiKey={meta.ODDS_API_KEY}"
    try:
        resp = requests.get(url, timeout=5)
    except Exception:
        return None
    if resp.status_code == 200:
        return resp.json()
    return None

def get_odds(sport_key: str, region: str = None, market: str = None):
    """
    Belirli bir spor için yaklaşan maçların oranlarını döndürür.
    region verilmezse meta.DEFAULT_REGION, market verilmezse meta.DEFAULT_MARKET kullanılır.
    """
    if region is None:
        region = meta.DEFAULT_REGION
    if market is None:
        market = meta.DEFAULT_MARKET
    url = (
        f"{ODDS_API_URL}/sports/{sport_key}/odds/"
        f"?apiKey={meta.ODDS_API_KEY}"
        f"&regions={region}&markets={market}&oddsFormat=decimal"
    )
    try:
        resp = requests.get(url, timeout=5)
    except Exception:
        return None
    if resp.status_code == 200:
        return resp.json()
    return None

def send_message(chat_id: str, text: str) -> bool:
    """
    Telegram API üzerinden mesaj gönderir. Başarı durumunda True, aksi halde False döner.
    """
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=5)
    except Exception:
        return False
    return resp.status_code == 200

def fetch_sports_data(league: str, date_str: str, home: str, away: str):
    """
    API‑Sports üzerinden takım bilgisi veya maç istatistikleri çeker.
    Bu fonksiyon örnek niteliğindedir; API‑Sports dokümantasyonuna göre endpoint'ler ve parametreler düzenlenmelidir.
    Geri dönüş değeri, JSON veri ya da hata durumunda {'error': ...} sözlüğüdür.
    """
    api_key = meta.API_SPORT_KEY
    headers = {"x-apisports-key": api_key} if api_key else {}
    try:
        # Ev sahibi takımı arayın
        resp_home = requests.get(
            f"{SPORT_API_URL}/teams",
            params={"search": home},
            headers=headers,
            timeout=10,
        )
        resp_home.raise_for_status()
        data_home = resp_home.json()

        # Deplasman takımı arayın
        resp_away = requests.get(
            f"{SPORT_API_URL}/teams",
            params={"search": away},
            headers=headers,
            timeout=10,
        )
        resp_away.raise_for_status()
        data_away = resp_away.json()

        # Gerekirse ek uç noktalar: maç fikstürleri veya istatistikler
        return {"home_team": data_home, "away_team": data_away}
    except Exception as e:
        return {"error": str(e)} 
