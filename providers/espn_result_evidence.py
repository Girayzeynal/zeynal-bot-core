"""Replayable final-score observations; local hashes are not source signatures."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import time

from providers.espn_completed_event import parse_completed_nba_event


def result_digest(snapshot):
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_final_summary(payload, observed_at_utc):
    try:
        if type(observed_at_utc) is not int or not 0 < observed_at_utc <= int(time.time()):
            return None
        header = payload["header"]
        if len(header["competitions"]) != 1:
            return None
        competition = header["competitions"][0]
        if header["id"] != competition["id"]:
            return None
        # If both status locations exist, neither may contradict a final.
        for status in (header.get("status"), competition.get("status")):
            if status is not None and (status["type"].get("completed") is not True
                    or status["type"].get("state") not in ("post", "completed")):
                return None
        return parse_completed_nba_event(dict(header, date=competition["date"]),
                    datetime.fromtimestamp(observed_at_utc, timezone.utc))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def capture_result_evidence(payload, *, observed_at_utc, input_sha256,
                            home_team_id, away_team_id):
    parsed = parse_final_summary(payload, observed_at_utc)
    if parsed is None:
        raise ValueError("No consistent completed result")
    if (parsed["home_team_id"] != home_team_id or parsed["away_team_id"] != away_team_id
            or home_team_id == away_team_id):
        raise ValueError("Completed result team orientation conflicts")
    header, competition = payload["header"], payload["header"]["competitions"][0]
    compact_header = {"id": header["id"], "competitions": [{
        "id": competition["id"], "date": competition["date"],
        "competitors": [{"homeAway": row["homeAway"], "score": row["score"],
                         "team": {"id": row["team"]["id"]}}
                        for row in competition["competitors"]],
    }]}
    if "status" in header:
        compact_header["status"] = header["status"]
    if "status" in competition:
        compact_header["competitions"][0]["status"] = competition["status"]
    snapshot = deepcopy(dict(schema_version=1, observed_at_utc=observed_at_utc,
        prediction_input_sha256=input_sha256, event=parsed,
        home_team_id=home_team_id, away_team_id=away_team_id,
        summary={"header": compact_header},
        source_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="
                   + parsed["provider_fixture_id"]))
    evidence = dict(snapshot=snapshot, sha256=result_digest(snapshot))
    validate_result_evidence(evidence, parsed, observed_at_utc, input_sha256)
    return evidence


def validate_result_evidence(evidence, event, observed_at_utc, input_sha256):
    try:
        snapshot = evidence["snapshot"]
        if (type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1
                or evidence["sha256"] != result_digest(snapshot)
                or type(observed_at_utc) is not int or snapshot["observed_at_utc"] != observed_at_utc
                or snapshot["prediction_input_sha256"] != input_sha256):
            raise ValueError("Result evidence integrity/binding mismatch")
        if (not isinstance(input_sha256, str) or len(input_sha256) != 64
                or any(ch not in "0123456789abcdef" for ch in input_sha256)):
            raise ValueError("Invalid input snapshot digest")
        parsed = parse_final_summary(snapshot["summary"], observed_at_utc)
        if parsed is None or snapshot["event"] != parsed or event != parsed:
            raise ValueError("Result evidence cannot replay original final score")
        if (snapshot["home_team_id"] != parsed["home_team_id"]
                or snapshot["away_team_id"] != parsed["away_team_id"]
                or snapshot["source_url"] !=
                   "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="
                   + parsed["provider_fixture_id"]):
            raise ValueError("Result evidence source/team identity mismatch")
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Malformed result evidence") from exc


def same_result_observation(previous, incoming):
    before, after = dict(previous["snapshot"]), dict(incoming["snapshot"])
    before_time = before.pop("observed_at_utc")
    after_time = after.pop("observed_at_utc")
    return before == after and after_time >= before_time
