# faz16_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict
import math


# ============================
# DATA MODELS
# ============================

@dataclass
class LiveSnapshot:
    # period: 1..4 (NBA)
    period: int
    # seconds elapsed in current period (0..720 for NBA quarter)
    sec_elapsed_in_period: int
    # total points scored so far (home+away)
    points_total_so_far: int


@dataclass
class Faz16LiveResult:
    # Updated distribution estimates
    live_mean_total: float
    live_std_total: float

    # Drift diagnostics
    pace_delta_pct: float   # + => faster than prematch, - => slower
    mean_shift: float       # how much mean moved vs prematch sim_mean

    # Decision
    live_edge_flag: str     # STILL_NO_EDGE | LIVE_WEAK_EDGE | LIVE_EDGE
    confidence_boost: float # additive boost suggestion (0..)
    notes: str


# ============================
# HELPERS
# ============================

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _remaining_game_seconds(period: int, sec_elapsed_in_period: int) -> int:
    # NBA: 4 * 12 min = 2880 sec
    total = 4 * 12 * 60
    elapsed = (period - 1) * 12 * 60 + sec_elapsed_in_period
    return max(0, total - elapsed)


def _project_final_total(points_so_far: int, seconds_elapsed_total: int) -> float:
    # Simple pace projection: points / elapsed * total
    total_game_seconds = 4 * 12 * 60
    if seconds_elapsed_total <= 0:
        return float(points_so_far)
    return (points_so_far / seconds_elapsed_total) * total_game_seconds


def _seconds_elapsed_total(period: int, sec_elapsed_in_period: int) -> int:
    return (period - 1) * 12 * 60 + sec_elapsed_in_period


# ============================
# CORE: LIVE RECALIBRATION
# ============================

def faz16_live_recalibrate(
    prematch_sim_mean: float,
    prematch_sim_std: float,
    market_total: Optional[float],
    snapshot: LiveSnapshot,
    *,
    # Controls (safe defaults)
    early_window_min_sec: int = 6 * 60,   # 6 minutes into game
    full_q1_sec: int = 12 * 60,           # Q1 length
    drift_trigger_pct: float = 6.0,       # >= 6% pace drift => re-weight strongly
    drift_soft_pct: float = 3.0,          # <= 3% drift => keep mostly prematch
) -> Faz16LiveResult:
    """
    Uses early live scoring pace to adjust the prematch distribution.
    - Produces updated mean/std
    - Decides whether an EDGE has emerged
    """

    # Compute elapsed time in whole game
    sec_elapsed_total = _seconds_elapsed_total(snapshot.period, snapshot.sec_elapsed_in_period)
    sec_remaining = _remaining_game_seconds(snapshot.period, snapshot.sec_elapsed_in_period)

    # Hard safety: need some time on clock to avoid division noise
    if sec_elapsed_total <= 60:  # first minute is chaos
        return Faz16LiveResult(
            live_mean_total=prematch_sim_mean,
            live_std_total=prematch_sim_std,
            pace_delta_pct=0.0,
            mean_shift=0.0,
            live_edge_flag="STILL_NO_EDGE",
            confidence_boost=0.0,
            notes="LIVE: çok erken (<=60sn). Prematch dağılım korunuyor."
        )

    # Live projection of final total from current pace
    live_proj_total = _project_final_total(snapshot.points_total_so_far, sec_elapsed_total)

    # Pace delta vs prematch mean (proxy)
    # +% => game tracking above prematch expectation
    pace_delta_pct = ((live_proj_total - prematch_sim_mean) / max(1e-9, prematch_sim_mean)) * 100.0

    # Determine blending weight based on how much game is revealed + drift strength
    # Base weight grows with time (cap at end of Q1)
    q1_elapsed = min(sec_elapsed_total, full_q1_sec)
    time_weight = _clamp(q1_elapsed / full_q1_sec, 0.0, 1.0)

    # Drift weight: stronger drift => more trust in live projection
    abs_drift = abs(pace_delta_pct)
    if abs_drift >= drift_trigger_pct:
        drift_weight = 1.0
    elif abs_drift <= drift_soft_pct:
        drift_weight = 0.25
    else:
        # Linear between soft and trigger
        drift_weight = 0.25 + (abs_drift - drift_soft_pct) * (0.75 / (drift_trigger_pct - drift_soft_pct))

    # Final live influence weight
    w_live = _clamp(time_weight * drift_weight, 0.0, 1.0)

    # Updated mean: blend prematch mean with live projection
    live_mean = (1.0 - w_live) * prematch_sim_mean + w_live * live_proj_total

    # Updated std: early live reduces uncertainty a bit, but drift can increase it
    # - As time reveals info => std decreases
    # - If drift is big => std slightly increases (game script volatility)
    shrink = _clamp(1.0 - 0.25 * time_weight, 0.7, 1.0)   # up to 30% shrink by end of Q1
    inflate = 1.0 + _clamp(abs_drift / 25.0, 0.0, 0.25)   # up to +25% inflate on huge drift
    live_std = prematch_sim_std * shrink * inflate

    mean_shift = live_mean - prematch_sim_mean

    # ============================
    # LIVE EDGE DECISION
    # ============================
    if market_total is None:
        # No market => we can only output live mean band
        return Faz16LiveResult(
            live_mean_total=round(live_mean, 2),
            live_std_total=round(live_std, 2),
            pace_delta_pct=round(pace_delta_pct, 2),
            mean_shift=round(mean_shift, 2),
            live_edge_flag="STILL_NO_EDGE",
            confidence_boost=0.0,
            notes="LIVE: market yok. Sadece live projeksiyon + dağılım güncellendi."
        )

    diff_live_vs_market = abs(live_mean - market_total)

    # Thresholds scale with updated std
    weak_edge_th = live_std * 0.35
    strong_edge_th = live_std * 0.55

    if diff_live_vs_market < weak_edge_th:
        edge_flag = "STILL_NO_EDGE"
        boost = 0.0
    elif diff_live_vs_market < strong_edge_th:
        edge_flag = "LIVE_WEAK_EDGE"
        boost = 3.0  # suggested confidence bump
    else:
        edge_flag = "LIVE_EDGE"
        boost = 7.0

    # Add context notes
    direction = "OVER" if live_mean > market_total else "UNDER"
    notes = (
        f"LIVE: w_live={w_live:.2f} | proj={live_proj_total:.1f} | "
        f"mean={live_mean:.1f} vs market={market_total:.1f} => {direction} | "
        f"abs_drift={abs_drift:.1f}%"
    )

    return Faz16LiveResult(
        live_mean_total=round(live_mean, 2),
        live_std_total=round(live_std, 2),
        pace_delta_pct=round(pace_delta_pct, 2),
        mean_shift=round(mean_shift, 2),
        live_edge_flag=edge_flag,
        confidence_boost=boost,
        notes=notes
    )


# ============================
# OPTIONAL: BAND OUTPUT (for FAZ-13 style)
# ============================

def faz16_band(mean: float, std: float, sigma: float = 0.55) -> Dict[str, float]:
    """
    Returns a narrow band around mean using sigma * std.
    sigma=0.55 ~ "dar bant" (tunable)
    """
    half = std * sigma
    lo = mean - half
    hi = mean + half
    return {
        "lo": round(lo, 1),
        "hi": round(hi, 1),
        "center": round(mean, 1)
    } 


# ============================
# BACKWARD COMPATIBILITY SHIM
# ============================

def faz16_run_simulation(*args, **kwargs):
    """
    Geriye uyumluluk köprüsü.
    Eski main.py çağrılarını kırmadan
    yeni FAZ-16 live recalibrate motorunu çalıştırır.
    """
    try:
        return faz16_live_recalibrate(*args, **kwargs)
    except Exception as e:
        return {
            "error": "FAZ16_RUN_SIMULATION_FAILED",
            "detail": str(e),
        } 
