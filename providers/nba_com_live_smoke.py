"""Read-only NBA.com historical-games smoke check.

Run: python -m providers.nba_com_live_smoke SA
Exit 0 only if six or more structurally valid past games were returned.\nThis does not independently verify official scores or measured possessions.
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
            and len({(g.get("source"), g.get("game_id")) for g in games}) == len(games)
            and all(g.get("source") == "nba_com"
                    and isinstance(g.get("game_id"), str)
                    and g["game_id"].isdigit()
                    and 0 < g["ts_utc"] < now
                    and g["pts_for"] >= 0 and g["pts_against"] >= 0
                    and g["pts_for"] != g["pts_against"] for g in games)
        )
        return {
            "provider": "nba_com", "team": team,
            "candidate_game_count": len(games),
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
