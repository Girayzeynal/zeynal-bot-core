"""
providers.py - defines functions for interacting with external services (Odds API, Telegram API).
"""
import requests
from faz22_engine import faz22_meta as meta

# Base URLs for the APIs
TELEGRAM_API_URL = f"https://api.telegram.org/bot{meta.TELEGRAM_TOKEN}"
ODDS_API_URL = "https://api.the-odds-api.com/v4"

def get_sports():
    """
    Fetches the list of in-season sports from the Odds API.
    Returns: list of sports (as JSON objects) or None if error.
    """
    url = f"{ODDS_API_URL}/sports/?apiKey={meta.ODDS_API_KEY}"
    try:
        resp = requests.get(url, timeout=5)
    except Exception as e:
        return None
    if resp.status_code == 200:
        return resp.json()
    else:
        return None

def get_odds(sport_key, region=None, market=None):
    """
    Fetches odds for upcoming games of the given sport from the Odds API.
    Parameters:
        sport_key (str): The sport key (e.g., "soccer_epl").
        region (str): Region code for bookmakers (default from meta if None).
        market (str): Betting market (default from meta if None).
    Returns: list of events with odds or None if error.
    """
    if region is None:
        region = meta.DEFAULT_REGION
    if market is None:
        market = meta.DEFAULT_MARKET
    url = f"{ODDS_API_URL}/sports/{sport_key}/odds/?apiKey={meta.ODDS_API_KEY}&regions={region}&markets={market}&oddsFormat=decimal"
    try:
        resp = requests.get(url, timeout=5)
    except Exception as e:
        return None
    if resp.status_code == 200:
        return resp.json()
    else:
        return None

def send_message(chat_id, text):
    """
    Sends a text message to a Telegram chat via the Bot API.
    """
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, json=payload, timeout=5)
    except Exception as e:
        return False
    return resp.status_code == 200 
