"""Original pre-tipoff EuroLeague fixture observations; no network or inferred identity."""
from copy import deepcopy
from datetime import datetime
import time
from zoneinfo import ZoneInfo

from prediction_inputs import digest, validate_prediction_inputs
from providers.euroleague_live import BASE, PACE_METHOD, parse_game


def capture_fixture_evidence(raw, *, year, observed_at_utc):
    game = parse_game(raw, league="EUROLEAGUE", year=year, observed_at_utc=observed_at_utc)
    if (game is None or game["status"] != "UNPLAYED" or game["phase"] != "RS"
            or not observed_at_utc < game["start_ts_utc"]):
        raise ValueError("A confirmed future regular-season EuroLeague fixture is required")
    try:
        for side in ("local", "road"):
            part = raw[side]["partials"]
            if (type(raw[side]["score"]) is not int or raw[side]["score"] != 0
                    or part["extraPeriods"] != {}
                    or any(type(part[f"partials{i}"]) is not int or part[f"partials{i}"] != 0 for i in range(1, 5))):
                raise ValueError("Unplayed fixture contains live/score evidence")
        compact = {key: deepcopy(raw[key]) for key in ("id", "identifier", "gameCode", "season",
            "confirmedDate", "confirmedHour", "gameStatus", "played", "utcDate", "phaseType")}
        for side in ("local", "road"):
            compact[side] = dict(score=raw[side]["score"], partials=deepcopy(raw[side]["partials"]),
                club={key: raw[side]["club"][key] for key in ("code", "name", "isVirtual")})
        payload = dict(schema_version=1, year=year, observed_at_utc=observed_at_utc, fixture=game,
            raw_game=compact, source_url=f"{BASE}/E/seasons/{game['season_code']}/games/{game['game_code']}")
        return dict(payload=payload, sha256=digest(payload))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed scheduled EuroLeague fixture") from exc


def validate_fixture_evidence(evidence, *, fixture_id, tipoff_utc, prediction_utc, input_snapshot):
    try:
        payload = evidence["payload"]
        if (type(payload["schema_version"]) is not int or payload["schema_version"] != 1
                or evidence["sha256"] != digest(payload)):
            raise ValueError("EuroLeague fixture observation integrity mismatch")
        replay = capture_fixture_evidence(payload["raw_game"], year=payload["year"],
                                         observed_at_utc=payload["observed_at_utc"])
        if replay != evidence:
            raise ValueError("EuroLeague fixture observation cannot replay")
        game, observed = payload["fixture"], payload["observed_at_utc"]
        if (type(prediction_utc) is not int or not 0 < prediction_utc <= observed < tipoff_utc
                or observed > int(time.time()) or game["provider_fixture_id"] != fixture_id
                or game["start_ts_utc"] != tipoff_utc or game["league"] != "EUROLEAGUE"):
            raise ValueError("EuroLeague fixture prediction identity/time mismatch")
        inputs = input_snapshot["payload"]
        validate_prediction_inputs(input_snapshot, league="EUROLEAGUE", prediction_utc=prediction_utc,
            expected_home=inputs["expected_home"], expected_away=inputs["expected_away"])
        context = inputs["context"]
        expected_day = datetime.fromtimestamp(tipoff_utc, ZoneInfo("Europe/Istanbul")).date().isoformat()
        if (context["date"] != expected_day or context["home"] != game["home_team_id"]
                or context["away"] != game["away_team_id"]):
            raise ValueError("EuroLeague input context does not match provider fixture")
        for team in inputs["teams"].values():
            for row in team["records"]:
                if (row["source"] != PACE_METHOD
                        or row["pace_evidence"]["game"]["season_code"] != game["season_code"]):
                    raise ValueError("EuroLeague inputs use a different source or season")
        return game
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Malformed EuroLeague fixture binding") from exc
