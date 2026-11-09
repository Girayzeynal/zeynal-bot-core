"""Evidence-gated basketball scenario inputs.

No imputed injuries, player stats, possession counts, or probabilities.
Use this as a validation boundary before simulation and calibration.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Optional


@dataclass(frozen=True)
class Observation:
    value: float
    source: str
    observed_at_utc: int
    fixture_start_utc: int
    unit: str

    def validate(self, *, prediction_at_utc: int) -> None:
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool) or not isfinite(self.value):
            raise ValueError("invalid numeric observation")
        if not self.source or not self.source.strip():
            raise ValueError("missing observation source")
        if self.unit not in {"points", "possessions", "minutes", "percentage", "count", "rating"}:
            raise ValueError("unsupported unit")
        if not all(type(x) is int for x in (self.observed_at_utc, self.fixture_start_utc, prediction_at_utc)):
            raise ValueError("timestamps must be integer UTC seconds")
        if not (0 < self.observed_at_utc <= prediction_at_utc < self.fixture_start_utc):
            raise ValueError("observation not available strictly before tipoff")


@dataclass(frozen=True)
class ScenarioInput:
    league: str
    fixture_id: str
    prediction_at_utc: int
    fixture_start_utc: int
    home: str
    away: str
    home_points_for: Observation
    home_points_against: Observation
    away_points_for: Observation
    away_points_against: Observation
    pace: Optional[Observation] = None
    lineup_evidence: Optional[str] = None
    injury_evidence: Optional[str] = None

    def validate(self) -> dict:
        if not all(isinstance(x, str) and x.strip() for x in
                   (self.league, self.fixture_id, self.home, self.away)):
            raise ValueError("missing fixture identity")
        if self.home == self.away:
            raise ValueError("home and away must differ")
        if type(self.prediction_at_utc) is not int or type(self.fixture_start_utc) is not int:
            raise ValueError("invalid fixture timestamps")
        if not 0 < self.prediction_at_utc < self.fixture_start_utc:
            raise ValueError("prediction must precede fixture")
        for observation in (self.home_points_for, self.home_points_against,
                            self.away_points_for, self.away_points_against):
            observation.validate(prediction_at_utc=self.prediction_at_utc)
            if observation.fixture_start_utc != self.fixture_start_utc or observation.unit != "points":
                raise ValueError("incompatible points observation")
        if self.pace is not None:
            self.pace.validate(prediction_at_utc=self.prediction_at_utc)
            if self.pace.fixture_start_utc != self.fixture_start_utc or self.pace.unit != "possessions":
                raise ValueError("invalid pace evidence")
        return {
            "fixture_id": self.fixture_id,
            "prediction_at_utc": self.prediction_at_utc,
            "base_projection": {
                "home": (self.home_points_for.value + self.away_points_against.value) / 2,
                "away": (self.away_points_for.value + self.home_points_against.value) / 2,
            },
            "pace_available": self.pace is not None,
            "lineup_available": bool(self.lineup_evidence),
            "injury_available": bool(self.injury_evidence),
            "scenario_probabilities_calibrated": False,
            "decision_quality": "INSUFFICIENT_FOR_FULL_SCENARIO_MODEL",
        }
