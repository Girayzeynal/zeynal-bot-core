"""Replayable FAZ13 input copies. Digests provide integrity, not source attestation."""
from copy import deepcopy
import hashlib
import json
import math
from statistics import mean
import time
from types import SimpleNamespace

from baseline_numeric_reconciliation import reconcile_team_average
from prematch_series_audit import audit_prematch_series


def canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(payload):
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class FrozenInputStore:
    def __init__(self, teams):
        self.teams = deepcopy(teams)

    def get_series(self, league, team, count):
        for item in self.teams.values():
            if item["key"] == team:
                return [SimpleNamespace(**row) for row in item["records"]][-count:]
        return []


def _validate_team(item, *, league, prediction_utc):
    captured = item["captured_at_utc"]
    if type(captured) is not int or not 0 < captured <= prediction_utc:
        raise ValueError("Input capture was unavailable before prediction")
    rows = item["records"]
    if not isinstance(rows, list) or not 6 <= len(rows) <= 1000:
        raise ValueError("Invalid input sample size")
    signatures = {}
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("home")) is not bool
                or any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k])
                       or row[k] < 0 for k in ("pts_for", "pts_against", "pace"))
                or row["pace"] <= 0):
            raise ValueError("Invalid input game statistics")
        signature = tuple(row[k] for k in ("ts_utc", "pts_for", "pts_against", "pace", "home"))
        if signature in signatures and signatures[signature] != row["source"]:
            raise ValueError("Ambiguous cross-provider input games")
        signatures[signature] = row["source"]
    store = FrozenInputStore({"team": item})
    audit = audit_prematch_series(store, league=league, team=item["key"],
                                  prediction_utc=captured)
    if audit["eligible_games"] != len(rows):
        raise ValueError("Some captured inputs were unavailable or unverified")
    return {"points_for": mean(row["pts_for"] for row in rows),
            "points_against": mean(row["pts_against"] for row in rows),
            "pace": mean(row["pace"] for row in rows)}


def capture_team_inputs(store, *, league, key, average, n_games):
    """Called by FAZ13 while loading the aggregate it actually uses."""
    if type(n_games) is not int or not 6 <= n_games <= 1000:
        raise ValueError("Invalid input sample size")
    captured = int(time.time())
    # Store aggregates use a trailing window; older retained games are not
    # model inputs. Reconcile exactly this window against the loaded means.
    records = store.get_series(league, key, n_games)
    fields = ("ts_utc", "pts_for", "pts_against", "pace", "home", "game_id",
              "source", "timestamp_precision")
    rows = [dict({name: getattr(row, name) for name in fields},
                 pace_evidence=deepcopy(getattr(row, "pace_evidence", None)))
            for row in records]
    rows.sort(key=lambda row: (row["ts_utc"], row["source"] or "", row["game_id"] or ""))
    item = dict(key=key, captured_at_utc=captured, records=rows)
    _validate_team(item, league=league, prediction_utc=captured)
    if len(rows) != n_games:
        raise ValueError("Input sample differs from loaded aggregate")
    reconcile_team_average(average, records, prediction_utc=captured)
    return item


def seal_prediction_inputs(core, home, away):
    """Seal and replay-check the two copies before exposing a bound FAZ13 output."""
    payload = dict(schema_version=1, league=core.ctx.league,
                   context={k: getattr(core.ctx, k) for k in ("date", "home", "away")},
                   prediction_ts_utc=core.meta["generated_at"], scope="FINAL_WITH_OT",
                   expected_home=core.meta["expected_home"],
                   expected_away=core.meta["expected_away"],
                   teams={"home": deepcopy(home), "away": deepcopy(away)})
    result = dict(payload=payload, sha256=digest(payload))
    validate_prediction_inputs(result, league=core.ctx.league,
        prediction_utc=core.meta["generated_at"], expected_home=core.meta["expected_home"],
        expected_away=core.meta["expected_away"])
    return result


def validate_prediction_inputs(snapshot, *, league, prediction_utc,
                               expected_home, expected_away, scope="FINAL_WITH_OT"):
    try:
        if not isinstance(snapshot, dict):
            raise ValueError("Missing original FAZ13 input snapshot")
        payload = snapshot["payload"]
        if snapshot["sha256"] != digest(payload):
            raise ValueError("Input snapshot integrity mismatch")
        if (type(payload["schema_version"]) is not int or payload["schema_version"] != 1
                or payload["league"] != league or payload["scope"] != scope
                or type(prediction_utc) is not int or prediction_utc <= 0
                or type(payload["prediction_ts_utc"]) is not int
                or payload["prediction_ts_utc"] != prediction_utc):
            raise ValueError("Input snapshot prediction identity mismatch")
        context, teams = payload["context"], payload["teams"]
        if (any(not isinstance(context.get(k), str) or not context[k].strip()
                for k in ("date", "home", "away")) or context["home"] == context["away"]
                or set(teams) != {"home", "away"}
                or any(teams[side]["key"] != context[side] for side in teams)):
            raise ValueError("Input snapshot team context mismatch")
        averages = {side: _validate_team(teams[side], league=league, prediction_utc=prediction_utc)
                    for side in teams}
        calculated = {
            "expected_home": (averages["home"]["points_for"] + averages["away"]["points_against"]) / 2,
            "expected_away": (averages["away"]["points_for"] + averages["home"]["points_against"]) / 2,
        }
        for field, expected in (("expected_home", expected_home), ("expected_away", expected_away)):
            if (type(expected) not in (int, float) or not math.isfinite(expected)
                    or type(payload[field]) not in (int, float) or not math.isfinite(payload[field])
                    or payload[field] != expected or abs(calculated[field] - expected) > 0.011):
                raise ValueError(f"Input snapshot {field} differs from prediction")
        return FrozenInputStore(teams)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid FAZ13 input snapshot") from exc
