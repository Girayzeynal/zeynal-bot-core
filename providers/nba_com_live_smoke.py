"""Read-only NBA.com historical-games smoke check.

Run: python -m providers.nba_com_live_smoke SA
Exit 0 only if six or more verified past games were returned.
No secrets, scores, or team-specific game identifiers are printed.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

from providers.nba_com_adapter import NBAComAdapter


async def check(team: str) -> dict:
    adapter = NBAComAdapter()
    try:
        games = await adapter.fetch_team_recent_games("NBA", team, 10)
        games = games or []
        now = datetime.now(timezone.utc).timestamp()
        valid = (
            len(games) >= 6
            and len({int(g["ts_utc"]) for g in games}) >= 6
            and all(0 < g["ts_utc"] < now
                    and g["pts_for"] >= 0 and g["pts_against"] >= 0
                    and g["pts_for"] != g["pts_against"] for g in games)
        )
        return {
            "provider": "nba_com", "team": team,
            "verified_game_count": len(games),
            "oldest_game_date_utc": datetime.fromtimestamp(min(g["ts_utc"] for g in games), timezone.utc).date().isoformat() if games else None,
            "newest_game_date_utc": datetime.fromtimestamp(max(g["ts_utc"] for g in games), timezone.utc).date().isoformat() if games else None,
            "status": "pass" if valid else "insufficient_or_invalid",
        }
    finally:
        await adapter.aclose()


def main() -> int:
    team = sys.argv[1].strip().upper() if len(sys.argv) == 2 else ""
    if team not in ("SA", "UTAH"):
        print("Usage: python -m providers.nba_com_live_smoke SA|UTAH", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(check(team))
    except Exception as exc:
        print(json.dumps({"provider": "nba_com", "team": team, "status": "error", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
