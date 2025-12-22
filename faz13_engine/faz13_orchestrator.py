# ================================================================
# FAZ-13 ORCHESTRATOR — TEAM BASELINE PRIMARY (LEAGUE AVG DISABLED)
# NBA CORE MODE UYUMLU
# ================================================================
from __future__ import annotations

import math
import logging
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)

# Elite leagues list (priority)
ELITE_LEAGUES = {
    "NBA",
    "EUROLEAGUE",
    "ACB",
    "BSL",
    "VTB",
    "BBL",
    "LBA",
    "LNB",
    "ABA",
    "A1",
    "NBL",
    "LKL",
    "CBA",
}

# Lig bazlı (sadece periyot dağılımı ve dar bant toleransı için)
# NOT: Bu "lig ortalaması" değildir. Base_pred TEAM-FIRST gelir.
LEAGUE_PROFILE = {
    "NBA": {"band_half": 6.0, "weights": [0.24, 0.25, 0.25, 0.26]},       # ±5–7 hedefi
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

def _split_periods(total: float, weights) -> Dict[str, int]:
    q1 = round(total * weights[0])
    q2 = round(total * weights[1])
    q3 = round(total * weights[2])
    q4 = round(total * weights[3])
    h1 = q1 + q2
    h2 = q3 + q4
    return {"q1": q1, "q2": q2, "h1": h1, "q3": q3, "q4": q4, "h2": h2}

def _team_split(total: float, home_avg: float, away_avg: float, league: str) -> Dict[str, int]:
    # Home edge küçük bir bias (NBA: ev avantajı biraz daha belirgin)
    bias = 0.01 if league == "NBA" else 0.005
    denom = max(1e-9, home_avg + away_avg)
    share = _clamp((home_avg / denom) + bias, 0.45, 0.55)
    home_score = round(total * share)
    away_score = round(total - home_score)
    return {"home": int(home_score), "away": int(away_score)}

def _risk_label(league: str, inj_count: int, market_delta: float, confidence: float) -> str:
    # NBA daha agresif: market şişmesi + injury -> risk yükselir
    ad = abs(market_delta)
    score = 0.0
    score += 0.15 * min(4, inj_count)          # injuries
    score += 0.10 * min(10.0, ad)              # market delta
    score += (1.0 - confidence) * 10.0         # düşük güven

    if league == "NBA":
        if score >= 2.6:
            return "HIGH"
        if score >= 1.6:
            return "MID"
        return "LOW"
    # EuroLeague daha yumuşak
    if score >= 3.0:
        return "HIGH"
    if score >= 1.8:
        return "MID"
    return "LOW"

def run_faz13_auto_pipeline(
    league: str,
    home: str,
    away: str,
    date_str: str,
    market_data: Dict[str, Any] = None,
    market_meta: Dict[str, Any] = None,
    extra_inputs: Dict[str, Any] = None,   # context burada
) -> Dict[str, Any]:
    """
    TEAM-FIRST CORE:
      base_pred = home_avg + away_avg (+ küçük context düzeltmeleri)
    LIG ORTALAMASI: DISABLED
    """

    league_key = (league or "DEFAULT").upper()
    profile = LEAGUE_PROFILE.get(league_key, LEAGUE_PROFILE["DEFAULT"])

    ctx = extra_inputs or {}
    team_stats = ctx.get("team_stats", {}) if isinstance(ctx.get("team_stats"), dict) else {}
    inj = ctx.get("injuries", {}) if isinstance(ctx.get("injuries"), dict) else {}

    home_avg = float(team_stats.get("home_avg_for", team_stats.get("home_avg", 0.0)) or 0.0)
    away_avg = float(team_stats.get("away_avg_for", team_stats.get("away_avg", 0.0)) or 0.0)

    # Eğer API fail olursa burada “bootstrap” yaparız ama asla UNKNOWN yazmayız
    # Bu bir lig ortalaması değil; sadece boş kalmamak için minimum güvenli prior.
    if home_avg <= 0:
        home_avg = 111.0 if league_key == "NBA" else 80.0
    if away_avg <= 0:
        away_avg = 111.0 if league_key == "NBA" else 80.0

    base_pred = home_avg + away_avg

    # News/coach/rotation risk -> band genişletme ve confidence etkisi FAZ-22’de daha ağır yapılır.
    # FAZ-13’te minimal: injury varsa 1-2 puan düşür
    inj_count = int(inj.get("count", 0) or 0)
    if inj_count > 0:
        base_pred = base_pred - min(3.0, inj_count * 0.8)

    base_pred = float(_round_half(base_pred))

    band_half = float(profile["band_half"])
    band_low = int(math.floor(base_pred - band_half))
    band_high = int(math.ceil(base_pred + band_half))
    periods = _split_periods(base_pred, profile["weights"])

    # market normalize
    market = market_data if isinstance(market_data, dict) else {}
    line = market.get("totals_line")
    try:
        market_line = float(line) if line is not None else None
    except Exception:
        market_line = None

    # “None/Unknown yok” kuralı için fallback line:
    # market yoksa base_pred’ten line üretiyoruz (etiketle: FALLBACK_LINE)
    fallback_used = False
    if market_line is None:
        market_line = float(_round_half(base_pred))
        fallback_used = True

    market_delta = float(_round_half(market_line - base_pred))

    # O/U direction zorunlu:
    # predicted > line -> OVER, else UNDER (eşitse UNDER)
    ou_dir = "OVER" if base_pred > market_line else "UNDER"

    # confidence (faz13 içi kaba; faz22 daha iyi şekillendirir)
    # injury + delta -> düşür
    conf = 0.92
    conf -= min(0.12, abs(market_delta) * (0.015 if league_key == "NBA" else 0.01))
    conf -= min(0.08, inj_count * 0.02)
    conf = _clamp(conf, 0.35, 0.97)

    teams = _team_split(base_pred, home_avg, away_avg, league_key)
    risk = _risk_label(league_key, inj_count, market_delta, conf)

    output = {
        "match": {
            "league": league_key,
            "date": date_str,
            "home": home,
            "away": away,
        },
        "baseline": {
            "home_avg_for": round(home_avg, 2),
            "away_avg_for": round(away_avg, 2),
            "inj_count": inj_count,
        },
        "base_pred": round(base_pred, 1),
        "band": [band_low, band_high],
        "teams": teams,
        "periods": periods,
        "market": {
            "line": market_line,
            "delta": market_delta,
            "fallback_used": fallback_used,
            "provider": market.get("provider"),
        },
        "ou": {
            "dir": ou_dir,
            "band": [band_low, band_high],
        },
        "confidence": round(conf, 3),
        "risk": risk,
        "debug": {
            "context_keys": list(ctx.keys()),
        }
    }

    log.info(f"FAZ13 | {league_key} | {home}-{away} | {output}")
    return output
