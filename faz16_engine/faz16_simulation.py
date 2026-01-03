from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict


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
    pace_delta_pct: float
    mean_shift: float

    # Decision
    live_edge_flag: str     # STILL_NO_EDGE | LIVE_WEAK_EDGE | LIVE_EDGE
    confidence_boost: float
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


def _seconds_elapsed_total(period: int, sec_elapsed_in_period: int) -> int:
    return (period - 1) * 12 * 60 + sec_elapsed_in_period


def _project_final_total(points_so_far: int, seconds_elapsed_total: int) -> float:
    # Simple pace projection
    total_game_seconds = 4 * 12 * 60
    if seconds_elapsed_total <= 0:
        return float(points_so_far)
    return (points_so_far / seconds_elapsed_total) * total_game_seconds


# ============================
# CORE: LIVE RECALIBRATION
# ============================

def faz16_live_recalibrate(
    prematch_sim_mean: float,
    prematch_sim_std: float,
    market_total: Optional[float],
    snapshot: LiveSnapshot,
    *,
    early_window_min_sec: int = 6 * 60,
    full_q1_sec: int = 12 * 60,
    drift_trigger_pct: float = 6.0,
    drift_soft_pct: float = 3.0,
) -> Faz16LiveResult:
    """
    FAZ-16 FULL LIVE ENGINE

    - Tempo sapmasını okur
    - Prematch dağılımını canlı veriye göre kaydırır
    - Std shrink / inflate uygular
    - Market varsa LIVE EDGE üretir
    """

    sec_elapsed_total = _seconds_elapsed_total(
        snapshot.period, snapshot.sec_elapsed_in_period
    )

    # future gating için tutulur (kaldırma)
    _ = _remaining_game_seconds(snapshot.period, snapshot.sec_elapsed_in_period)
    _ = early_window_min_sec

    # Erken koruma (ilk 60 saniye)
    if sec_elapsed_total <= 60:
        return Faz16LiveResult(
            live_mean_total=prematch_sim_mean,
            live_std_total=prematch_sim_std,
            pace_delta_pct=0.0,
            mean_shift=0.0,
            live_edge_flag="STILL_NO_EDGE",
            confidence_boost=0.0,
            notes="LIVE: çok erken (<=60sn). Prematch dağılım korunuyor.",
        )

    # Live tempo projeksiyonu
    live_proj_total = _project_final_total(
        snapshot.points_total_so_far, sec_elapsed_total
    )

    pace_delta_pct = (
        (live_proj_total - prematch_sim_mean)
        / max(1e-9, prematch_sim_mean)
    ) * 100.0

    # Zaman ağırlığı
    q1_elapsed = min(sec_elapsed_total, full_q1_sec)
    time_weight = _clamp(q1_elapsed / full_q1_sec, 0.0, 1.0)

    # Drift ağırlığı
    abs_drift = abs(pace_delta_pct)
    if abs_drift >= drift_trigger_pct:
        drift_weight = 1.0
    elif abs_drift <= drift_soft_pct:
        drift_weight = 0.25
    else:
        drift_weight = 0.25 + (
            (abs_drift - drift_soft_pct)
            * (0.75 / (drift_trigger_pct - drift_soft_pct))
        )

    w_live = _clamp(time_weight * drift_weight, 0.0, 1.0)

    # Mean kaydırma
    live_mean = (
        (1.0 - w_live) * prematch_sim_mean
        + w_live * live_proj_total
    )

    # Std güncelleme (shrink + inflate)
    shrink = _clamp(1.0 - 0.25 * time_weight, 0.7, 1.0)
    inflate = 1.0 + _clamp(abs_drift / 25.0, 0.0, 0.25)
    live_std = prematch_sim_std * shrink * inflate

    mean_shift = live_mean - prematch_sim_mean

    # ============================
    # LIVE EDGE DECISION
    # ============================

    if market_total is None:
        return Faz16LiveResult(
            live_mean_total=round(live_mean, 2),
            live_std_total=round(live_std, 2),
            pace_delta_pct=round(pace_delta_pct, 2),
            mean_shift=round(mean_shift, 2),
            live_edge_flag="STILL_NO_EDGE",
            confidence_boost=0.0,
            notes="LIVE: market yok. Sadece tempo + dağılım güncellendi.",
        )

    diff = abs(live_mean - market_total)

    weak_th = live_std * 0.35
    strong_th = live_std * 0.55

    if diff < weak_th:
        edge_flag = "STILL_NO_EDGE"
        boost = 0.0
    elif diff < strong_th:
        edge_flag = "LIVE_WEAK_EDGE"
        boost = 3.0
    else:
        edge_flag = "LIVE_EDGE"
        boost = 7.0

    direction = "OVER" if live_mean > market_total else "UNDER"

    notes = (
        f"LIVE: mean={live_mean:.1f} vs market={market_total:.1f} | "
        f"dir={direction} | drift={pace_delta_pct:.1f}% | "
        f"std={live_std:.2f}"
    )

    return Faz16LiveResult(
        live_mean_total=round(live_mean, 2),
        live_std_total=round(live_std, 2),
        pace_delta_pct=round(pace_delta_pct, 2),
        mean_shift=round(mean_shift, 2),
        live_edge_flag=edge_flag,
        confidence_boost=float(boost),
        notes=notes,
    )


# ============================
# OPTIONAL: BAND OUTPUT
# ============================

def faz16_band(mean: float, std: float, sigma: float = 0.55) -> Dict[str, float]:
    half = std * sigma
    return {
        "lo": round(mean - half, 1),
        "hi": round(mean + half, 1),
        "center": round(mean, 1),
    }


# ============================
# BACKWARD COMPATIBILITY
# ============================

def faz16_run_simulation(*args, **kwargs):
    """
    Legacy entrypoint.
    main.py çağrılarını kırmaz.
    """
    return faz16_live_recalibrate(*args, **kwargs) 
