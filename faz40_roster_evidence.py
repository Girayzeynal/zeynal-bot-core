"""FAZ40 fail-closed roster/lineup evidence gate (offline; no provider calls)."""
from datetime import datetime, timezone
import hashlib
import json


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def seal_roster_observation(*, fixture_id, observed_at_utc, source, players,
                            starting_five=None, status="UNCONFIRMED"):
    """Never promote an inferred lineup to a confirmed provider announcement."""
    if not isinstance(fixture_id, str) or not fixture_id.strip():
        raise ValueError("Missing fixture identity")
    if type(observed_at_utc) is not int or observed_at_utc <= 0:
        raise ValueError("Invalid observation time")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Missing roster source")
    if status not in ("UNCONFIRMED", "CONFIRMED"):
        raise ValueError("Invalid lineup status")
    if not isinstance(players, list) or any(not isinstance(p, str) or not p.strip() for p in players):
        raise ValueError("Invalid roster")
    if len(players) != len(set(players)):
        raise ValueError("Duplicate roster player")
    if starting_five is not None:
        if (not isinstance(starting_five, list) or len(starting_five) != 5
                or any(not isinstance(p, str) or p not in players for p in starting_five)
                or len(set(starting_five)) != 5):
            raise ValueError("Invalid starting five")
    if status == "CONFIRMED" and starting_five is None:
        raise ValueError("Confirmed lineup requires five named players")
    payload = dict(schema_version=1, fixture_id=fixture_id, observed_at_utc=observed_at_utc,
                   source=source, players=players, starting_five=starting_five, status=status)
    return dict(payload=payload, sha256=hashlib.sha256(_canonical(payload).encode()).hexdigest())


def validate_roster_observation(evidence, *, fixture_id, prediction_utc, tipoff_utc,
                                require_confirmed=False):
    if type(prediction_utc) is not int or type(tipoff_utc) is not int:
        raise ValueError("Invalid prediction/tipoff time")
    try:
        payload = evidence["payload"]
        rebuilt = seal_roster_observation(
            fixture_id=payload["fixture_id"], observed_at_utc=payload["observed_at_utc"],
            source=payload["source"], players=payload["players"],
            starting_five=payload["starting_five"], status=payload["status"])
        if rebuilt != evidence or payload["fixture_id"] != fixture_id:
            raise ValueError("Roster evidence integrity or fixture mismatch")
        if not 0 < payload["observed_at_utc"] <= prediction_utc < tipoff_utc:
            raise ValueError("Roster observation was not available before prediction")
        if require_confirmed and payload["status"] != "CONFIRMED":
            raise ValueError("Unconfirmed lineup cannot be used as confirmed")
        return payload
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed roster evidence") from exc
