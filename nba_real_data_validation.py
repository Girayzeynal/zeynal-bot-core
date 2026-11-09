"""Offline replay of fetched ESPN finals; does not manufacture historical forecasts."""
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from providers.espn_completed_event import parse_completed_nba_event
from providers.espn_result_evidence import parse_final_summary
from providers.espn_boxscore_pace import estimate_pace_from_summary
from providers.nba_com_adapter import NBA_TEAMS


def deduplicate_finals(records):
    """Canonical NBA team IDs must be resolved by source adapters, never fuzzy names."""
    games, provider_ids = {}, {}
    for row in records:
        if (type(row.get("start_ts_utc")) is not int or row["start_ts_utc"] <= 0
                or any(not isinstance(row.get(k), str) or not row[k].strip()
                       for k in ("provider", "provider_fixture_id", "home", "away"))
                or row["home"] == row["away"]
                or any(type(row.get(k)) is not int or row[k] < 0 for k in ("home_score", "away_score"))
                or row["home_score"] == row["away_score"] or row.get("scope") != "FINAL_WITH_OT"):
            raise ValueError("invalid normalized final")
        if any(team not in {str(v) for v in NBA_TEAMS.values()} for team in (row["home"], row["away"])):
            raise ValueError("unknown canonical NBA team ID")
        key = (row["start_ts_utc"], tuple(sorted((row["home"], row["away"]))))
        facts = tuple(row[k] for k in ("home", "away", "home_score", "away_score", "scope"))
        provider_key = (row["provider"], row["provider_fixture_id"])
        if provider_key in provider_ids and provider_ids[provider_key] != key:
            raise ValueError("provider fixture ID reused")
        if key in games and games[key] != facts:
            raise ValueError("conflicting cross-provider final")
        # Conflicting schedules for a team at an exact start cannot inflate n.
        if any(start == key[0] and set(teams).intersection(key[1]) and teams != key[1]
               for start, teams in games):
            raise ValueError("conflicting same-team start")
        provider_ids[provider_key] = key
        games[key] = facts
    return dict(observations=len(records), distinct_games=len(games), duplicates=len(records)-len(games))


def verify_pair(event, summary, observed_at_utc):
    now = datetime.fromtimestamp(observed_at_utc, timezone.utc)
    game = parse_completed_nba_event(event, now)
    final = parse_final_summary(summary, observed_at_utc)
    if game is None or final is None or game != final:
        raise ValueError("scoreboard/summary final mismatch")
    competition = event["competitions"][0]
    if str(competition["id"]) != game["provider_fixture_id"]:
        raise ValueError("competition identity mismatch")
    canonical = {}
    for competitor in competition["competitors"]:
        abbreviation = competitor["team"]["abbreviation"]
        abbreviation = {"WSH": "WAS"}.get(abbreviation, abbreviation)
        if abbreviation not in NBA_TEAMS:
            raise ValueError("unmapped source team")
        canonical[competitor["homeAway"]] = str(NBA_TEAMS[abbreviation])
    pace = estimate_pace_from_summary(summary, game, now)
    return dict(provider="ESPN", provider_fixture_id=game["provider_fixture_id"],
                start_ts_utc=game["start_ts_utc"], **canonical,
                source_home_team_id=game["home_team_id"], source_away_team_id=game["away_team_id"],
                home_score=game["actual_home"], away_score=game["actual_away"], scope=game["scope"],
                pace=pace, observed_at_utc=observed_at_utc,
                injury_prematch_evidence="MISSING", roster_prematch_evidence="MISSING",
                historical_availability="NOT_ESTABLISHED")


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory")
    args=p.parse_args(argv)
    root=Path(args.directory)
    try:
        manifest=json.loads((root/"manifest.json").read_text())
        board=json.loads((root/"espn-20261102.raw").read_text())
        records=[]
        for event in board["events"]:
            summary=json.loads((root/(event["id"]+".json")).read_text())
            records.append(verify_pair(event, summary, manifest["observed_at_utc"]))
        source_files=["espn-20261102.raw", "manifest.json"]+[e["id"]+".json" for e in board["events"]]
        report=dict(source_file_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in source_files},
                    scoreboard_url="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261102",
                    summary_url_template="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={provider_fixture_id}",
                    status="source_consistent", coverage=deduplicate_finals(records), games=records,
                    independent_provider_verified=False, other_sources=manifest["other_sources"],
                    verified_prematch_predictions=0,
                    accuracy_metrics=dict(mae=None, rmse=None, brier_score=None, log_loss=None,
                                          probability_calibration=None),
                    stage_comparison={stage:"NO_ORIGINAL_PREMATCH_FORECAST_FOR_COMPLETED_SAMPLE"
                                      for stage in ("FAZ13","FAZ22","FAZ23")},
                    calibration_status="NOT_ESTABLISHED",
                    reason="No original pre-tipoff forecasts or historically available input snapshots for these finals")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps(dict(status="validation_failed",error_type=type(exc).__name__)))
        return 1
    print(json.dumps(report, sort_keys=True,allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
