"""
FAZ-5 Heavy Engine – Router
Kupon modlarının tek giriş noktası.
"""

from .engine_core import calculate_prediction


def run_faz5(mode: str, raw_games):
    if not raw_games:
        return []

    results = []

    for g in raw_games:
        base = calculate_prediction(g)

        result = {
            "mode": mode,
            "home": g.get("home", "TEAM-A"),
            "away": g.get("away", "TEAM-B"),
            "predicted_total": base["predicted_total"],
            "predicted_pace": base["predicted_pace"],
            "predicted_winner": base["predicted_winner"],
            "confidence": base["confidence"],
            "note": base["note"],
        }

        results.append(result)

    return results
