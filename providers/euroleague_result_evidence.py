"""Full-clock final-score observations bound to original EuroLeague fixture and inputs."""
from copy import deepcopy
import time

from prediction_inputs import digest
from providers.euroleague_fixture_evidence import validate_fixture_evidence
from providers.euroleague_live import estimate_pace, replay_pace_evidence

IDENTITY_FIELDS = ("provider", "league", "competition_code", "season_code", "provider_fixture_id",
                   "provider_game_uuid", "game_code", "start_ts_utc", "home_team_id", "away_team_id", "phase")


def same_fixture_identity(game, original):
    return all(game.get(key) == original.get(key) for key in IDENTITY_FIELDS)


def capture_result_evidence(raw_game, stats, *, original_fixture, original_inputs, observed_at_utc):
    pace = estimate_pace(raw_game, stats, league="EUROLEAGUE", year=original_fixture["payload"]["year"],
                         observed_at_utc=observed_at_utc)
    if pace is None:
        raise ValueError("No complete, reconciled EuroLeague final box score")
    snapshot = dict(schema_version=1, observed_at_utc=observed_at_utc,
        prediction_input_sha256=original_inputs["sha256"], fixture_observation_sha256=original_fixture["sha256"],
        event=deepcopy(pace["game"]), pace_evidence=pace)
    evidence = dict(snapshot=snapshot, sha256=digest(snapshot))
    validate_result_evidence(evidence, original_fixture=original_fixture, original_inputs=original_inputs,
                             observed_at_utc=observed_at_utc)
    return evidence


def validate_result_evidence(evidence, *, original_fixture, original_inputs, observed_at_utc=None):
    try:
        snapshot = evidence["snapshot"]
        observed = snapshot["observed_at_utc"]
        if (type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1
                or evidence["sha256"] != digest(snapshot)
                or snapshot["prediction_input_sha256"] != original_inputs["sha256"]
                or snapshot["fixture_observation_sha256"] != original_fixture["sha256"]
                or type(observed) is not int or not 0 < observed <= int(time.time())
                or (observed_at_utc is not None and observed != observed_at_utc)):
            raise ValueError("EuroLeague result evidence integrity/time/binding mismatch")
        fixture = original_fixture["payload"]["fixture"]
        predicted = original_inputs["payload"]["prediction_ts_utc"]
        validate_fixture_evidence(original_fixture, fixture_id=fixture["provider_fixture_id"],
            tipoff_utc=fixture["start_ts_utc"], prediction_utc=predicted, input_snapshot=original_inputs)
        game = replay_pace_evidence(snapshot["pace_evidence"])
        if (snapshot["pace_evidence"]["observed_at_utc"] != observed or snapshot["event"] != game
                or not same_fixture_identity(game, fixture) or game["status"] != "PLAYED"
                or game["scope"] != "FINAL_WITH_OT" or game["league"] != "EUROLEAGUE"
                or not predicted < game["start_ts_utc"] < observed):
            raise ValueError("EuroLeague completed result conflicts with original fixture")
        return game
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Malformed EuroLeague result evidence") from exc


def same_result_observation(previous, incoming):
    """Ignore only observation timestamps/digests; preserve all original source facts."""
    def facts(evidence):
        snapshot = deepcopy(evidence["snapshot"])
        observed = snapshot.pop("observed_at_utc")
        pace = snapshot["pace_evidence"]
        pace.pop("observed_at_utc")
        pace["snapshot"].pop("observed_at_utc")
        pace.pop("sha256")
        return observed, snapshot
    old_time, old = facts(previous)
    new_time, new = facts(incoming)
    return old == new and new_time >= old_time
