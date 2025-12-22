from typing import Dict, Any, Optional
import math
import datetime
import logging

log = logging.getLogger(__name__)

# Lig bazlı ayarlar
LEAGUE_CONFIG: Dict[str, Dict[str, Any]] = {
    # NBA maçları genellikle yüksek tempolu ve yüksek skorludur
    "NBA": {
        "base_pred": 223.0,
        "band_half": 7.0,
        "weights": [0.24, 0.25, 0.25, 0.26],
    },
    # EuroLeague: daha düşük tempo, dengeli periyot dağılımı
    "EUROLEAGUE": {
        "base_pred": 160.0,
        "band_half": 5.5,
        "weights": [0.25, 0.25, 0.25, 0.25],
    },
    # Türkiye Basketbol Süper Ligi (BSL)
    "TBL": {
        "base_pred": 161.0,
        "band_half": 6.0,
        "weights": [0.24, 0.24, 0.26, 0.26],
    },
    # Çin Ligi (CBA): çok yüksek tempo
    "CBA": {
        "base_pred": 197.0,
        "band_half": 8.0,
        "weights": [0.23, 0.25, 0.25, 0.27],
    },
    # Varsayılan değerler
    "DEFAULT": {
        "base_pred": 170.0,
        "band_half": 6.0,
        "weights": [0.25, 0.25, 0.25, 0.25],
    },
}

# Sezon bazlı ufak ayarlamalar (örnek)
SEASON_ADJUST: Dict[str, float] = {
    "2024": 0.0,
    "2025": 1.5,  # 2025 sezonunda oyun tempo artışı
    "2026": 2.0,
}

def _split_periods_with_weights(total: float, weights) -> Dict[str, int]:
    """Verilen ağırlıklar ile çeyrek/yarı skorlarına bölüştürür."""
    q1 = round(total * weights[0])
    q2 = round(total * weights[1])
    q3 = round(total * weights[2])
    q4 = round(total * weights[3])
    h1 = q1 + q2
    h2 = q3 + q4
    return {"q1": q1, "q2": q2, "h1": h1, "q3": q3, "q4": q4, "h2": h2}

def _get_config_for_league(league: str) -> Dict[str, Any]:
    key = (league or "").upper()
    return LEAGUE_CONFIG.get(key, LEAGUE_CONFIG["DEFAULT"])

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
    Lig ve sezon bazlı ayarlarla otomatik pipeline.
    - Lig parametresinden config çeker
    - Sezon ayarını uygular
    - Bant ve periyot dağılımı oluşturur
    """
    cfg = _get_config_for_league(league)
    season_adj = _get_season_adjust(date_str)

    base_pred = cfg["base_pred"] + season_adj
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

    log.info(f"FAZ13 | {league} | {home}-{away} | {result}")
    return result
