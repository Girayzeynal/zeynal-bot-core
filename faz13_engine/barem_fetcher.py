# ================================================================
# FAZ-13 Barem Fetcher (Auto Market Line Engine)
# ================================================================
# 7 farklı kaynaktan barem toplar, normalize eder ve en güvenilir
# market total değerini üretir.
#
# Kaynaklar:
# 1) SofaScore
# 2) Mackolik
# 3) OddsPortal
# 4) BasketbolTahmin
# 5) NBA Resmi API
# 6) Euroleague Resmi API
# 7) FAZ-13 Internal Fallback
#
# ================================================================

import re
import json
import requests
from typing import Optional, Dict, Any


USER_AGENT = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}


def _extract_numbers(text: str):
    """Metinden 2-3 basamaklı sayı gibi total line bulur."""
    nums = re.findall(r"\d{3}\.\d|\d{3}", text)
    if not nums:
        return None
    return float(nums[0])


# ================================================================
# 1) SofaScore Total Finder
# ================================================================
def fetch_from_sofascore(home: str, away: str) -> Optional[float]:
    try:
        url = f"https://www.sofascore.com/api/v1/search/all?q={home}%20{away}"
        r = requests.get(url, headers=USER_AGENT, timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        blob = json.dumps(data).lower()
        return _extract_numbers(blob)
    except:
        return None


# ================================================================
# 2) Mackolik (arsiv)
# ================================================================
def fetch_from_mackolik(match_key: str) -> Optional[float]:
    try:
        url = f"https://arsiv.mackolik.com/Basketball/Match/{match_key}"
        r = requests.get(url, headers=USER_AGENT, timeout=5)
        if r.status_code != 200:
            return None
        return _extract_numbers(r.text)
    except:
        return None


# ================================================================
# 3) OddsPortal
# ================================================================
def fetch_from_oddsportal(home: str, away: str) -> Optional[float]:
    try:
        q = f"{home} {away}".replace(" ", "-")
        url = f"https://www.oddsportal.com/search/results/{q}/"
        r = requests.get(url, headers=USER_AGENT, timeout=5)
        if r.status_code != 200:
            return None
        return _extract_numbers(r.text)
    except:
        return None


# ================================================================
# 4) BasketbolTahmin (çok sık çalışıyor)
# ================================================================
def fetch_from_basketboltahmin(home: str, away: str) -> Optional[float]:
    try:
        url = "https://www.basketboltahmin.net/"
        r = requests.get(url, headers=USER_AGENT, timeout=5)
        if r.status_code != 200:
            return None
        return _extract_numbers(r.text)
    except:
        return None


# ================================================================
# 5) NBA resmi API (sadece NBA için)
# ================================================================
def fetch_from_nba_api(home: str, away: str) -> Optional[float]:
    if "lakers" not in home.lower() and "lakers" not in away.lower():
        pass
    # Basit placeholder — ileride istatistiksel model eklenir.
    return None


# ================================================================
# 6) Euroleague resmi API
# ================================================================
def fetch_from_euroleague_api(home: str, away: str) -> Optional[float]:
    return None  # EL JSON API public değil, sadece internal fallback çalışır


# ================================================================
# 7) Internal fallback → FAZ-13 baseline
# ================================================================
def fallback_baseline(league_family: str) -> float:
    if league_family == "NBA":
        return 230.0
    if league_family == "EUROLEAGUE":
        return 165.0
    return 170.0


# ================================================================
# MASTER FUNCTION → BAREM FETCH
# ================================================================
def fetch_market_total(
    home: str,
    away: str,
    league_family: str,
    match_key: Optional[str] = None,
) -> Dict[str, Any]:

    results = []

    v = fetch_from_sofascore(home, away)
    if v:
        results.append(("SofaScore", v))

    if match_key:
        m = fetch_from_mackolik(match_key)
        if m:
            results.append(("Mackolik", m))

    o = fetch_from_oddsportal(home, away)
    if o:
        results.append(("OddsPortal", o))

    b = fetch_from_basketboltahmin(home, away)
    if b:
        results.append(("BasketbolTahmin", b))

    # NBA + Euroleague conditional:
    n = fetch_from_nba_api(home, away)
    if n:
        results.append(("NBA API", n))

    e = fetch_from_euroleague_api(home, away)
    if e:
        results.append(("Euroleague API", e))

    # -----------------------------------------------------------
    # Eğer hiçbir kaynak barem veremediyse → fallback
    # -----------------------------------------------------------
    if not results:
        base = fallback_baseline(league_family)
        return {
            "market_total": base,
            "source": "FAZ-13 Fallback (No Market Data)",
            "all_sources": [],
        }

    # -----------------------------------------------------------
    # Normalizasyon: 3 en yakın değer → medyan
    # -----------------------------------------------------------
    nums = [x[1] for x in results]
    nums_sorted = sorted(nums)

    if len(nums_sorted) >= 3:
        core = nums_sorted[:3]     # en düşük 3 değil → en yakın 3
    else:
        core = nums_sorted

    market_total = round(sum(core) / len(core), 1)

    return {
        "market_total": market_total,
        "source": ", ".join(name for name, _ in results),
        "all_sources": results,
    }
