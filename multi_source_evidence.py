"""Multi-provider evidence reconciliation; no network calls or silent averaging.

Source attestations and independence must be verified by upstream adapters.
A digest proves payload integrity, not that the source is truthful.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Observation:
    provider: str
    independent_group: str
    fixture_id: str
    field: str
    value: float
    observed_at_utc: int
    source_url: str


@dataclass(frozen=True)
class Resolution:
    status: str
    value: float | None
    providers: tuple[str, ...]
    reasons: tuple[str, ...]


def reconcile(observations, *, fixture_id: str, field: str,
              prediction_utc: int, max_age_seconds: int,
              tolerance: float = 0.0, min_independent_groups: int = 2) -> Resolution:
    """Accept a numeric field only with fresh independent corroboration.

    Conflicting fresh values are quarantined; no winner is guessed.
    """
    if (not isinstance(fixture_id, str) or not fixture_id.strip()
            or not isinstance(field, str) or not field.strip()
            or type(prediction_utc) is not int or prediction_utc <= 0
            or type(max_age_seconds) is not int or max_age_seconds < 0
            or type(min_independent_groups) is not int or min_independent_groups < 2
            or isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance) or tolerance < 0):
        raise ValueError("Invalid reconciliation configuration")
    accepted = []
    rejected = []
    for item in observations:
        if not isinstance(item, Observation):
            rejected.append("INVALID_OBSERVATION")
            continue
        if (not item.provider.strip() or not item.independent_group.strip()
                or not item.source_url.startswith(("https://",))
                or item.fixture_id != fixture_id or item.field != field
                or type(item.observed_at_utc) is not int
                or not 0 <= prediction_utc - item.observed_at_utc <= max_age_seconds
                or type(item.value) not in (int, float)
                or not math.isfinite(item.value)):
            rejected.append("UNVERIFIED_OR_STALE_OBSERVATION")
            continue
        accepted.append(item)
    # Multiple feeds sharing one upstream source do not constitute consensus.
    groups = {}
    for item in accepted:
        groups.setdefault(item.independent_group, []).append(item)
    if any(max(x.value for x in items) - min(x.value for x in items) > tolerance
           for items in groups.values()):
        return Resolution("CONFLICT", None, tuple(sorted({x.provider for x in accepted})),
                          ("INTRA_SOURCE_CONFLICT",))
    if len(groups) < min_independent_groups:
        return Resolution("INSUFFICIENT_EVIDENCE", None,
                          tuple(sorted({x.provider for x in accepted})),
                          ("INSUFFICIENT_INDEPENDENT_SOURCES",))
    values = [items[0].value for items in groups.values()]
    if max(values) - min(values) > tolerance:
        return Resolution("CONFLICT", None, tuple(sorted({x.provider for x in accepted})),
                          ("CROSS_SOURCE_CONFLICT",))
    return Resolution("VERIFIED_CONSENSUS", values[0],
                      tuple(sorted({x.provider for x in accepted})), ())
