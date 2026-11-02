"""Read-only ESPN historical team verification (no deployment or predictions).

Usage: python3 -m providers.espn_history_live_smoke
"""
import asyncio
import json
from datetime import datetime, timezone

from providers.espn_adapter import ESPNAdapter
from providers.espn_scoreboard_history import ESPNScoreboardHistory


async def main():
    resolver = ESPNAdapter()
    history = ESPNScoreboardHistory()
    try:
        output = []
        for name in ("San Antonio Spurs", "Utah Jazz"):
            resolved = await resolver.resolve_team(name)
            if not resolved:
                output.append({"team": name, "status": "unresolved"})
                continue
            games = await history.fetch_verified_games(
                resolved["id"],
                as_of_utc=datetime.now(timezone.utc),
                days=20, minimum=6,
            )
            if games is None:
                output.append({"team": name, "status": "insufficient_or_unavailable"})
                continue
            entries = []
            for game in games:
                home = game["home_team_id"] == resolved["id"]
                entries.append({
                    "fixture_id": game["provider_fixture_id"],
                    "utc": datetime.fromtimestamp(game["start_ts_utc"], timezone.utc).isoformat(),
                    "home": home,
                    "points_for": game["actual_home"] if home else game["actual_away"],
                    "points_against": game["actual_away"] if home else game["actual_home"],
                    "opponent_id": game["away_team_id"] if home else game["home_team_id"],
                })
            output.append({
                "team": name, "status": "pass",
                "verified_game_count": len(entries),
                "games": entries[-10:],
            })
        print(json.dumps({"provider": "ESPN", "results": output}, indent=2))
        return 0 if all(row["status"] == "pass" for row in output) else 1
    finally:
        await history.aclose()
        await resolver.aclose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        raise SystemExit(1)
