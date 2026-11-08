"""Strict ESPN final-score extraction for regulation-only calibration.

Parsing does not write to the prediction ledger. Only completed games with
four valid quarter scores on both sides are accepted; overtime is excluded.
"""
from __future__ import annotations


def parse_espn_regulation_final(event: object) -> dict | None:
    if not isinstance(event, dict):
        return None
    game_id = event.get("id")
    if isinstance(game_id, bool) or not isinstance(game_id, (str, int)) or not str(game_id).strip():
        return None
    status = event.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("type"), dict):
        return None
    state = status["type"]
    if state.get("completed") is not True or state.get("name") != "STATUS_FINAL":
        return None
    competitions = event.get("competitions")
    if not isinstance(competitions, list) or len(competitions) != 1:
        return None
    competitors = competitions[0].get("competitors") if isinstance(competitions[0], dict) else None
    if not isinstance(competitors, list) or len(competitors) != 2:
        return None
    totals = {}
    full = {}
    for team in competitors:
        if not isinstance(team, dict) or team.get("homeAway") not in ("home", "away"):
            return None
        side = team["homeAway"]
        if side in totals:
            return None
        lines = team.get("linescores")
        if not isinstance(lines, list) or len(lines) < 4:
            return None
        values = []
        for row in lines:
            if not isinstance(row, dict):
                return None
            value = row.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or int(value) != value:
                return None
            values.append(int(value))
        score = team.get("score")
        if isinstance(score, bool) or not isinstance(score, (str, int)) or not str(score).isdigit():
            return None
        score = int(score)
        if sum(values) != score:
            return None
        totals[side] = sum(values[:4])
        full[side] = score
    if set(totals) != {"home", "away"}:
        return None
    return {"provider": "ESPN", "provider_fixture_id": str(game_id),
            "scope": "REGULATION_ONLY", "home": totals["home"], "away": totals["away"],
            "has_overtime": any(len(t["linescores"]) > 4 for t in competitors),
            "final_with_ot_home": full["home"], "final_with_ot_away": full["away"]}
