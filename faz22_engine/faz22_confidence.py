from typing import Dict

def combine_confidence(var_conf: float, hist: Dict[str, float]) -> float:
    if hist.get("n", 0) < 10:
        return round(max(0.01, min(0.99, var_conf)), 3)

    hit_rate = float(hist.get("hit_rate", 0.0))
    mae = float(hist.get("mae", 0.0))

    hist_conf = hit_rate
    mae_penalty = min(0.2, max(0.0, mae / 100.0))
    hist_conf = max(0.01, hist_conf - mae_penalty)

    final = 0.6 * hist_conf + 0.4 * var_conf
    return round(max(0.01, min(0.99, final)), 3)
