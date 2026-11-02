"""Read-only end-to-end ESPN score history quality audit.

Run: python3 -m providers.espn_history_gate_live_smoke
Never writes a baseline or invents possession/pace data.
"""
import asyncio
import json
from datetime import datetime, timezone

from providers.espn_adapter import ESPNAdapter
from providers.espn_scoreboard_history import ESPNScoreboardHistory
from providers.espn_history_quality_gate import validate_history_for_fixture


async def main():
    resolver = ESPNAdapter()
    history = ESPNScoreboardHistory()
    try:
        cutoff = datetime.now(timezone.utc)
        results = []
        for name in ("San Antonio Spurs", "Utah Jazz"):
            team = await resolver.resolve_team(name)
            if not isinstance(team, dict) or not str(team.get("id", "")).isdigit():
                results.append({"team": name, "status": "team_unresolved"})
                continue
            games = await history.fetch_verified_games(
                str(team["id"]), as_of_utc=cutoff, days=20,
                minimum=6, regular_season_only=True)
            if games is None:
                results.append({"team": name, "status": "insufficient_or_unavailable"})
                continue
            score = validate_history_for_fixture(
                games, team_id=str(team["id"]), fixture_start_utc=cutoff,
                minimum=6, require_pace=False)
            pace = validate_history_for_fixture(
                games, team_id=str(team["id"]), fixture_start_utc=cutoff,
                minimum=6, require_pace=True)
            results.append({
                "team": name, "verified_game_count": len(games),
                "score_history": score["status"],
                "pace_dependent_baseline": pace["status"],
                "production_ready": False,
            })
        print(json.dumps({"provider": "ESPN", "cutoff_utc": cutoff.isoformat(),
                          "results": results}, indent=2))
        return 0 if len(results) == 2 and all(
            x.get("score_history") == "score_history_verified"
            and x.get("pace_dependent_baseline") == "pace_unavailable"
            for x in results) else 1
    finally:
        await history.aclose()
        await resolver.aclose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        raise SystemExit(1)
