# faz13_engine/faz13_orchestrator.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional, List, Tuple

# Optional helpers (safe imports). If missing, code still runs.
try:
    from .league_autodetect import autodetect_league  # type: ignore
except Exception:
    autodetect_league = None  # type: ignore

# ------------------------------------------------------------
# Contract types
# ------------------------------------------------------------
MarketData = Dict[str, Any]
MarketMeta = Dict[str, Any]
Faz13Result = Dict[str, Any]


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _mk_market_view(market_data: Optional[MarketData], market_meta: Optional[MarketMeta]) -> Dict[str, Any]:
    used = False
    conf = 0.0
    reason = "no_market"
    totals_line = None

    if isinstance(market_meta, dict):
        m = market_meta.get("market")
        if isinstance(m, dict):
            used = bool(m.get("used", False))
            conf = _safe_float(m.get("confidence", 0.0), 0.0)
            reason = str(m.get("reason", reason) or reason)

    if isinstance(market_data, dict):
        try:
            tl = market_data.get("totals_line", None)
            totals_line = float(tl) if tl is not None else None
        except Exception:
            totals_line = None

    if totals_line is None:
        used = False
        conf = 0.0
        if reason == "ok":
            reason = "no_line"

    conf = _clamp(conf, 0.0, 1.0)

    return {"used": used, "confidence": conf, "reason": reason, "totals_line": totals_line}


def _team_based_base_pred(league: str, home: str, away: str) -> Tuple[float, Dict[str, float], List[str]]:
    """
    Team-average PRIMARY yaklaşımı.
    Bu katmanda lig ortalaması DISABLED. Burada sadece stabil bir baseline üretilir.
    Gerçek projede buraya takım veri kaynağın (DB/API/ocr) bağlanacak.
    """
    # Şimdilik "neutral" baseline: 160-170 bandı, lig bağlamına göre mikro kaydırma
    # (buradaki sayılar placeholder; veri kaynağın bağlanınca otomatikleşecek)
    league_u = (league or "").upper()

    base = 165.0
    if "NBA" in league_u:
        base = 223.0
    elif "EUROLEAGUE" in league_u or "EL" == league_u:
        base = 160.0
    elif "TBL" in league_u or "BSL" in league_u:
        base = 161.0
    elif "CBA" in league_u:
        base = 197.0

    weights = {
        "team_avg_primary": 1.0,   # lig ortalaması yok
        "pace_filter": 0.0,
        "bench_var": 0.0,
        "garbage_time": 0.0,
        "b2b_rotation": 0.0,
        "market_hint": 0.0,
    }
    enrichment = ["TEAM_AVG_PRIMARY", "LEAGUE_AVG_DISABLED"]

    return base, weights, enrichment


def _apply_filters_and_band(base_pred: float, league: str, market_view: Dict[str, Any]) -> Tuple[float, List[int], Dict[str, float], List[str]]:
    """
    Dar bant üretimi:
    - Lig bazlı tolerans (NBA daha geniş, EL daha dar)
    - Market line varsa sadece "hint" (zorla eşitleme yok)
    """
    league_u = (league or "").upper()

    # Lig bazlı default half-range (dar bant yarıçapı)
    half_range = 6.0
    if "NBA" in league_u:
        half_range = 7.0
    elif "EUROLEAGUE" in league_u or "EL" == league_u:
        half_range = 5.5

    adjusted = base_pred
    weights = {"band_half_range": half_range, "market_nudge": 0.0}
    enrichment: List[str] = []

    # Market hint (küçük nudge): sadece confidence yüksekse
    if market_view.get("used") and market_view.get("totals_line") is not None:
        conf = float(market_view.get("confidence", 0.0) or 0.0)
        tl = float(market_view["totals_line"])
        # nudge factor: max 15% etkili, conf ile ölçeklenir
        nudge = _clamp(conf, 0.0, 1.0) * 0.15
        adjusted = (1.0 - nudge) * adjusted + nudge * tl
        weights["market_nudge"] = round(nudge, 4)
        enrichment.append("MARKET_HINT_APPLIED")

    low = int(round(adjusted - half_range))
    high = int(round(adjusted + half_range))
    return adjusted, [low, high], weights, enrichment


def _period_scenario(total_pred: float) -> Dict[str, float]:
    """
    Periyot senaryosu (toplamı dağıtır).
    Basit ama deterministik, stabil.
    """
    # 1H: %51, 2H: %49 gibi stabil bir dağılım
    h1 = total_pred * 0.51
    h2 = total_pred - h1

    # Quarter dağılımı: 1Q 26%, 2Q 25%, 3Q 25%, 4Q 24%
    q1 = total_pred * 0.26
    q2 = total_pred * 0.25
    q3 = total_pred * 0.25
    q4 = total_pred - (q1 + q2 + q3)

    return {
        "q1": round(q1, 1),
        "q2": round(q2, 1),
        "q3": round(q3, 1),
        "q4": round(q4, 1),
        "h1": round(h1, 1),
        "h2": round(h2, 1),
    }


def run_faz13_auto_pipeline(
    league: str,
    home: str,
    away: str,
    date_str: str,
    market_data: Optional[MarketData] = None,
    market_meta: Optional[MarketMeta] = None,
) -> Faz13Result:
    """
    FINAL CONTRACT:
    - Lig izolasyonu: league paramı ile bağlam kilitlenir.
    - Lig ortalaması DISABLED (team-based primary).
    - Market: sadece hint/sinyal.
    """
    ts = int(time.time())

    # optional autodetect fallback (asla override etmez, sadece enrichment)
    enrichment: List[str] = []
    if callable(autodetect_league):
        try:
            auto = autodetect_league(league, home, away)  # type: ignore
            if auto and str(auto).upper() != str(league).upper():
                enrichment.append(f"AUTO_DETECT_NOTE:{auto}")
        except Exception:
            pass

    market_view = _mk_market_view(market_data, market_meta)

    base_pred, base_weights, base_enrich = _team_based_base_pred(league, home, away)
    enrichment.extend(base_enrich)

    adjusted_pred, band, band_weights, band_enrich = _apply_filters_and_band(base_pred, league, market_view)
    enrichment.extend(band_enrich)

    periods = _period_scenario(adjusted_pred)

    # weights birleşimi (debug amaçlı)
    weights: Dict[str, Any] = {}
    weights.update(base_weights)
    weights.update(band_weights)

    result: Faz13Result = {
        "engine": "FAZ-13",
        "ts": ts,
        "league": league,
        "home": home,
        "away": away,
        "date": date_str,
        "base_pred": round(float(adjusted_pred), 1),
        "band": [int(band[0]), int(band[1])],
        "periods": periods,
        "enrichment": enrichment,
        "market": {
            "used": bool(market_view["used"]),
            "confidence": float(market_view["confidence"]),
            "reason": str(market_view["reason"]),
            "totals_line": market_view.get("totals_line"),
        },
        "weights": weights,
    }
    return result
