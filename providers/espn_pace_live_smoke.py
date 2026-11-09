"""Read-only history/box-score reconciliation. Never writes a baseline or prediction."""
import argparse
import asyncio
from datetime import datetime, timezone
import json

from providers.espn_adapter import ESPNAdapter
from providers.espn_scoreboard_history import ESPNScoreboardHistory


async def check_teams(teams: list[str]) -> dict:
    adapter = ESPNAdapter()
    history = ESPNScoreboardHistory()
    cutoff = datetime.now(timezone.utc)
    results = []
    cache = {}
    try:
        for name in teams:
            ref = await adapter.resolve_team(name)
            games = None if not ref else await history.fetch_verified_games(
                ref["id"], as_of_utc=cutoff, days=20, minimum=6, regular_season_only=True)
            if not games:
                results.append(dict(team=name, status="history_unavailable"))
                continue
            accepted, rejected = [], []
            for game in games:
                gid = game["provider_fixture_id"]
                if gid not in cache:
                    cache[gid] = await adapter.fetch_pace_evidence(game, cutoff)
                evidence = cache[gid]
                if evidence is None:
                    rejected.append(gid)
                    continue
                accepted.append(dict(fixture_id=gid, pace=evidence["pace"],
                                     method=evidence["method"], kind=evidence["kind"],
                                     duration_minutes=evidence["duration_minutes"],
                                     inputs=evidence["inputs"], source_url=evidence["source_url"]))
            results.append(dict(team=name, history_games=len(games),
                                estimated_pace_games=len(accepted), rejected_fixture_ids=rejected,
                                status="estimated_pace_available" if len(accepted) >= 6 else "insufficient_pace",
                                production_ready=False, games=accepted))
        return dict(provider="ESPN", observed_at_utc=cutoff.isoformat(),
                    status="pass" if results and all(r["status"] == "estimated_pace_available" for r in results) else "incomplete",
                    results=results)
    finally:
        await adapter.aclose()
        await history.aclose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("teams", nargs="+", help="Quoted ESPN NBA team names")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(check_teams(args.teams))
    except (RuntimeError, ValueError, OSError):
        print(json.dumps({"status": "error"}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
