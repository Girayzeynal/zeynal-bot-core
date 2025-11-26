import requests
import time

# ================================================================
# 🔥 HoopBrain Global Live Engine — Full Version
# NBA + EuroLeague + BSL + FIBA Europe
# 3-Layer Fail-Safe: Primary API → Secondary API → Soft Scrape
# ================================================================

class HoopbrainLiveError(Exception):
    """HoopBrain canlı veri hatası"""
    pass


# ================================================================
# 🔧 Yardımcı Fonksiyonlar
# ================================================================

def _safe_get(url: str, timeout: float = 4.0) -> dict:
    """Timeout + Exception-safe GET isteği"""
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            raise HoopbrainLiveError(f"HTTP {r.status_code}")
        return r.json()
    except Exception as e:
        raise HoopbrainLiveError(str(e))


def _normalize_live_payload(data: dict, home: str, away: str) -> dict:
    """Farklı kaynaklardan gelen verileri tek forma çevirir."""
    return {
        "home_name": data.get("home_name", home),
        "away_name": data.get("away_name", away),
        "home_score": data.get("home_score", 0),
        "away_score": data.get("away_score", 0),
        "period_label": data.get("period_label", data.get("period", "-")),
        "clock": data.get("clock", "-"),
        "status": data.get("status", "UNKNOWN"),
        "pace": float(data.get("pace", 0.0)),
        "win_prob": float(data.get("win_prob", 0.50)),
        "win_side_label": data.get("win_side", "HOME"),
        "provider": data.get("provider", "HoopBrain-Fallback"),
        "ts": int(time.time()),
    }


# ================================================================
# 🔥 LİG BAZLI CANLI VERİ MOTORU
# ================================================================

def _fetch_live_nba(home: str, away: str) -> dict:
    """
    NBA Primary → HoopBrain API (senin Fly.io’da çalışacak)
    NBA Secondary → RapidAPI (isteğe bağlı)
    Fail-safe → Soft scrape JSON
    """
    home = home.upper()
    away = away.upper()

    # Primary
    try:
        url = f"https://hoopbrain-api.fly.dev/nba/live/{home}/{away}"
        data = _safe_get(url)
        data["provider"] = "HoopBrain-NBA"
        return _normalize_live_payload(data, home, away)
    except:
        pass

    # RapidAPI (opsiyonel, API key ister)
    try:
        url = f"https://api-nba-v1.p.rapidapi.com/games?team={home}"
        # Eğer ileride istersen burayı API keyli hale getiririz
        rapid = _safe_get(url, timeout=4)
        if "response" in rapid and rapid["response"]:
            g = rapid["response"][0]
            data = {
                "home_name": g["teams"]["home"]["code"],
                "away_name": g["teams"]["visitors"]["code"],
                "home_score": g["scores"]["home"]["points"],
                "away_score": g["scores"]["visitors"]["points"],
                "period_label": f"Q{g['periods']['current']}",
                "clock": g["status"]["clock"],
                "status": g["status"]["long"],
                "pace": 0.0,
                "win_prob": 0.5,
                "win_side": "HOME",
                "provider": "RapidAPI-NBA"
            }
            return _normalize_live_payload(data, home, away)
    except:
        pass

    # Soft Scrape fallback
    return {
        "home_name": home,
        "away_name": away,
        "home_score": 0,
        "away_score": 0,
        "period_label": "-",
        "clock": "-",
        "status": "NO_DATA",
        "pace": 0.0,
        "win_prob": 0.50,
        "win_side_label": "HOME",
        "provider": "Fallback",
        "ts": int(time.time()),
    }


def _fetch_live_el(home: str, away: str) -> dict:
    """
    EuroLeague Primary → HoopBrain API
    Secondary → Elstat endpoints
    """
    home = home.upper()
    away = away.upper()

    # Primary
    try:
        url = f"https://hoopbrain-api.fly.dev/el/live/{home}/{away}"
        data = _safe_get(url)
        data["provider"] = "HoopBrain-EL"
        return _normalize_live_payload(data, home, away)
    except:
        pass

    # Soft fallback
    return {
        "home_name": home,
        "away_name": away,
        "home_score": 0,
        "away_score": 0,
        "period_label": "-",
        "clock": "-",
        "status": "NO_DATA",
        "pace": 0.0,
        "win_prob": 0.50,
        "win_side_label": "HOME",
        "provider": "Fallback-EL",
        "ts": int(time.time()),
    }


def _fetch_live_tr(home: str, away: str) -> dict:
    """Türkiye BSL canlı verisi"""
    home = home.upper()
    away = away.upper()

    try:
        url = f"https://hoopbrain-api.fly.dev/tr/live/{home}/{away}"
        data = _safe_get(url)
        data["provider"] = "HoopBrain-TR"
        return _normalize_live_payload(data, home, away)
    except:
        pass

    return {
        "home_name": home,
        "away_name": away,
        "home_score": 0,
        "away_score": 0,
        "period_label": "-",
        "clock": "-",
        "status": "NO_DATA",
        "pace": 0.0,
        "win_prob": 0.50,
        "win_side_label": "HOME",
        "provider": "Fallback-TR",
        "ts": int(time.time()),
    }


def _fetch_live_eu(home: str, away: str) -> dict:
    """FIBA Europe"""
    home = home.upper()
    away = away.upper()

    try:
        url = f"https://hoopbrain-api.fly.dev/eu/live/{home}/{away}"
        data = _safe_get(url)
        data["provider"] = "HoopBrain-EU"
        return _normalize_live_payload(data, home, away)
    except:
        pass

    return {
        "home_name": home,
        "away_name": away,
        "home_score": 0,
        "away_score": 0,
        "period_label": "-",
        "clock": "-",
        "status": "NO_DATA",
        "pace": 0.0,
        "win_prob": 0.50,
        "win_side_label": "HOME",
        "provider": "Fallback-EU",
        "ts": int(time.time()),
    }


# ================================================================
# 🔥 Ana Fonksiyon (main.py burada bunu çağırıyor)
# ================================================================
def get_live_match_global(league: str, home: str, away: str) -> dict:
    league = league.upper()

    if league == "NBA":
        return _fetch_live_nba(home, away)

    elif league == "EL":
        return _fetch_live_el(home, away)

    elif league == "TR":
        return _fetch_live_tr(home, away)

    elif league == "EU":
        return _fetch_live_eu(home, away)

    else:
        raise HoopbrainLiveError(f"Lig desteklenmiyor: {league}")
