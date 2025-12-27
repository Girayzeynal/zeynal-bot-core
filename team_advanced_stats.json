"""
Script to generate advanced NBA team statistics using the balldontlie API.

This script queries the balldontlie API for each NBA team in a given season,
computes offensive and defensive ratings and average pace, and writes the
results to a JSON file that conforms to the format expected by the
HoopBrain FAZ-13 engine.

Requirements:
    - Python 3.7+
    - Requests library (install with `pip install requests`)

Usage:
    Set your API key in the environment or pass it via command-line flag.
    Then run the script to produce `team_advanced_stats.json`.

    Example:
        export BDL_API_KEY="your_api_key_here"
        python generate_team_advanced_stats.py --season 2025

    This will produce a file named `team_advanced_stats.json` in the
    current working directory.

Notes:
    The balldontlie free tier exposes team and player box scores but does
    not directly provide advanced statistics. This script derives
    possessions and ratings using commonly accepted formulas:

    possessions = FGA + 0.44 * FTA - ORB + TOV
    ORTG = (points for / possessions) * 100
    DRTG = (points against / possessions) * 100
    pace = possessions / games played

    If you wish to add additional metrics, modify the `compute_metrics`
    function accordingly.
"""

import argparse
import json
import os
import sys
from typing import Dict, Tuple

import requests


API_BASE_URL = "https://api.balldontlie.io/v1"


def get_api_key(env_var: str = "BDL_API_KEY") -> str:
    """Retrieve the API key from environment variables.

    Args:
        env_var: Name of the environment variable containing the key.

    Returns:
        The API key as a string.

    Raises:
        RuntimeError: If the key is not found.
    """
    api_key = os.getenv(env_var)
    if not api_key:
        raise RuntimeError(
            f"API key not found in environment variable '{env_var}'. "
            "Set your API key via `export BDL_API_KEY=your_key` or pass it "
            "explicitly using the --api-key argument."
        )
    return api_key


def fetch_all_teams(api_key: str) -> Dict[str, int]:
    """Fetch all NBA teams and return a mapping from full name to ID.

    Args:
        api_key: Your balldontlie API key.

    Returns:
        A dictionary mapping team full names to their numeric IDs.
    """
    teams = {}
    page = 1
    while True:
        resp = requests.get(
            f"{API_BASE_URL}/teams",
            params={"per_page": 100, "page": page},
            headers={"Authorization": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for team in data.get("data", []):
            full_name = team.get("full_name")
            if full_name:
                teams[full_name] = team["id"]
        if not data.get("meta", {}).get("next_page"):
            break
        page += 1
    return teams


def fetch_team_stats(api_key: str, team_id: int, season: int) -> Tuple[float, float, float, int]:
    """Fetch box score stats for a team in a given season and compute metrics.

    Args:
        api_key: API key for balldontlie.
        team_id: ID of the team to query.
        season: The NBA season year (e.g., 2025).

    Returns:
        A tuple of (ortg, drtg, pace, games_played).
    """
    total_possessions = 0.0
    total_points_for = 0
    total_points_against = 0
    games_played = 0
    page = 1
    # The API returns up to 100 records per page; iterate until no next page
    while True:
        resp = requests.get(
            f"{API_BASE_URL}/stats",
            params={
                "team_ids[]": team_id,
                "seasons[]": season,
                "per_page": 100,
                "page": page,
                "postseason": False,
            },
            headers={"Authorization": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        records = data.get("data", [])
        for row in records:
            # Compute possessions using standard formula
            fga = row.get("fga", 0)
            fta = row.get("fta", 0)
            orb = row.get("oreb", 0)
            turnovers = row.get("turnover", 0)
            possessions = fga + 0.44 * fta - orb + turnovers
            total_possessions += possessions
            total_points_for += row.get("pts", 0)
            total_points_against += row.get("opp_pts", 0)
            games_played += 1
        # Check for next page
        if not data.get("meta", {}).get("next_page"):
            break
        page += 1
    if games_played == 0 or total_possessions == 0:
        return 0.0, 0.0, 0.0, 0
    ortg = (total_points_for / total_possessions) * 100.0
    drtg = (total_points_against / total_possessions) * 100.0
    pace = total_possessions / games_played
    return ortg, drtg, pace, games_played


def generate_advanced_stats(api_key: str, season: int, output_file: str) -> None:
    """Generate advanced stats for all NBA teams and write to a JSON file.

    Args:
        api_key: balldontlie API key.
        season: NBA season year.
        output_file: Path to write the output JSON file.
    """
    print(f"Fetching team list for season {season}…")
    teams = fetch_all_teams(api_key)
    print(f"Found {len(teams)} teams. Fetching stats...")
    season_key = str(season)
    result: Dict[str, Dict[str, Dict[str, float]]] = {season_key: {}}
    for team_name, team_id in teams.items():
        print(f"Processing {team_name} (ID {team_id})…", end=" ")
        try:
            ortg, drtg, pace, games = fetch_team_stats(api_key, team_id, season)
            result[season_key][team_name] = {
                "ortg": round(ortg, 1),
                "drtg": round(drtg, 1),
                "pace": round(pace, 2),
                "games": games,
            }
            print("done.")
        except Exception as e:
            print(f"error: {e}")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Advanced stats written to {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate NBA team advanced stats using the balldontlie API."
    )
    parser.add_argument(
        "--season",
        type=int,
        default=2025,
        help="Season year (e.g., 2025 for the 2025-2026 NBA season)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key for balldontlie. If omitted, uses the BDL_API_KEY environment variable.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="team_advanced_stats.json",
        help="Output JSON file path",
    )
    args = parser.parse_args()
    api_key = args.api_key or get_api_key()
    generate_advanced_stats(api_key, args.season, args.output)


if __name__ == "__main__":
    main()
