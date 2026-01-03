from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

from league_profiles import get_league_profile


# ============================
# DATA MODELS
# ============================

@dataclass
class LiveSnapshot:
    period: int
    sec_elapsed_in_period: int
    points_total_so_far: int


@dataclass
class Faz16LiveResult:
    live_mean_total: float
    live_std_total: float
    pace_delta_pct: float
    mean_shift: float
    live_edge_flag: str
    confidence_boost: float
    notes: str


# ============================
# HELPERS
# ============================

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _game_clock(league: str) -> Tuple[int, int]:
    """
    Returns (period_count, sec_per_period).
    Defaults:
      NBA: 4 x 12m
      EUROLEAGUE/TBL/FIBA: 4 x 10m
    """
    key = (league or "").upper().strip()
    if key == "NBA":
        return 4, 12 * 60
    return 4, 10 * 60


def _seconds_elapsed_total(period: int, sec_elapsed_in_period: int, period_sec: int) -> int:
    # period is 1-indexed
    p = max(1, int(period))
    s = max(0, int(sec_elapsed_in_period))
    return (p - 1) * period_sec + min(s, period_sec)


def _project_final_total(points_so_far: int, seconds_elapsed_total: int, total_game_seconds: int) -> float:
    if seconds_elapsed_total <= 0:
        return float(points_so_far)
    return (float(points_so_far) / float(seconds_elapsed_total)) * float(total_game_seconds)


def _live_weight(seconds_elapsed_total: int, period_sec: int, pace_delta_pct: float,
                 drift_trigger_pct: float, drift_soft_pct: float) -> float:
    """
    time_weight: grows to 1 over first period
    drift_weight: grows with absolute drift
    """
    q1_elapsed = min(seconds_elapsed_total, period_sec)
    time_weight = _clamp(q1_elapsed / float(period_sec), 0.0, 1.0)

    abs_drift = abs(float(pace_delta_pct))
    if abs_drift >= drift_trigger_pct:
        drift_weight = 1.0
    elif abs_drift <= drift_soft_pct:
        drift_weight = 0.25
    else:
        drift_weight = 0.25 + (
            (abs_drift - drift_soft_pct) * (0.75 / (drift_trigger_pct - drift_soft_pct))
        )

    return _clamp(time_weight * drift_weight, 0.0, 1.0)


# ============================
# CORE: LIVE RECALIBRATION
# ============================

def faz16_live_recalibrate(
    prematch_sim_mean: float,
    prematch_sim_std: float,
    market_total: Optional[float],
    snapshot: LiveSnapshot,
    *,
    league: str = "NBA",
    early_guard_sec: int = 60,
    drift_trigger_pct: float = 6.0,
    drift_soft_pct: float = 3.0,
) -> Faz16LiveResult:
    """
    FAZ-16 LIVE RECALIBRATION (LEAGUE-AWARE)

    - Uses league clock (NBA 12m, others 10m) deterministically
    - Updates mean via weighted blend prematch vs live pace projection
    - Updates std via controlled blend:
        std_live = sqrt( (1-w)*std_pre^2 + w*std_obs^2 ) * inflate(drift)
      where std_obs is derived from early-game volatility proxy
    """

    prematch_sim_mean = float(prematch_sim_mean)
    prematch_sim_std = max(1e-6, float(prematch_sim_std))

    periods, period_sec = _game_clock(league)
    total_game_seconds = periods * period_sec

    sec_elapsed_total = _seconds_elapsed_total(snapshot.period, snapshot.sec_elapsed_in_period, period_sec)

    # Early guard
    if sec_elapsed_total <= int(early_guard_sec):
        return Faz16LiveResult(
            live_mean_total=round(prematch_sim_mean, 2),
            live_std_total=round(prematch_sim_std, 2),
            pace_delta_pct=0.0,
            mean_shift=0.0,
            live_edge_flag="STILL_NO_EDGE",
            confidence_boost=0.0,
            notes=f"LIVE: çok erken (<= {early_guard_sec}sn). Prematch korunuyor.",
        )

    # Live pace projection
    live_proj_total = _project_final_total(
        snapshot.points_total_so_far, sec_elapsed_total, total_game_seconds
    )

    pace_delta_pct = ((live_proj_total - prematch_sim_mean) / max(1e-9, prematch_sim_mean)) * 100.0

    # Weight for blending
    w = _live_weight(sec_elapsed_total, period_sec, pace_delta_pct, drift_trigger_pct, drift_soft_pct)

    # Mean update
    live_mean = (1.0 - w) * prematch_sim_mean + w * live_proj_total
    mean_shift = live_mean - prematch_sim_mean

    # ---- Std update (controlled)
    # Observed volatility proxy:
    # use per-second scoring rate variability proxy early-game:
    # std_obs scales with sqrt(time) so it doesn't explode.
    rate = float(snapshot.points_total_so_far) / max(1.0, float(sec_elapsed_total))
    # base proxy: convert rate uncertainty to total uncertainty
    std_obs = max(4.0, min(20.0, (rate * total_game_seconds) * 0.06))

    # Blend variances (Bayes-like)
    var_pre = prematch_sim_std ** 2
    var_obs = std_obs ** 2
    var_live = (1.0 - w) * var_pre + w * var_obs

    # Drift inflation (bounded)
    inflate = 1.0 + _clamp(abs(pace_delta_pct) / 25.0, 0.0, 0.25)
    live_std = (var_live ** 0.5) * inflate

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
            notes="LIVE: market yok. Tempo + dağılım güncellendi.",
        )

    market_total_f = float(market_total)
    diff = abs(live_mean - market_total_f)

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

    direction = "OVER" if live_mean > market_total_f else "UNDER"

    notes = (
        f"LIVE({league}): mean={live_mean:.1f} vs market={market_total_f:.1f} | "
        f"dir={direction} | drift={pace_delta_pct:.1f}% | std={live_std:.2f} | w={w:.2f}"
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
    half = float(std) * float(sigma)
    return {"lo": round(mean - half, 1), "hi": round(mean + half, 1), "center": round(mean, 1)}


# ============================
# BACKWARD COMPATIBILITY
# ============================

def faz16_run_simulation(*args, **kwargs):
    return faz16_live_recalibrate(*args, **kwargs) 
