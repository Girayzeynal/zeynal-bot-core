import requests

class HoopbrainLiveError(Exception):
    pass


def get_live_match_global(league: str, home: str, away: str):
    """
    HoopBrain Global Live Engine (Simplified)
    Desteklenen ligler:
    - NBA
    - EL (EuroLeague)
    - TR (BSL)
    - EU (FIBA Europe)
    """

    league = league.upper()
    home = home.upper()
    away = away.upper()

    # Örnek demo API’ler (sen gerçek kaynakları ekleyeceksin)
    PROVIDERS = {
        "NBA": f"https://hoopbrain-api.fly.dev/live/nba/{home}/{away}",
        "EL":  f"https://hoopbrain-api.fly.dev/live/el/{home}/{away}",
        "TR":  f"https://hoopbrain-api.fly.dev/live/tr/{home}/{away}",
        "EU":  f"https://hoopbrain-api.fly.dev/live/eu/{home}/{away}",
    }

    if league not in PROVIDERS:
        raise HoopbrainLiveError(f"Lig desteklenmiyor: {league}")

    url = PROVIDERS[league]

    try:
        r = requests.get(url, timeout=4)
        if r.status_code != 200:
            raise HoopbrainLiveError(
                f"API cevap vermedi (HTTP {r.status_code})"
            )
        data = r.json()

        # Bot’un okuyacağı temel alanlar
        return {
            "league": league,
            "home_name": data.get("home", home),
            "away_name": data.get("away", away),
            "home_score": data.get("home_score", 0),
            "away_score": data.get("away_score", 0),
            "period_label": data.get("period", "-"),
            "clock": data.get("clock", "-"),
            "status": data.get("status", "-"),
            "pace": data.get("pace", 0.0),
            "win_prob": data.get("win_prob", 0.50),
            "win_side_label": data.get("win_side", "HOME"),
            "provider": data.get("provider", "HoopBrainAPI"),
        }

    except Exception as e:
        raise HoopbrainLiveError(f"Canlı veri alınamadı: {e}")
