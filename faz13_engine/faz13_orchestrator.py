from typing import Dict, Any, Optional
import math
import datetime
import logging

log = logging.getLogger(__name__)

# Her lig için varsayılan takım başına ortalama skor
LEAGUE_TEAM_DEFAULT = {
    "NBA": 111.0,
    "EUROLEAGUE": 80.0,
    "TBL": 82.0,
    "CBA": 106.0,
    "DEFAULT": 85.0,
}

# Her lig için toplam skor, bant yarıçapı ve periyot ağırlıkları
LEAGUE_CONFIG: Dict[str, Dict[str, Any]] = {
    "NBA": {
        "band_half": 7.0,
        "weights": [0.24, 0.25, 0.25, 0.26],
    },
    "EUROLEAGUE": {
        "band_half": 5.5,
        "weights": [0.25, 0.25, 0.25, 0.25],
    },
    "TBL": {
        "band_half": 6.0,
        "weights": [0.24, 0.24, 0.26, 0.26],
    },
    "CBA": {
        "band_half": 8.0,
        "weights": [0.23, 0.25, 0.25, 0.27],
    },
    "DEFAULT": {
        "band_half": 6.0,
        "weights": [0.25, 0.25, 0.25, 0.25],
    },
}

# Sezona göre toplam skoru küçük ayarlamak için (isteğe bağlı)
SEASON_ADJUST: Dict[str, float] = {
    "2024": 0.0,
    "2025": 1.5,  # 2025 sezonunda skorlar yükseldi ise
    "2026": 2.0,
}

# Takım bazlı ortalamaları buraya ekleyebilirsiniz.
# Anahtar: (lig, takım adı büyük harf)
TEAM_AVG_POINTS: Dict[str, float] = {
    # NBA örnekleri
    "NBA:BOSTON": 113.0,
    "NBA:INDIANA": 115.0,
    "NBA:LAKERS": 112.5,
    "NBA:SUNS": 110.8,
    # EuroLeague örnekleri
    "EUROLEAGUE:ANADOLU EFES": 84.0,
    "EUROLEAGUE:FENERBAHÇE": 82.5,
    # Tanımsız takımlar için ligin varsayılanı kullanılacaktır
}

def _get_team_avg(league: str, team: str) -> float:
    """Takımın ortalama skorunu getir; yoksa lig varsayılanını döndür."""
    key = f"{league.upper()}:{team.upper()}"
    if key in TEAM_AVG_POINTS:
        return TEAM_AVG_POINTS[key]
    return LEAGUE_TEAM_DEFAULT.get(league.upper(), LEAGUE_TEAM_DEFAULT["DEFAULT"])

def _split_periods_with_weights(total: float, weights) -> Dict[str, int]:
    """Verilen ağırlıklar ile periyot dağılımı hesaplar."""
    q1 = round(total * weights[0])
    q2 = round(total * weights[1])
    q3 = round(total * weights[2])
    q4 = round(total * weights[3])
    h1 = q1 + q2
    h2 = q3 + q4
    return {"q1": q1, "q2": q2, "h1": h1, "q3": q3, "q4": q4, "h2": h2}

def _get_season_adjust(date_str: str) -> float:
    try:
        year = str(datetime.datetime.strptime(date_str, "%Y-%m-%d").year)
        return SEASON_ADJUST.get(year, 0.0)
    except Exception:
        return 0.0

def run_faz13_auto_pipeline(
    *,
    league: str,
    home: str,
    away: str,
    date_str: str,
    market_data: Optional[Dict[str, Any]] = None,
    market_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    FAZ-13 pipeline – takım bazlı ortalamalara göre toplam skor tahmini.
    base_pred = ev sahibi takım ortalaması + deplasman takım ortalaması (+ sezon ayarı)
    """
    league_key = (league or "DEFAULT").upper()

    # Takım ortalamalarını çek
    home_avg = _get_team_avg(league_key, home)
    away_avg = _get_team_avg(league_key, away)

    # Sezon ayarını uygula
    season_adj = _get_season_adjust(date_str)

    # Toplam skor tahmini = home_avg + away_avg + season_adj
    base_pred = home_avg + away_avg + season_adj

    # Lig bazlı band ve periyot ağırlıkları
    cfg = LEAGUE_CONFIG.get(league_key, LEAGUE_CONFIG["DEFAULT"])
    band_half = cfg["band_half"]
    weights = cfg["weights"]

    band_low = int(math.floor(base_pred - band_half))
    band_high = int(math.ceil(base_pred + band_half))
    periods = _split_periods_with_weights(base_pred, weights)

    market = market_data if isinstance(market_data, dict) else {}

    result = {
        "league": league,
        "home": home,
        "away": away,
        "date": date_str,
        "base_pred": round(float(base_pred), 1),
        "band": [band_low, band_high],
        "periods": periods,
        "market": market,
    }

    log.info(f"FAZ13 | {league_key} | {home}-{away} | {result}")
    return result
