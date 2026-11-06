"""FAZ40 historical quarter features with strict point-in-time and scope checks.

Only archived matches completed and observed before the requested cutoff are
eligible. This module does not claim empirical model calibration.
"""
import math
from statistics import mean


def quarter_history_features(rows, *, cutoff_utc, league, team, min_games=5):
    if type(cutoff_utc) is not int or cutoff_utc <= 0:
        raise ValueError("Invalid point-in-time cutoff")
    if not isinstance(league, str) or not league.strip() or not isinstance(team, str) or not team.strip():
        raise ValueError("Missing league/team identity")
    if type(min_games) is not int or min_games < 2:
        raise ValueError("Invalid minimum sample")
    if not isinstance(rows, list):
        raise ValueError("Invalid historical rows")

    eligible = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed historical game")
        if row.get("league") != league or row.get("team") != team:
            raise ValueError("Cross-league/team historical contamination")
        game_id = row.get("game_id")
        ended = row.get("ended_at_utc")
        observed = row.get("observed_at_utc")
        if (not isinstance(game_id, str) or not game_id.strip()
                or type(ended) is not int or type(observed) is not int
                or not 0 < ended <= observed <= cutoff_utc):
            raise ValueError("Historical game unavailable at cutoff")
        if game_id in seen:
            raise ValueError("Duplicate historical fixture")
        seen.add(game_id)
        if row.get("score_scope") != "REGULATION_ONLY":
            raise ValueError("Historical quarter score scope is not regulation")
        quarters = row.get("quarters")
        if (not isinstance(quarters, list) or len(quarters) != 4
                or any(type(q) is not int or q < 0 for q in quarters)):
            raise ValueError("Missing or invalid quarter scores")
        eligible.append((ended, game_id, quarters))

    eligible.sort(key=lambda item: (item[0], item[1]))
    if len(eligible) < min_games:
        raise ValueError("Insufficient verified quarter history")
    # Last min_games at cutoff: deterministic and replayable.
    sample = eligible[-min_games:]
    means = [mean(item[2][i] for item in sample) for i in range(4)]
    halves = [means[0] + means[1], means[2] + means[3]]
    return {
        "league": league, "team": team, "cutoff_utc": cutoff_utc,
        "sample_games": len(sample), "score_scope": "REGULATION_ONLY",
        "quarter_means": means, "first_half_mean": halves[0],
        "second_half_mean": halves[1], "second_half_delta": halves[1] - halves[0],
        "regulation_total_mean": sum(means),
        "calibration_status": "NOT_ESTABLISHED",
    }
