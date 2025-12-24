from typing import Dict, Any
import math

def _round_half(x: float) -> float:
    return round(x * 2) / 2

def run_faz13_auto_pipeline(
    league: str,
    home: str,
    away: str,
    date_str: str,
    market_data: Dict[str,Any] | None = None,
    extra_inputs: Dict[str,Any] | None = None
) -> Dict[str,Any]:
    """
    BASE = SADECE TAKIM BASELINE
    Market burada ASLA base üretmez.
    """

    ctx = extra_inputs or {}
    team = ctx.get("team_stats", {})

    home_avg = float(team.get("home_avg_for", 111.0))
    away_avg = float(team.get("away_avg_for", 111.0))

    tempo = float(team.get("tempo", 1.0))
    inj = int(ctx.get("injuries", {}).get("count", 0))

    base_pred = _round_half((home_avg + away_avg) * tempo)
    if inj > 0:
        base_pred = _round_half(base_pred - min(3.0, inj * 0.8))

    band = [int(base_pred - 12), int(base_pred + 12)]

    return {
        "league": league,
        "base_pred": base_pred,
        "band": band,
        "market": market_data or {},
        "confidence": 0.92,
        "team_baseline": {
            "home_avg_for": home_avg,
            "away_avg_for": away_avg,
            "tempo": tempo,
            "injuries": inj
        }
    } 
