"""Versioned, replayable pace observations. Hashes detect corruption, not forgery."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import time

from providers.espn_boxscore_pace import METHOD, estimate_pace_from_summary


def _digest(snapshot):
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def capture_pace_evidence(payload, game, *, observed_at_utc, cutoff=None):
    """Capture only source fields needed to replay identity, score and pace checks."""
    estimate = estimate_pace_from_summary(payload, game, cutoff)
    if estimate is None or type(observed_at_utc) is not int:
        return None
    if not game["start_ts_utc"] < observed_at_utc <= int(time.time()):
        return None
    header = payload["header"]
    competition = header["competitions"][0]
    compact = {
        "header": {
            "id": header["id"], "season": header["season"],
            "competitions": [{
                "id": competition["id"], "date": competition["date"],
                "status": competition["status"],
                "competitors": [
                    {key: row[key] for key in ("homeAway", "score", "linescores")}
                    | {"team": {"id": row["team"]["id"]}}
                    for row in competition["competitors"]
                ],
            }],
        },
        "format": payload["format"],
        "boxscore": {"teams": [
            {"homeAway": row["homeAway"], "team": {"id": row["team"]["id"]},
             "statistics": row["statistics"]}
            for row in payload["boxscore"]["teams"]
        ]},
    }
    snapshot = deepcopy(dict(schema_version=1, observed_at_utc=observed_at_utc,
                             game=game, summary=compact))
    return dict(estimate, snapshot=snapshot, snapshot_sha256=_digest(snapshot))


def validate_pace_evidence(record, *, league, prediction_utc=None):
    """Bind stored evidence to a game's numbers and optional availability cutoff.

    Legacy sources without estimated ESPN pace retain their existing contract.
    Method-tagged records always require complete replayable observations.
    """
    evidence = getattr(record, "pace_evidence", None)
    if getattr(record, "source", None) != METHOD:
        if evidence is not None:
            raise ValueError("Pace evidence requires its declared estimation method")
        return
    try:
        if league != "NBA" or not isinstance(evidence, dict):
            raise ValueError("Missing NBA pace observation")
        snapshot = evidence["snapshot"]
        if (type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1
                or evidence["snapshot_sha256"] != _digest(snapshot)):
            raise ValueError("Pace observation integrity mismatch")
        observed = snapshot["observed_at_utc"]
        game = snapshot["game"]
        if (type(observed) is not int or not record.ts_utc < observed <= int(time.time())
                or type(record.home) is not bool or record.timestamp_precision != "exact"
                or record.game_id != game["provider_fixture_id"]
                or record.ts_utc != game["start_ts_utc"]):
            raise ValueError("Pace observation identity/time mismatch")
        if prediction_utc is not None and (
            type(prediction_utc) is not int or not observed < prediction_utc
        ):
            raise ValueError("Pace observation was unavailable before prediction")
        side, opponent = ("home", "away") if record.home else ("away", "home")
        if (record.pts_for != game[f"actual_{side}"]
                or record.pts_against != game[f"actual_{opponent}"]):
            raise ValueError("Pace observation score orientation mismatch")
        calculated = estimate_pace_from_summary(
            snapshot["summary"], game, datetime.fromtimestamp(observed, timezone.utc))
        if calculated is None or any(evidence.get(k) != v for k, v in calculated.items()):
            raise ValueError("Pace observation cannot be replayed")
        if (type(record.pace) not in (int, float) or not math.isfinite(record.pace)
                or abs(record.pace - calculated["pace"]) > 1e-9):
            raise ValueError("Stored pace differs from source calculation")
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid stored pace observation") from exc


def same_pace_observation(previous, incoming):
    """Repeated later fetches cannot overwrite the original observation time."""
    if previous is None or incoming is None:
        return previous is incoming
    old = dict(previous["snapshot"])
    new = dict(incoming["snapshot"])
    old_time = old.pop("observed_at_utc")
    new_time = new.pop("observed_at_utc")
    return old == new and new_time >= old_time


def pace_available_before(record, *, league, prediction_utc):
    try:
        validate_pace_evidence(record, league=league, prediction_utc=prediction_utc)
        return True
    except ValueError:
        return False
