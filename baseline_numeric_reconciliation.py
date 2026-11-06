"""Fail-closed numerical reconciliation of a FAZ13 team average and historical rows.

This proves numerical consistency only, not that rows were available to the
model when it originally ran. A separate immutable input snapshot is needed.
"""
import math
from statistics import mean
from providers.pace_evidence import pace_available_before


def reconcile_team_average(core_average, records, *, prediction_utc, tolerance=0.01, league="NBA", team=None):
    if type(prediction_utc) is not int or prediction_utc <= 0:
        raise ValueError("Invalid prediction timestamp")
    if not isinstance(records, list) or len(records) < 6:
        raise ValueError("Insufficient historical rows")
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Invalid tolerance")
    if any(type(getattr(row, "ts_utc", None)) is not int
           or not 0 < row.ts_utc < prediction_utc
           or getattr(row, "timestamp_precision", None) != "exact"
           for row in records):
        raise ValueError("Historical rows are not point-in-time exact")
    if any(not pace_available_before(row, league=league, team=team, prediction_utc=prediction_utc)
           for row in records):
        raise ValueError("Historical pace evidence was unavailable before prediction")
    fields = (("points_for", "pts_for"), ("points_against", "pts_against"), ("pace", "pace"))
    for target_field, record_field in fields:
        target = getattr(core_average, target_field, None)
        values = [getattr(row, record_field, None) for row in records]
        if (type(target) not in (int, float) or not math.isfinite(target)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
            raise ValueError("Missing finite numerical baseline evidence")
        if target < 0 or any(v < 0 for v in values) or (target_field == 'pace' and
                (target == 0 or any(v == 0 for v in values))):
            raise ValueError("Nonphysical numerical baseline evidence")
        actual = mean(values)
        if abs(actual - target) > tolerance:
            raise ValueError(f"FAZ13 {target_field} differs from historical game mean")
    return True
