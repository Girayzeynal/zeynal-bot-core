"""Deterministic, fail-closed evidence gate for NBA pregame forecasts.

This module assesses evidence quality, not betting profitability or win probability.
It does not fetch data, write files, or manufacture missing observations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceAssessment:
    status: str
    reasons: tuple[str, ...]
    score: int


def assess_pregame_evidence(
    *, fixture_verified: bool, tipoff_verified: bool,
    data_observed_utc: int | None, prediction_utc: int,
    tipoff_utc: int | None, sample_home: int,
    sample_away: int, lineup_confirmed: bool,
    market_observed_utc: int | None = None,
    max_data_age_seconds: int = 86400,
    max_market_age_seconds: int = 3600,
    min_sample: int = 10,
) -> EvidenceAssessment:
    """Block unverified identity/time; flag stale or thin evidence separately.

    A score is an operational completeness index (0-100), not a calibrated
    confidence level. No recommendation is authorized by this gate.
    """
    if type(prediction_utc) is not int or prediction_utc <= 0:
        raise ValueError("prediction_utc must be a positive integer epoch")
    if any(type(v) is not int or v < 0 for v in (max_data_age_seconds, max_market_age_seconds, min_sample)):
        raise ValueError("thresholds must be nonnegative integers")
    reasons = []
    blockers = []
    if fixture_verified is not True:
        blockers.append("UNVERIFIED_FIXTURE")
    if tipoff_verified is not True or type(tipoff_utc) is not int or tipoff_utc <= prediction_utc:
        blockers.append("UNVERIFIED_FUTURE_TIPOFF")
    if type(data_observed_utc) is not int or not 0 <= prediction_utc - data_observed_utc <= max_data_age_seconds:
        reasons.append("STALE_OR_MISSING_TEAM_DATA")
    if type(sample_home) is not int or type(sample_away) is not int or min(sample_home, sample_away) < min_sample:
        reasons.append("INSUFFICIENT_SAMPLE")
    if lineup_confirmed is not True:
        reasons.append("UNCONFIRMED_LINEUP")
    if type(market_observed_utc) is not int or not 0 <= prediction_utc - market_observed_utc <= max_market_age_seconds:
        reasons.append("STALE_OR_MISSING_MARKET")
    if blockers:
        return EvidenceAssessment("BLOCKED", tuple(blockers + reasons), 0)
    score = max(0, 100 - 20 * len(reasons))
    return EvidenceAssessment("CAUTION" if reasons else "EVIDENCE_COMPLETE", tuple(reasons), score)
