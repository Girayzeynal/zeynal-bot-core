import os
import time
import logging
from typing import Optional, Dict, Any, List

import requests

log = logging.getLogger(__name__)

# ================================================================
# 🌍 HOOPBRAIN GLOBAL DATA ENGINE v0.1
#   Kaynak: API-SPORTS / API-BASKETBALL
#   Docs: https://api-sports.io/documentation/basketball/v1
# ================================================================
HB_API_BASE = os.getenv("HB_API_BASE", "https://v1.basketball.api-sports.io")
HB_API_KEY = (
    os.getenv("HB_API_KEY")
    or os.getenv("API_SPORTS_KEY")
    or os.getenv("APISPORTS_KEY")
)

HB_TIMEOUT = float(os.getenv("HB_API_TIMEOUT", "8.0"))


class HoopbrainLiveError(Exception):
    """Hoopbrain canlı veri hataları için basit exception tipi."""


def _ensure_api_key():
    if not HB_API_KEY:
        raise HoopbrainLiveError(
            "HB_API_KEY / API_SPORTS_KEY env tanımlı değil "
            "(API-BASKETBALL anahtarı gerekiyor)."
        )


def _api_get(path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    API-SPORTS basket endpoint wrapper.
    """
    _ensure_api_key()

    base = HB_API_BASE.rstrip("/")
    url = f"{base}{path}"

    headers = {
        "x-apisports-key": HB_API_KEY,
        "Accept": "application/json",
        "User-Agent": "hoopbrain-core/1.0",
    }

    log.info("[HB_API] GET %s params=%s", url, params)

    resp = requests.get(url, headers=headers, params=params, timeout=HB_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    # API-SPORTS format: {"response": [...], "errors": {...}, "results": n}
    if data.get("errors"):
        log.warning("[HB_API] errors: %s", data["errors"])

    return data.get("response", []) or []


def _normalize_name(s: str) -> str:
    if not s:
        return ""
    return (
        s.lower()
        .replace(".", " ")
        .replace("-", " ")
        .replace("_", " ")
        .replace("  ", " ")
        .strip()
    )


def _match_team_name(target: str, candidate: str) -> bool:
    """
    Çok katı eşleşme yapmayalım; substring + normalize.
    Örn:
      target: "fener", candidate: "Fenerbahce Beko"
    """
    t = _normalize_name(target)
    c = _normalize_name(candidate)
    if not t or not c:
        return False
    return t in c or c in t


def fetch_live_game_any(
    league_hint: str,
    home_hint: str,
    away_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Tek giriş noktası:
      - league_hint: "NBA", "EL", "TR", "ALL" vs (şimdilik sadece filtreleyici hint)
      - home_hint: "MIA", "FENER", "EFES"
      - away_hint: opsiyonel; verilmezse sadece home takımla arar.

    Dönüş:
      {
        "raw": {... API-SPORTS orijinal game objesi ...},
        "league": "NBA",
        "home": "Miami Heat",
        "away": "New York Knicks",
        "score_home": 54,
        "score_away": 50,
        "period": "Q3",
        "clock": "05:21",
        "status_long": "3rd quarter",
        "timestamp": 1730000000,
      }

    Not:
      - Şimdilik tüm canlı maçları çekip isimle eşleştiriyoruz (live=all).
      - İleride league_id mapping ile hızlandırırız.
    """
    league_hint = (league_hint or "").upper()
    home_hint = (home_hint or "").strip()
    away_hint = (away_hint or "").strip() if away_hint else None

    if not home_hint:
        raise HoopbrainLiveError("home_hint boş olamaz")

    # Canlı maçları çek
    games = _api_get("/games", {"live": "all"})

    if not games:
        raise HoopbrainLiveError("Şu anda API'de canlı basketbol maçı bulunamadı.")

    candidates = []

    for g in games:
        try:
            league_name = g.get("league", {}).get("name") or ""
            league_country = g.get("league", {}).get("country") or ""
            teams = g.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})

            home_name = home.get("name") or ""
            away_name = away.get("name") or ""

            # League filtresi (çok sıkı değil, sadece küçük bir bias)
            if league_hint not in ("", "ALL"):
                if league_hint == "NBA" and "nba" not in _normalize_name(league_name):
                    continue
                if league_hint in ("EL", "EUROLEAGUE"):
                    # Euroleague / Eurocup için kabaca filter
                    if "euro" not in _normalize_name(league_name):
                        continue
                if league_hint == "TR":
                    # Türkiye liglerini ülkeden yakala
                    if "turkey" not in _normalize_name(league_country):
                        continue

            # Takım ismi eşleşmesi
            if not _match_team_name(home_hint, home_name) and not (
                away_hint and _match_team_name(home_hint, away_name)
            ):
                # home_hint hiçbir takımda geçmiyorsa, bu maçı atla
                continue

            if away_hint:
                if not (
                    _match_team_name(away_hint, away_name)
                    or _match_team_name(away_hint, home_name)
                ):
                    continue

            # Buraya gelenler "candidate"
            candidates.append(g)
        except Exception as e:
            log.warning("[HB_API] game parse hata: %s", e)

    if not candidates:
        raise HoopbrainLiveError(
            f"Eşleşen canlı maç bulunamadı. (league_hint={league_hint}, "
            f"home={home_hint}, away={away_hint})"
        )

    # Şimdilik ilk maçı al (ileride skor / önem / saat vs. ile seçim yapılır)
    game = candidates[0]

    return _extract_game_summary(game)


def _extract_game_summary(game: Dict[str, Any]) -> Dict[str, Any]:
    """
    API-SPORTS game objesinden Hoopbrain friendly özet çıkar.
    """
    league = game.get("league", {})
    teams = game.get("teams", {})
    scores = game.get("scores", {})
    status = game.get("status", {}) or {}

    home = teams.get("home", {})
    away = teams.get("away", {})

    home_name = home.get("name") or "HOME"
    away_name = away.get("name") or "AWAY"

    # total skor
    s_home = scores.get("home", {})
    s_away = scores.get("away", {})

    score_home = s_home.get("total")
    score_away = s_away.get("total")

    # Period / çeyrek durumu
    period = status.get("short") or ""
    status_long = status.get("long") or ""
    clock = status.get("timer") or ""

    # Timestamp (unixtime)
    timestamp = game.get("date", {}).get("timestamp")

    summary = {
        "raw": game,
        "league": league.get("name") or "Basketball",
        "league_country": league.get("country") or "",
        "home": home_name,
        "away": away_name,
        "score_home": score_home,
        "score_away": score_away,
        "period": period,
        "clock": clock,
        "status_long": status_long,
        "timestamp": timestamp,
    }

    return summary


# ================================================================
# 🇹🇷 MACKOLIK HOOK (şimdilik sadece skeleton)
# ================================================================
def enrich_with_mackolik(
    summary: Dict[str, Any],
    mackolik_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Şimdilik sadece hook:
      - İleride burada maçkolik HTML / JSON çekip:
          * yerel iddaa baremleri
          * açılış / kapanış oranları
          * handikap & total line
        ekleyeceğiz.

    Şimdilik summary'i aynen geri dönüyor.
    """
    # TODO: FAZ-14.x'te Mackolik entegrasyonu buraya
    return summary


# ================================================================
# 🎯 HOOPBRAIN HIGH-LEVEL ENTRY
# ================================================================
def get_live_match_global(
    league_hint: str,
    home_hint: str,
    away_hint: Optional[str] = None,
    mackolik_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ana giriş:
      - API-SPORTS üzerinden canlı maçı bul
      - Özet çıkar
      - İsteğe bağlı Mackolik ile zenginleştir

    Kullanım:
      summary = get_live_match_global("NBA", "MIA", "NYK")
      summary = get_live_match_global("TR", "FENER", "EFES", mackolik_id="4406870")
    """
    summary = fetch_live_game_any(league_hint, home_hint, away_hint)
    summary = enrich_with_mackolik(summary, mackolik_id=mackolik_id)
    return summary
