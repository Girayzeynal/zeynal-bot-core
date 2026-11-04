"""Point-in-time baseline evidence audit for canonical NBA projections.

A current aggregate baseline is not historical proof. This audit requires
individual game identities and exact provider timestamps before prediction.
It does not assert independent authenticity of the provider response.
"""
from __future__ import annotations

from typing import Any
from providers.pace_evidence import pace_available_before, validate_series_scope


def audit_prematch_series(
    store: Any, *, league: str, team: str,
    prediction_utc: int, min_games: int = 6,
) -> dict:
    if not isinstance(league, str) or not league.strip():
        raise ValueError("League is required")
    if not isinstance(team, str) or not team.strip():
        raise ValueError("Team is required")
    if type(prediction_utc) is not int or prediction_utc <= 0:
        raise ValueError("Invalid prediction timestamp")
    if type(min_games) is not int or min_games < 1:
        raise ValueError("Invalid minimum sample")
    if not callable(getattr(store, "get_series", None)):
        raise TypeError("Baseline series store required")
    # Fetch the entire retained series, not just the most recent N rows.
    records = store.get_series(league, team, 100000)
    if not isinstance(records, list) or len(records) < min_games:
        raise ValueError("Insufficient recorded game evidence")
    validate_series_scope(records)
    identities = set()
    eligible = []
    for row in records:
        ts = getattr(row, "ts_utc", None)
        game_id = getattr(row, "game_id", None)
        source = getattr(row, "source", None)
        precision = getattr(row, "timestamp_precision", None)
        if (type(ts) is not int or ts <= 0 or ts >= prediction_utc
                or precision != "exact"
                or not isinstance(game_id, str) or not game_id.strip()
                or not isinstance(source, str) or not source.strip()
                or source == "MANUAL_BASELINE"
                or not pace_available_before(row, league=league, team=team, prediction_utc=prediction_utc)):
            # A retained game dated after prediction is excluded, not used.
            continue
        identity = (source, game_id)
        if identity in identities:
            raise ValueError("Duplicate provider game identity")
        identities.add(identity)
        eligible.append(row)
    if len(eligible) < min_games:
        raise ValueError("Insufficient pre-prediction exact-time game evidence")
    # Avoid treating identical observations from different providers as two games.
    checker = getattr(store, "_ambiguous_cross_provider_games", None)
    if callable(checker) and checker(eligible):
        raise ValueError("Ambiguous cross-provider observations")
    return {
        "league": league,
        "team": team,
        "eligible_games": len(eligible),
        "latest_game_ts_utc": max(row.ts_utc for row in eligible),
        "sources": sorted({row.source for row in eligible}),
    }
