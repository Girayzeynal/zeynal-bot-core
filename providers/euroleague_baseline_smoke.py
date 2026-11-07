"""Persist explicit Euroleague Live estimates only to a new isolated research directory."""
import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from prediction_inputs import capture_team_inputs, digest
from providers.euroleague_live import EuroleagueLiveAdapter, identity


async def check_baselines(*, directory, league, year, teams, minimum=6):
    canonical, _, _, season = identity(league, year)
    if type(minimum) is not int or not 6 <= minimum <= 20:
        raise ValueError("Research baseline minimum must be six to twenty")
    if not teams or len(set(teams)) != len(teams):
        raise ValueError("Unique source team codes required")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)  # Refuse existing/production directories.
    store = TeamBaselineStore(str(root / "baselines"))
    adapter = EuroleagueLiveAdapter(baseline_season_year=year, allow_estimated_pace=True)
    bootstrap = TeamBaselineBootstrapper(store, [adapter])
    results, copies, all_ids = [], {}, set()
    try:
        for team in teams:
            baseline = await bootstrap.ensure_async(canonical, team, min_games=minimum)
            if baseline is None:
                results.append(dict(team=team, status="insufficient_or_unavailable",
                                    diagnostics=adapter.baseline_diagnostics))
                continue
            reopened = TeamBaselineStore(store.base_dir)
            rows = reopened.get_series(canonical, baseline.team, 100)
            if len(rows) < minimum:
                raise RuntimeError("Persisted evidence did not replay")
            first_observed = min(r.pace_evidence["observed_at_utc"] for r in rows)
            if reopened.get_series_before(canonical, baseline.team, first_observed, 100):
                raise RuntimeError("Late observations entered historical selection")
            # Wait for actual clock progression, never backdate source observations.
            await asyncio.sleep(1.1)
            item = capture_team_inputs(reopened, league=canonical, key=baseline.team, n_games=baseline.n_games,
                average=SimpleNamespace(points_for=baseline.pts_for, points_against=baseline.pts_against, pace=baseline.pace))
            copies[baseline.team] = item
            all_ids.update(r.game_id for r in rows)
            results.append(dict(team=baseline.team, status="replayed", retained_records=len(rows),
                aggregate_games=baseline.n_games, captured_input_games=len(item["records"]),
                input_copy_sha256=digest(item), pre_observation_records=0,
                diagnostics=adapter.baseline_diagnostics,
                baseline=asdict(baseline)))
        (root / "input-copies.json").write_text(json.dumps(copies, sort_keys=True, allow_nan=False) + "\n")
        report = dict(status="pass" if results and all(r["status"] == "replayed" for r in results) else "incomplete",
            league=canonical, season_code=season, observed_at_utc=datetime.now(timezone.utc).isoformat(),
            teams=results, distinct_retained_fixtures=len(all_ids), research_directory=str(root),
            production_written=False, profiles_added=False, predictions_created=0,
            calibration_status="NOT_EVALUATED")
        (root / "verification.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
        return report
    finally:
        await adapter.aclose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, help="Must not already exist")
    parser.add_argument("--league", required=True, choices=("EUROLEAGUE", "EUROCUP"))
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--teams", nargs="+", required=True)
    parser.add_argument("--minimum", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(check_baselines(directory=args.directory, league=args.league,
            year=args.year, teams=args.teams, minimum=args.minimum))
    except (ValueError, OSError, RuntimeError):
        print(json.dumps({"status": "baseline_check_failed"}))
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
