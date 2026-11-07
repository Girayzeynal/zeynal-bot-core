"""Explicit prematch lineup uncertainty contract; no guessed official starters.

This module does not fetch rosters or modify projections. Its output is a
validated input to a future rotation-aware simulation integration.
"""
from dataclasses import dataclass
from enum import Enum


class LineupStatus(str, Enum):
    OFFICIAL = "OFFICIAL"
    PROJECTED = "PROJECTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class LineupAssessment:
    status: LineupStatus
    starters: tuple[str, ...]
    excluded: tuple[str, ...]
    uncertain: tuple[str, ...]
    observed_at_utc: int | None
    source: str | None


def assess_lineup(*, eligible, excluded=(), uncertain=(), starters=None,
                  official=False, observed_at_utc=None, source=None,
                  prediction_utc=None):
    """Reject false certainty and post-prediction observations.

    A missing lineup is not a failure. Projected starters are explicitly
    marked PROJECTED and must not be described as confirmed.
    """
    if type(official) is not bool:
        raise ValueError("official must be boolean")
    if prediction_utc is not None and (type(prediction_utc) is not int or prediction_utc <= 0):
        raise ValueError("invalid prediction timestamp")
    if observed_at_utc is not None and (type(observed_at_utc) is not int or observed_at_utc <= 0):
        raise ValueError("invalid observation timestamp")
    if observed_at_utc is not None and prediction_utc is not None and observed_at_utc > prediction_utc:
        raise ValueError("post-prediction lineup evidence is forbidden")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise ValueError("invalid source")
    def names(items):
        if isinstance(items, (str, bytes)) or items is None:
            raise ValueError("player collection required")
        result = tuple(items)
        if any(not isinstance(x, str) or not x.strip() for x in result) or len(set(result)) != len(result):
            raise ValueError("invalid or duplicate player identity")
        return result
    available = names(eligible)
    out = names(excluded)
    maybe = names(uncertain)
    if set(out) & set(available) or not set(maybe) <= set(available):
        raise ValueError("roster status conflict")
    five = () if starters is None else names(starters)
    if five and (len(five) != 5 or not set(five) <= set(available)):
        raise ValueError("starters must be five eligible players")
    if official:
        if len(five) != 5 or not source or observed_at_utc is None:
            raise ValueError("official lineup requires five starters and timed source")
        if set(five) & set(maybe):
            raise ValueError("official starters cannot remain uncertain")
    status = (LineupStatus.OFFICIAL if official else
              LineupStatus.PROJECTED if five else LineupStatus.UNAVAILABLE)
    return LineupAssessment(status, five, out, maybe, observed_at_utc, source)
