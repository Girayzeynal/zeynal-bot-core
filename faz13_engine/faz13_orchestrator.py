# -*- coding: utf-8 -*-
"""
FAZ-13 + FAZ-23 Orchestrator (FINAL PATCH)
- Market data: main_total / total_line / primary_total anahtarlarını normalize eder
- Drift detector + wrong-line suspicion + league profile ağırlıkları
- Çıktı: main.py'nin beklediği alanlarla uyumludur (total/band/vector/meta23)
"""

import math
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List, Tuple

# FAZ-23 DataHub opsiyonel
try:
    from faz23_engine.faz23_datahub import fetch_match_totals  # type: ignore
except Exception:
    fetch_match_totals = None  # type: ignore


# ================================================================
# DATA MODELLERİ
# ================================================================
@dataclass
class Faz13Input:
    source: str
    league: str
    date_str: str
    home: str
    away: str
    prematch_total_hint: Optional[float] = None
    recent_points_avg: Optional[float] = None
    manual_text: Optional[str] = None
    api_data: Optional[Dict[str, Any]] = None
    visual_meta: Optional[Dict[str, Any]] = None
    market_data: Optional[Dict[str, Any]] = None
    profile: Optional[Dict[str, Any]] = None


# ================================================================
# NORMALİZASYON
# ================================================================
def normalize_manual_text(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = " ".join(text.split())
    lowered = cleaned.lower()
    return {
        "raw": text,
        "cleaned": cleaned,
        "tokens": cleaned.split(),
        "has_overtime": ("ot" in lowered) or ("uzatma" in lowered),
    }

def normalize_api_data(api_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not api_data:
        return None
    out = dict(api_data)
    if "pace" in out:
        try: out["pace"] = float(out["pace"])
        except Exception: pass
    return out

def normalize_visual_meta(visual_meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not visual_meta:
        return None
    return dict(visual_meta)


# ================================================================
# LEAGUE FAMILY + BASELINE
# ================================================================
def _detect_league_family(league: str) -> Tuple[str, float]:
    l = (league or "").lower()
    if "nba" in l:
        return "NBA", 230.0
    if "euroleague" in l or "euro league" in l:
        return "EUROLEAGUE", 165.0
    if "eurocup" in l:
        return "EUROCUP", 162.0
    if "bsl" in l or "türkiye" in l or "turkey" in l:
        return "EURO_MID", 160.0
    if "fiba" in l or "world cup" in l or "eurobasket" in l or "national" in l:
        return "NATIONAL", 162.0
    return "GENERICMID", 165.0


# ================================================================
# PROFILES (market ağırlığı + varyans)
# ================================================================
LEAGUE_PROFILES: Dict[str, Dict[str, Any]] = {
    "NBA": {"market_weight": 0.60, "variance": "HIGH", "band_delta": 6.5},
    "EUROLEAGUE": {"market_weight": 0.50, "variance": "LOW", "band_delta": 5.5},
    "EUROCUP": {"market_weight": 0.50, "variance": "MID", "band_delta": 5.8},
    "EURO_MID": {"market_weight": 0.48, "variance": "MID", "band_delta": 5.8},
    "NATIONAL": {"market_weight": 0.40, "variance": "CHAOTIC", "band_delta": 7.0},
    "GENERICMID": {"market_weight": 0.50, "variance": "MID", "band_delta": 6.0},
}


# ================================================================
# MARKET NORMALIZER
# ================================================================
def _extract_market_total(market_data: Optional[Dict[str, Any]]) -> Tuple[Optional[float], float, List[str]]:
    """
    Returns: (market_total, confidence, srcs)
    - desteklenen anahtarlar: main_total, total_line, primary_total, line, ou, total
    - confidence: market_data["confidence"] varsa kullanır (0..1), yoksa 0.65
    - srcs: market_data["sources"] veya market_data["src"] içinden
    """
    if not market_data or not isinstance(market_data, dict):
        return None, 0.0, []

    keys = ["main_total", "total_line", "primary_total", "line", "ou", "total"]
    market_total = None
    for k in keys:
        if k in market_data and market_data.get(k) is not None:
            try:
                market_total = float(str(market_data.get(k)).replace(",", "."))
                break
            except Exception:
                pass

    conf = 0.65
    try:
        if market_data.get("confidence") is not None:
            conf = float(market_data["confidence"])
            conf = max(0.0, min(1.0, conf))
    except Exception:
        conf = 0.65

    srcs: List[str] = []
    try:
        if isinstance(market_data.get("sources"), list):
            for s in market_data["sources"]:
                if isinstance(s, dict) and s.get("src"):
                    srcs.append(str(s["src"]))
        elif isinstance(market_data.get("src"), dict):
            for kk, vv in market_data["src"].items():
                if vv:
                    srcs.append(str(kk))
    except Exception:
        pass

    return market_total, conf, srcs


# ================================================================
# DRIFT + WRONG LINE
# ================================================================
def detect_market_drift(model_total: float, market_total: float) -> str:
    diff = market_total - model_total
    if abs(diff) >= 6.0:
        return "HARD_DRIFT"
    if abs(diff) >= 3.0:
        return "SOFT_DRIFT"
    return "ALIGNED"

def wrong_line_suspicion(model_total: float, market_total: float, variance: str) -> bool:
    # düşük varyanslı liglerde büyük fark = şüphe
    if variance == "LOW" and abs(model_total - market_total) >= 7.0:
        return True
    if variance == "CHAOTIC" and abs(model_total - market_total) >= 10.0:
        return True
    return False


# ================================================================
# PERIOD SPLIT
# ================================================================
def _split_periods(total: float) -> Tuple[float, float, float, float]:
    weights = [0.24, 0.26, 0.25, 0.25]
    return (
        round(total * weights[0], 1),
        round(total * weights[1], 1),
        round(total * weights[2], 1),
        round(total * weights[3], 1),
    )


# ================================================================
# CORE TOTAL ESTIMATOR
# ================================================================
def _estimate_total_points(data: Faz13Input, league_baseline: float) -> float:
    total = league_baseline

    if data.prematch_total_hint is not None:
        try:
            total = float(data.prematch_total_hint)
        except Exception:
            pass

    if data.recent_points_avg is not None:
        try:
            r = float(data.recent_points_avg)
            total = (league_baseline * 0.5) + (r * 0.5)
        except Exception:
            pass

    return round(total, 1)


# ================================================================
# FAZ-23 META
# ================================================================
def _build_faz23_meta(
    model_total: float,
    market_total: Optional[float],
    market_conf: float,
    srcs: List[str],
    profile: Dict[str, Any],
    external_ctx: Optional[Dict[str, Any]],
) -> Dict[str, Any]:

    if market_total is None:
        model_over = 0.500
        model_under = 0.500
        primary_total = float(model_total)
        flags = ["NO_MARKET_DATA"]
        drift = "NO_MARKET"
        wrong = False
    else:
        primary_total = float(market_total)
        diff = float(model_total) - float(market_total)

        # diff > 0 => model daha yüksek => over eğilim
        if diff > 3:
            model_over, model_under = 0.62, 0.38
        elif diff > 1.5:
            model_over, model_under = 0.56, 0.44
        elif diff < -3:
            model_over, model_under = 0.38, 0.62
        elif diff < -1.5:
            model_over, model_under = 0.44, 0.56
        else:
            model_over, model_under = 0.50, 0.50

        drift = detect_market_drift(model_total, market_total)
        wrong = wrong_line_suspicion(model_total, market_total, str(profile.get("variance", "MID")))

        flags = []
        flags.append(drift)
        if wrong:
            flags.append("WRONG_LINE_SUSPECT")
        if market_conf >= 0.80:
            flags.append("MARKET_CONF_HIGH")
        elif market_conf <= 0.45:
            flags.append("MARKET_CONF_LOW")

    external_summary: Dict[str, Any] = {}
    if external_ctx:
        external_summary = {
            "family": external_ctx.get("family"),
            "league_total_baseline": external_ctx.get("league_total_baseline"),
            "team_total_baseline": external_ctx.get("team_total_baseline"),
            "has_odds": external_ctx.get("odds") is not None,
        }

    return {
        "primary_total": float(primary_total),
        "model_over": float(model_over),
        "model_under": float(model_under),
        "drift": drift,
        "wrong_line_suspicion": bool(wrong),
        "market_confidence": float(market_conf),
        "market_sources": srcs,
        "flags": flags,
        "external": external_summary,
    }


# ================================================================
# MAIN PIPELINE
# ================================================================
def run_faz13_auto_pipeline(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
    prematch_total_hint: Optional[float] = None,
    recent_points_avg: Optional[float] = None,
    source: str = "manual",
    manual_text: Optional[str] = None,
    api_data: Optional[Dict[str, Any]] = None,
    visual_meta: Optional[Dict[str, Any]] = None,
    market_data: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Dict[str, Any]:

    data = Faz13Input(
        source=source,
        league=league,
        date_str=date_str,
        home=home,
        away=away,
        prematch_total_hint=prematch_total_hint,
        recent_points_avg=recent_points_avg,
        manual_text=manual_text,
        api_data=api_data,
        visual_meta=visual_meta,
        market_data=market_data,
        profile=profile,
    )

    family, league_baseline = _detect_league_family(league)
    prof = dict(LEAGUE_PROFILES.get(family, LEAGUE_PROFILES["GENERICMID"]))

    # external ctx (opsiyonel)
    external_ctx: Optional[Dict[str, Any]] = None
    if fetch_match_totals is not None:
        try:
            external_ctx = fetch_match_totals(league=league, date_str=date_str, home=home, away=away)
        except Exception:
            external_ctx = None

    # external league baseline harmanı
    if external_ctx and external_ctx.get("league_total_baseline") is not None:
        try:
            ext_league = float(external_ctx["league_total_baseline"])
            league_baseline = round((league_baseline * 0.4) + (ext_league * 0.6), 1)
        except Exception:
            pass

    # core model total
    model_total = _estimate_total_points(data, league_baseline)

    # external team baseline harmanı
    if external_ctx and external_ctx.get("team_total_baseline") is not None:
        try:
            team_base = float(external_ctx["team_total_baseline"])
            model_total = round(model_total * 0.4 + team_base * 0.6, 1)
        except Exception:
            pass

    # market normalize
    market_total, market_conf, srcs = _extract_market_total(market_data)

    # market fusion (profile weight)
    if market_total is not None:
        mw = float(prof.get("market_weight", 0.5))
        fused_total = round((model_total * (1 - mw)) + (market_total * mw), 1)
    else:
        fused_total = float(model_total)

    # band & vector (lig varyansına göre)
    band_delta = float(prof.get("band_delta", 6.0))
    band = (round(fused_total - band_delta, 1), round(fused_total + band_delta, 1))
    vector = (round(fused_total - 4.0, 1), round(fused_total, 1), round(fused_total + 4.0, 1))

    # periods
    q1, q2, q3, q4 = _split_periods(fused_total)
    periods = (q1, q2, q3, q4)

    # team scores (basit home boost)
    home_boost = 2.0
    team_scores = (round(fused_total / 2.0 + home_boost, 1), round(fused_total / 2.0 - home_boost, 1))

    analysis: Dict[str, Any] = {
        "league_baseline": float(league_baseline),
        "profile": prof,
        "family": family,
        "home_boost": float(home_boost),
        "market_used": bool(market_total is not None),
        "market_total": market_total,
        "market_confidence": market_conf,
        "market_sources": srcs,
        "model_total_core": float(model_total),
    }

    norm_manual = normalize_manual_text(manual_text)
    norm_api = normalize_api_data(api_data)
    norm_visual = normalize_visual_meta(visual_meta)

    meta23 = _build_faz23_meta(
        model_total=float(model_total),
        market_total=market_total,
        market_conf=market_conf,
        srcs=srcs,
        profile=prof,
        external_ctx=external_ctx,
    )

    live_ctx = {
        "is_live": False,
        "live_total": None,
        "provider": None,
    }

    return {
        "family": family,
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
        "total": float(fused_total),
        "band": band,
        "vector": vector,
        "periods": periods,
        "team_scores": team_scores,
        "analysis": analysis,
        "meta23": meta23,
        "live_ctx": live_ctx,
        "raw": {
            "input": asdict(data),
            "norm_manual": norm_manual,
            "norm_api": norm_api,
            "norm_visual": norm_visual,
        },
        }
