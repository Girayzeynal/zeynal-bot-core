from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .league_autodetect import guess_league
from .faz13_news_scraper import MatchMeta, get_match_news, encode_news_features

log = logging.getLogger(__name__)

# ================================================================
# GLOBAL SAFE NORMALIZER — tuple/list/string fix
# ================================================================

def _safe_str(x: Any) -> str:
    """
    Tüm string girdileri normalize eder.
    Tuple/list/string/None → daima temiz string döner.
    """
    if x is None:
        return ""
    if isinstance(x, (tuple, list)):
        try:
            return " ".join(str(i) for i in x)
        except Exception:
            return str(x)
    return str(x)


# ================================================================
# Yardımcı fonksiyonlar
# ================================================================

def _safe_float(x: Any) -> Optional[float]:
    try:
        if isinstance(x, str):
            x = x.replace(",", ".")
        return float(x)
    except Exception:
        return None


def _detect_match_from_text(text: str) -> str:
    if not text:
        return ""

    t = text.replace("VS", "vs").replace("Vs", "vs")

    for sep in [" - ", "-", " vs ", " vs. "]:
        if sep in t:
            parts = t.split(sep)
            if len(parts) >= 2:
                left = parts[0].strip()
                right = parts[1].strip()
                if left and right:
                    return f"{left} - {right}"

    return text.strip()[:40]


def _baseline_total_for_league(league: Any) -> float:
    """
    ✔ FIXED: league parametresi tuple/list gelse bile crash vermez.
    """
    league = _safe_str(league).lower().strip()

    if not league:
        return 200.0

    if "nba" in league:
        return 230.0
    if "euroleague" in league:
        return 165.0
    if "türkiye" in league or "bsl" in league or "turkey" in league:
        return 160.0
    if "fiba" in league or "world cup" in league or "eurobasket" in league:
        return 155.0

    return 170.0


def _national_match_flag(home: Any, away: Any, league: Any) -> bool:
    home = _safe_str(home)
    away = _safe_str(away)
    league = _safe_str(league).lower()

    if any(k in league for k in ["fiba", "eurobasket", "world cup", "olympic"]):
        return True

    def is_country(name: str) -> bool:
        n = name.strip().lower()
        return n in {
            "turkey","türkiye","france","spain","serbia","germany","greece",
            "slovenia","lithuania","latvia","usa","canada","italy","croatia",
            "bosnia","belgium","poland","russia",
        }

    return is_country(home) and is_country(away)


# ================================================================
# normalize_manual_text
# ================================================================

def normalize_manual_text(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()

    fusion: Dict[str, Any] = {
        "engine": "FAZ-13",
        "raw": text,
        "match": "",
        "home_team": "",
        "away_team": "",
        "total": None,
        "pick": None,
        "odds": None,
        "score_low": None,
        "score_high": None,
    }

    if not text:
        return fusion

    parts = text.split()

    if len(parts) >= 2:
        home = parts[0].upper()
        away = parts[1].upper()
        fusion["home_team"] = home
        fusion["away_team"] = away
        fusion["match"] = f"{home} - {away}"

    total = None
    pick = None
    odds = None

    for token in parts[2:]:
        val = _safe_float(token)
        if val is not None:
            if total is None:
                total = val
            elif odds is None:
                odds = val
            continue

        up = token.upper()
        if up in {"U", "ALT", "UNDER"} and pick is None:
            pick = "UNDER"
        elif up in {"O", "ÜST", "OVER"} and pick is None:
            pick = "OVER"

    if total is not None:
        fusion["total"] = total
        fusion["score_low"] = total - 6
        fusion["score_high"] = total + 6

    if pick:
        fusion["pick"] = pick
    if odds:
        fusion["odds"] = odds

    return fusion


# ================================================================
# normalize_visual_meta
# ================================================================

def normalize_visual_meta(ocr_text: str) -> Dict[str, Any]:
    text = (ocr_text or "").strip()

    fusion = {
        "engine": "FAZ-13-VISUAL",
        "raw_text": text,
        "match": "",
        "home_team": "",
        "away_team": "",
        "league": "",
        "debug": [],
    }

    if not text:
        return fusion

    match_str = _detect_match_from_text(text)
    fusion["match"] = match_str

    if " - " in match_str:
        left, right = match_str.split(" - ", 1)
        fusion["home_team"] = left.strip()
        fusion["away_team"] = right.strip()

    fusion["debug"].append("visual_meta_normalized_v1")
    return fusion


# ================================================================
# normalize_api_data
# ================================================================

def normalize_api_data(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if data is None:
        return {}
    out = dict(data)
    out.setdefault("engine", "FAZ-13-API")
    return out


# ================================================================
# run_faz13_auto_pipeline — ✔ SAFE VERSION
# ================================================================

def run_faz13_auto_pipeline(
    league: Any,
    date: Any,
    home_team: Any,
    away_team: Any,
    full_output: bool = True,
    match_key: Optional[str] = None,
    meta_hint: Optional[Dict[str, Any]] = None,
    api_data: Optional[Dict[str, Any]] = None,
    visual_meta: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:

    # INPUT NORMALIZATION (CRITICAL FIX)
    league = _safe_str(league)
    home_team = _safe_str(home_team)
    away_team = _safe_str(away_team)
    date = _safe_str(date)

    # Overrides
    if meta_hint is None:
        meta_hint = kwargs.get("meta_hint")
    if api_data is None:
        api_data = kwargs.get("api_data")
    if visual_meta is None:
        visual_meta = kwargs.get("visual_meta")

    # 1) League detect
    detected_league = guess_league(home_team, away_team, league)
    final_league = detected_league or league or "Unknown League"

    # 2) News engine
    match_meta = MatchMeta(
        league=final_league,
        date=date or "1970-01-01",
        home_team=home_team or "HOME",
        away_team=away_team or "AWAY",
    )

    try:
        news_summary, news_features = get_match_news(match_meta, use_cache=True)
    except Exception as e:
        log.warning("get_match_news hata verdi: %s", e)

        class Dummy:
            def __init__(self):
                self.match_key = match_meta.match_key
                self.home_team = match_meta.home_team
                self.away_team = match_meta.away_team
                self.injuries = {}
                self.fatigue = {}
                self.tempo = {}
                self.total_view = {}
                self.spread_view = {}
                self.soft_score_range = {}
                self.flags = []
                self.confidence = 0.0
                self.key_quotes = []
                self.sources_used = []

        news_summary = Dummy()
        news_features = {}

    # 3) Base total
    base = _baseline_total_for_league(final_league)
    nf = news_features or {}

    total_bias = 0.0
    if nf.get("news_total_over_flag"):
        total_bias += 1
    if nf.get("news_total_under_flag"):
        total_bias -= 1

    pace_bias = 0.0
    if nf.get("news_pace_high_flag"):
        pace_bias += 1
    if nf.get("news_pace_low_flag"):
        pace_bias -= 1

    base_total = base + total_bias * 3 + pace_bias * 2

    avg_line = nf.get("news_total_avg_line") or 0.0
    if avg_line > 0:
        base_total = (base_total * 0.6) + (avg_line * 0.4)

    low = base_total - 8
    high = base_total + 8
    internal_score_vector = [round(low, 1), round(base_total, 1), round(high, 1)]

    # 4) Fusion total call
    line = round(base_total * 2) / 2.0

    if total_bias > 0.25:
        direction = "OVER"
    elif total_bias < -0.25:
        direction = "UNDER"
    else:
        direction = "NEUTRAL"

    fusion_total_call = (
        f"{final_league} | {home_team} - {away_team} | "
        f"TOTAL {line:.1f} band ({low:.1f}-{high:.1f}) [{direction}]"
    )

    # News summary
    if hasattr(news_summary, "__dataclass_fields__"):
        ns_dict = asdict(news_summary)
    else:
        ns_dict = getattr(news_summary, "__dict__", {}) or {}

    total_view = ns_dict.get("total_view") or {}
    tempo_view = ns_dict.get("tempo") or {}
    injuries_view = ns_dict.get("injuries") or {}

    flags = ns_dict.get("flags") or []
    if not isinstance(flags, list):
        flags = [str(flags)]

    news_summary_text = (
        f"TOTAL: {total_view.get('consensus','NEUTRAL')}, "
        f"tempo: {tempo_view.get('pace_hint','MID')}, "
        f"flags: {','.join(flags)}"
    )

    # Debug reasons
    debug_reasons = [f"League baseline ~ {base:.1f}"]

    if avg_line:
        debug_reasons.append(f"News avg_line ~ {avg_line:.1f}")
    if nf.get("news_total_over_flag"):
        debug_reasons.append("News: OVER")
    if nf.get("news_total_under_flag"):
        debug_reasons.append("News: UNDER")
    if nf.get("news_pace_high_flag"):
        debug_reasons.append("Pace: HIGH")
    if nf.get("news_pace_low_flag"):
        debug_reasons.append("Pace: LOW")
    if injuries_view.get("impact_home") or injuries_view.get("impact_away"):
        debug_reasons.append(
            f"Injury H:{injuries_view.get('impact_home',0)} "
            f"A:{injuries_view.get('impact_away',0)}"
        )

    # 6) Internal meta
    national_flag = _national_match_flag(home_team, away_team, final_league)

    internal_meta = {
        "league": final_league,
        "date": date,
        "home_team": home_team,
        "away_team": away_team,
        "match": f"{home_team} - {away_team}",
        "match_type": "NATIONAL" if national_flag else "CLUB",
        "base_total": float(round(base_total, 1)),
        "tempo_factor": 1.0 + (pace_bias * 0.05),
        "defense_factor": 1.0 - (pace_bias * 0.03),
        "national_bonus": 0.15 if national_flag else 0.0,
        "news_features": news_features,
        "news_flags": flags,
    }

    result = {
        "engine": "FAZ-13",
        "league": final_league,
        "date": date,
        "match": f"{home_team} - {away_team}",
        "fusion_total_call": fusion_total_call,
        "internal_score_vector": internal_score_vector,
        "news_summary": news_summary_text,
        "debug_reasons": debug_reasons,
        "internal_meta": internal_meta,
        "raw_news_summary": ns_dict,
    }

    return result


# ================================================================
# Coupon placeholders
# ================================================================

def faz13_daily_coupon(*args, **kwargs):
    return {"engine": "FAZ-13", "status": "NOT_IMPLEMENTED"}


def faz13_upcoming_coupon(*args, **kwargs):
    return {"engine": "FAZ-13", "status": "NOT_IMPLEMENTED"}


def faz13_league_coupon(*args, **kwargs):
    return {"engine": "FAZ-13", "status": "NOT_IMPLEMENTED"}


def faz13_live_coupon(*args, **kwargs):
    return {"engine": "FAZ-13", "status": "NOT_IMPLEMENTED"}
