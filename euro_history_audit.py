"""Offline, deduplicated source-evidence audit; no profile fitting or forecasts."""
import argparse
import json
from pathlib import Path
from statistics import fmean, stdev
from types import SimpleNamespace
import time

from providers.euroleague_live import PACE_METHOD, identity
from providers.pace_evidence import validate_pace_evidence


def audit_history(copies, *, league, year):
    canonical, _, _, season = identity(league, year)
    if not isinstance(copies, dict) or not copies:
        raise ValueError("nonempty team input copies required")
    fixtures, uuids, teams = {}, {}, {}
    observations = []
    for team, item in copies.items():
        if (not isinstance(team, str) or not team or team != team.strip().upper()
                or not isinstance(item, dict) or item.get("key") != team):
            raise ValueError("source team identity mismatch")
        captured = item.get("captured_at_utc")
        rows = item.get("records")
        if type(captured) is not int or not 0 < captured <= int(time.time()):
            raise ValueError("invalid capture time")
        if not isinstance(rows, list) or not rows:
            raise ValueError("nonempty record list required")
        seen = set()
        for raw in rows:
            if not isinstance(raw, dict):
                raise ValueError("invalid record")
            row = SimpleNamespace(**raw)
            if getattr(row, "source", None) != PACE_METHOD:
                raise ValueError("Euroleague Live evidence required")
            validate_pace_evidence(row, league=canonical, team=team, prediction_utc=captured)
            evidence = row.pace_evidence
            game = evidence["game"]
            if game["season_code"] != season:
                raise ValueError("mixed season")
            fixture = game["provider_fixture_id"]
            if fixture in seen:
                raise ValueError("duplicate fixture within team")
            seen.add(fixture)
            # Compare source identity and calculation facts, allowing independent
            # later observation times for each side without inventing a new match.
            facts = dict(game=game, pace=evidence["pace"], inputs=evidence["inputs"])
            if fixture in fixtures and fixtures[fixture] != facts:
                raise ValueError("conflicting fixture facts")
            uuid = game["provider_game_uuid"]
            if uuid in uuids and uuids[uuid] != fixture:
                raise ValueError("reused source UUID")
            uuids[uuid] = fixture
            fixtures[fixture] = facts
            observations.append(evidence["observed_at_utc"])
        teams[team] = dict(records=len(rows), first_start_utc=min(r["ts_utc"] for r in rows),
                           last_start_utc=max(r["ts_utc"] for r in rows))
    paces = [facts["pace"] for facts in fixtures.values()]
    return dict(status="audited", league=canonical, season_code=season,
                provider="EUROLEAGUE_LIVE", team_series=teams,
                team_records=sum(t["records"] for t in teams.values()),
                distinct_fixtures=len(fixtures),
                duplicate_cross_team_records=sum(t["records"] for t in teams.values())-len(fixtures),
                fixture_ids=sorted(fixtures),
                pace_kind="BOX_SCORE_ESTIMATE", pace_mean=fmean(paces),
                pace_sample_std=stdev(paces) if len(paces) > 1 else None,
                earliest_observation_utc=min(observations), latest_observation_utc=max(observations),
                coverage_scope="supplied_records_only", calibration_status="NOT_ESTABLISHED",
                independent_provider_verified=False, profiles_created=0, predictions_created=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_copies")
    parser.add_argument("--league", required=True, choices=("EUROLEAGUE", "EUROCUP"))
    parser.add_argument("--year", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        copies = json.loads(Path(args.input_copies).read_text())
        result = audit_history(copies, league=args.league, year=args.year)
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
        print(json.dumps(dict(status="audit_failed", error_type=type(exc).__name__)))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
