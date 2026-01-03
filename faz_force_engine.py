from typing import Dict, Tuple
from config.force_mode import DEFAULT_HANDICAP, NBA_1H_RATIO, NBA_Q_RATIOS

def force_distribution(
    total: int,
    home_mu: float,
    away_mu: float,
    market_ref: float | None,
    sigma: float,
) -> Dict[str, any]:
    # --- takım payları
    s = home_mu + away_mu
    home_share = home_mu / s if s > 0 else 0.5

    home_score = round(total * home_share)
    away_score = total - home_score

    # --- alt / üst
    ref = market_ref if market_ref is not None else total
    direction = "OVER" if total >= ref else "UNDER"

    # --- ilk yarı
    first_half = round(total * NBA_1H_RATIO)
    second_half = total - first_half

    # --- periyotlar
    q1 = round(total * NBA_Q_RATIOS[0])
    q2 = round(total * NBA_Q_RATIOS[1])
    q3 = round(total * NBA_Q_RATIOS[2])
    q4 = total - (q1 + q2 + q3)

    # --- handikap
    diff = home_score - away_score
    if diff > DEFAULT_HANDICAP:
        handicap_winner = "HOME_-5.5"
    else:
        handicap_winner = "AWAY_+5.5"

    # --- güven (zorunlu)
    confidence = min(80, max(45, int(45 + abs(total - ref) / max(1, sigma) * 18)))
    risk = "LOW" if confidence > 65 else "MID" if confidence > 55 else "HIGH"

    return {
        "total": total,
        "direction": direction,
        "teams": {
            "home": home_score,
            "away": away_score,
        },
        "halves": {
            "1H": first_half,
            "2H": second_half,
        },
        "quarters": {
            "1Q": q1,
            "2Q": q2,
            "3Q": q3,
            "4Q": q4,
        },
        "handicap": handicap_winner,
        "confidence": confidence,
        "risk": risk,
    }
