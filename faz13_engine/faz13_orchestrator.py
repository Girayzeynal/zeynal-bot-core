# ======================= faz13_engine/faz13_orchestrator.py =====================
from __future__ import annotations
import math
import logging
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)

LEAGUE_PROFILE: Dict[str, Dict[str, Any]] = {
    "NBA": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "EUROLEAGUE": {"band_half": 5.5, "weights": [0.25, 0.25, 0.25, 0.25]},
    "ACB": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "BSL": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "VTB": {"band_half": 6.5, "weights": [0.24, 0.25, 0.25, 0.26]},
    "BBL": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "LBA": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "LNB": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "ABA": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "A1": {"band_half": 5.5, "weights": [0.25, 0.25, 0.25, 0.25]},
    "NBL": {"band_half": 7.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "LKL": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},
    "CBA": {"band_half": 8.0, "weights": [0.23, 0.25, 0.25, 0.27]},
    "DEFAULT": {"band_half": 6.0, "weights": [0.25, 0.25, 0.25, 0.25]},
}

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def _round_half(x: float) -> float:
    return round(x * 2.0) / 2.0

def _split_periods(total: float, weights: list[float]) -> Dict[str, int]:
    q1 = round(total * weights[0])
    q2 = round(total * weights[1])
    q3 = round(total * weights[2])
    q4 = round(total * weights[3])
    return {
        "q1": q1,
        "q2": q2,
        "h1": q1 + q2,
        "q3": q3,
        "q4": q4,
        "h2": q3 + q4
    }

def _risk_label(league: str, inj_count: int,
                market_delta: float, confidence: float) -> str:
    ad = abs(market_delta)
    score = 0.15 * min(4, inj_count) + 0.10 * min(10.0, ad) + (1.0 - confidence) * 10.0
    if league.upper() == "NBA":
        return "HIGH" if score >= 2.6 else "MID" if score >= 1.6 else "LOW"
    return "HIGH" if score >= 3.0 else "MID" if score >= 1.8 else "LOW"

def run_faz13_auto_pipeline(
    league: str,
    home: str,
    away: str,
    date_str: str,
    market_data: Optional[Dict[str, Any]] = None,
    market_meta: Optional[Dict[str, Any]] = None,
    extra_inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    FAZ-13 takım-öncelikli (team-first) tahmin motoru.
    LİG ORTALAMASI kullanılmaz; base_pred = home_avg_for + away_avg_for.
    market_data, market_meta, extra_inputs opsiyoneldir.
    """
    lg = (league or "DEFAULT").upper()
    profile = LEAGUE_PROFILE.get(lg, LEAGUE_PROFILE["DEFAULT"])
    ctx = extra_inputs or {}
    team_stats = ctx.get("team_stats") if isinstance(ctx.get("team_stats"), dict) else {}
    injuries = ctx.get("injuries") if isinstance(ctx.get("injuries"), dict) else {}
    home_avg = float(team_stats.get("home_avg_for", 0.0) or 0.0)
    away_avg = float(team_stats.get("away_avg_for", 0.0) or 0.0)
    if home_avg <= 0.0:
        home_avg = 111.0 if lg == "NBA" else 80.0
    if away_avg <= 0.0:
        away_avg = 111.0 if lg == "NBA" else 80.0
    base_pred = _round_half(home_avg + away_avg)
    inj_count = int(injuries.get("count", 0) or 0)
    if inj_count > 0:
        base_pred = _round_half(base_pred - min(3.0, inj_count * 0.8))
    band_half = float(profile["band_half"])
    band = [int(math.floor(base_pred - band_half)), int(math.ceil(base_pred + band_half))]
    periods = _split_periods(base_pred, profile["weights"])
    market = market_data if isinstance(market_data, dict) else {}
    line = market.get("totals_line")
    try:
        market_line = float(line) if line is not None else None
    except Exception:
        market_line = None
    fallback_used = False
    if market_line is None:
        market_line = _round_half(base_pred)
        fallback_used = True
    market_delta = _round_half(market_line - base_pred)
    ou_dir = "OVER" if base_pred > market_line else "UNDER"
    conf = 0.92
    conf -= min(0.12, abs(market_delta) * (0.015 if lg == "NBA" else 0.01))
    conf -= min(0.08, inj_count * 0.02)
    conf = _clamp(conf, 0.35, 0.97)
    risk = _risk_label(lg, inj_count, market_delta, conf)
    out = {
        "match": {
            "league": lg,
            "date": date_str,
            "home": home,
            "away": away
        },
        "baseline": {
            "home_avg_for": round(home_avg, 2),
            "away_avg_for": round(away_avg, 2),
            "inj_count": inj_count
        },
        "base_pred": round(base_pred, 1),
        "band": band,
        "periods": periods,
        "market": {
            "line": market_line,
            "delta": market_delta,
            "fallback_used": fallback_used,
            "provider": market.get("provider"),
        },
        "ou": {
            "dir": ou_dir,
            "band": band
        },
        "confidence": round(conf, 3),
        "risk": risk,
        "debug": {
            "context_keys": list(ctx.keys())
        }
    }
    log.info(f"FAZ13 | {lg} | {home}-{away} | {out}")
    return out
