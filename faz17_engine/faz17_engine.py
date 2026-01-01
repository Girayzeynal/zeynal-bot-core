# faz17_engine.py

from dataclasses import dataclass
from typing import Any, Dict, Optional
import os
import asyncio
import aiohttp

@dataclass
class MarketRequest:
    league: str
    date_str: str  # format: YYYY-MM-DD
    home: str
    away: str

class Faz17Engine:
    @staticmethod
    async def fetch_market_total(req: MarketRequest) -> Dict[str, Any]:
        """Fetch market total and odds in a cascading order from ESPN, SportsDataIO, Odds API, API Sports, then Balldontlie."""
        # Prepare the result dictionary with required keys
        result: Dict[str, Optional[Any]] = {
            "total": None,
            "home_h2h": None,
            "away_h2h": None,
            "ft_score": None,
            "ht_score": None
        }

        # Get API keys from environment (if available)
        sportsdataio_key = os.getenv("SPORTSDATAIO_API_KEY")
        odds_api_key = os.getenv("ODDS_API_KEY")
        apisports_key = os.getenv("API_SPORTS_KEY")
        balldontlie_key = os.getenv("BALLDONTLIE_API_KEY")

        # Normalize input team names for comparisons (lowercase for case-insensitivity)
        home_name = req.home.lower() if req.home else ""
        away_name = req.away.lower() if req.away else ""
        league = req.league.upper() if req.league else ""

        # Parse date string and prepare various format versions
        try:
            from datetime import datetime
            game_date = datetime.strptime(req.date_str, "%Y-%m-%d")
        except Exception:
            game_date = None
        date_str = req.date_str
        date_no_dash = date_str.replace("-", "")
        # SportsDataIO requires date as YYYY-MMM-DD (e.g., 2023-SEP-15)
        date_mmm = None
        try:
            if game_date:
                date_mmm = game_date.strftime("%Y-%b-%d").upper()  # e.g., 2024-JAN-05
        except Exception:
            date_mmm = None

        # Helper: safely update result fields if they are currently None and new value is not None
        def fill_field(field: str, value: Any):
            if field in result and result[field] is None and value is not None:
                result[field] = value

        # Use a single session for HTTP requests
        timeout = aiohttp.ClientTimeout(total=5)  # 5 seconds timeout for each request
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 1. ESPN
            try:
                sport_path = None
                if league == "NBA":
                    sport_path = "basketball/nba"
                elif league == "NFL":
                    sport_path = "football/nfl"
                elif league == "MLB":
                    sport_path = "baseball/mlb"
                elif league == "NHL":
                    sport_path = "hockey/nhl"
                elif league in ["NCAAF", "CFB", "COLLEGE FOOTBALL"]:
                    sport_path = "football/college-football"
                elif league in ["NCAAB", "CBB", "COLLEGE BASKETBALL"]:
                    sport_path = "basketball/mens-college-basketball"
                elif league == "WNBA":
                    sport_path = "basketball/wnba"
                elif league == "EPL":
                    # ESPN uses 'eng.1' for English Premier League
                    sport_path = "soccer/eng.1"
                # Add more league mappings as needed

                if sport_path:
                    scoreboard_url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={date_no_dash}"
                    async with session.get(scoreboard_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                        else:
                            data = None
                    if data and "events" in data:
                        event = None
                        for ev in data["events"]:
                            # Each event has competitors with team names
                            try:
                                competitors = ev.get("competitions", [])[0].get("competitors", [])
                            except Exception:
                                competitors = []
                            team_names = {comp.get("team", {}).get("displayName", "").lower() for comp in competitors}
                            if home_name in team_names and away_name in team_names:
                                event = ev
                                break
                        if event:
                            # Extract final score if available
                            try:
                                comp_list = event["competitions"][0]["competitors"]
                            except Exception:
                                comp_list = []
                            home_score = away_score = None
                            for comp in comp_list:
                                team_info = comp.get("team", {})
                                comp_name = team_info.get("displayName", "").lower()
                                if comp_name == home_name or comp.get("homeAway") == "home":
                                    # If name matches home or marked as home
                                    home_score = comp.get("score")
                                if comp_name == away_name or comp.get("homeAway") == "away":
                                    away_score = comp.get("score")
                            # If scores are numeric strings and game is final, fill ft_score
                            status_info = event.get("status", {}).get("type", {})
                            if status_info.get("completed") or status_info.get("name") in ["STATUS_FINAL", "STATUS_END", "Final"]:
                                if home_score is not None and away_score is not None:
                                    # ensure they are strings or numbers
                                    ft = f"{home_score}-{away_score}"
                                    fill_field("ft_score", ft)

                            # Now fetch odds via summary to get market total and H2H if available
                            event_id = event.get("id")
                            if event_id:
                                summary_url = f"https://site.api.espn.com/apis/v2/sports/{sport_path}/summary?event={event_id}"
                                async with session.get(summary_url) as resp:
                                    if resp.status == 200:
                                        summary_data = await resp.json()
                                    else:
                                        summary_data = None
                                if summary_data:
                                    pickcenter = summary_data.get("pickcenter", [])
                                    # ESPN pickcenter might contain multiple entries from different providers
                                    pick = None
                                    for pc in pickcenter:
                                        # Choose the first entry that has both moneyLine and overUnder
                                        if pc.get("overUnder") is not None and pc.get("homeTeamOdds") and pc.get("awayTeamOdds"):
                                            pick = pc
                                            break
                                    if pick:
                                        fill_field("total", pick.get("overUnder"))
                                        # home_h2h and away_h2h as moneyLine odds
                                        # Sometimes ESPN uses american moneyline (e.g. -180), which can be int or str.
                                        home_ml = None
                                        away_ml = None
                                        try:
                                            home_ml = pick.get("homeTeamOdds", {}).get("moneyLine")
                                        except Exception:
                                            home_ml = None
                                        try:
                                            away_ml = pick.get("awayTeamOdds", {}).get("moneyLine")
                                        except Exception:
                                            away_ml = None
                                        fill_field("home_h2h", home_ml)
                                        fill_field("away_h2h", away_ml)
            except Exception:
                # On any error with ESPN, move to next source
                pass

            # 2. SportsDataIO
            try:
                if sportsdataio_key and date_mmm:
                    base_url = None
                    if league == "NBA":
                        base_url = "https://api.sportsdata.io/v3/nba/odds/json/GameOddsByDate/"
                    elif league == "MLB":
                        base_url = "https://api.sportsdata.io/v3/mlb/odds/json/GameOddsByDate/"
                    elif league == "NHL":
                        base_url = "https://api.sportsdata.io/v3/nhl/odds/json/GameOddsByDate/"
                    elif league == "WNBA":
                        base_url = "https://api.sportsdata.io/v3/wnba/odds/json/GameOddsByDate/"
                    # Note: SportsDataIO NFL odds require season/week endpoints, skipping for simplicity
                    # Note: Soccer (EPL) not covered via date without competition, skipping
                    if base_url:
                        url = base_url + date_mmm
                        headers = {"Ocp-Apim-Subscription-Key": sportsdataio_key}
                        async with session.get(url, headers=headers) as resp:
                            if resp.status == 200:
                                games = await resp.json()
                            else:
                                games = None
                        if games:
                            # If the response is a list of games
                            found_game = None
                            for game in games:
                                try:
                                    # Compare teams by abbreviation (SportsDataIO uses abbreviations in HomeTeam/AwayTeam)
                                    home_abbr = game.get("HomeTeam", "").lower()
                                    away_abbr = game.get("AwayTeam", "").lower()
                                except Exception:
                                    home_abbr = away_abbr = ""
                                # Check if input home/away matches either abbreviation or full name if provided in data (unlikely)
                                # We attempt match by abbreviation first.
                                if home_abbr == home_name and away_abbr == away_name:
                                    found_game = game
                                    break
                                # Also try if abbreviations match swapped (in case user gave abbreviations in any case)
                                if home_abbr == away_name and away_abbr == home_name:
                                    found_game = game
                                    break
                            if found_game:
                                fill_field("total", found_game.get("OverUnder"))
                                fill_field("home_h2h", found_game.get("HomeTeamMoneyLine"))
                                fill_field("away_h2h", found_game.get("AwayTeamMoneyLine"))
                                # If final scores available, fill ft_score
                                home_score = found_game.get("HomeTeamScore")
                                away_score = found_game.get("AwayTeamScore")
                                if home_score is not None and away_score is not None:
                                    ft = f"{home_score}-{away_score}"
                                    fill_field("ft_score", ft)
            except Exception:
                pass

            # 3. The Odds API
            try:
                if odds_api_key:
                    # Map league to The Odds API sport key
                    sport_key = None
                    if league == "NBA":
                        sport_key = "basketball_nba"
                    elif league == "NFL":
                        sport_key = "americanfootball_nfl"
                    elif league == "MLB":
                        sport_key = "baseball_mlb"
                    elif league == "NHL":
                        sport_key = "icehockey_nhl"
                    elif league == "EPL":
                        sport_key = "soccer_epl"
                    # (Add more mappings for other leagues if needed)
                    if sport_key:
                        odds_url = (f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds?"
                                    f"apiKey={odds_api_key}&regions=us&markets=h2h,totals&oddsFormat=american")
                        async with session.get(odds_url) as resp:
                            if resp.status == 200:
                                odds_data = await resp.json()
                            else:
                                odds_data = None
                        if odds_data:
                            game_odds = None
                            for game in odds_data:
                                home_team = game.get("home_team", "").lower()
                                away_team = game.get("away_team", "").lower()
                                if home_name == home_team and away_name == away_team:
                                    game_odds = game
                                    break
                                if home_name == away_team and away_name == home_team:
                                    # Swap in case input was reversed (shouldn't happen typically)
                                    game_odds = game
                                    break
                            if game_odds:
                                # The game_odds contains bookmakers with odds
                                bookmakers = game_odds.get("bookmakers", [])
                                chosen_book = None
                                for book in bookmakers:
                                    # Pick the first bookmaker with required markets
                                    markets = book.get("markets", [])
                                    market_keys = {m.get("key") for m in markets}
                                    if "h2h" in market_keys and "totals" in market_keys:
                                        chosen_book = book
                                        break
                                if not chosen_book and bookmakers:
                                    chosen_book = bookmakers[0]  # fallback: pick first available
                                if chosen_book:
                                    # Extract totals market
                                    total_line = None
                                    for market in chosen_book.get("markets", []):
                                        if market.get("key") == "totals":
                                            outcomes = market.get("outcomes", [])
                                            # Each outcome might have name "Over" or "Under"
                                            for out in outcomes:
                                                if "point" in out:
                                                    total_line = out["point"]
                                                    break
                                            # Once point is found, break out
                                            if total_line is not None:
                                                break
                                    fill_field("total", total_line)
                                    # Extract H2H odds (moneyline odds)
                                    for market in chosen_book.get("markets", []):
                                        if market.get("key") == "h2h":
                                            outcomes = market.get("outcomes", [])
                                            home_ml = away_ml = None
                                            for out in outcomes:
                                                name = out.get("name", "").lower()
                                                price = out.get("price")
                                                # The price in American format might be a string or number (e.g., "-180" or -180)
                                                if name == req.home.lower():
                                                    home_ml = price
                                                elif name == req.away.lower():
                                                    away_ml = price
                                            # If team names in outcomes might not exactly match input names (could differ in abbreviation vs full),
                                            # try an alternate match by checking if name contains part of input.
                                            if home_ml is None or away_ml is None:
                                                for out in outcomes:
                                                    name = out.get("name", "").lower()
                                                    price = out.get("price")
                                                    if home_ml is None and home_name in name:
                                                        home_ml = price
                                                    if away_ml is None and away_name in name:
                                                        away_ml = price
                                            fill_field("home_h2h", home_ml)
                                            fill_field("away_h2h", away_ml)
                                            break
            except Exception:
                pass

            # 4. API Sports
            try:
                if apisports_key:
                    # We'll primarily use API Sports for soccer (EPL), but also attempt for other leagues if supported
                    if league == "EPL":
                        league_id = 39  # English Premier League
                        # Determine season year (the year season starts in)
                        season_year = game_date.year if game_date else None
                        if game_date:
                            # If month is July or later, season starts same year, otherwise season started previous year
                            if game_date.month < 7:
                                season_year = game_date.year - 1
                            else:
                                season_year = game_date.year
                        # Fetch fixtures for that date and league
                        if season_year:
                            fixtures_url = (f"https://v3.football.api-sports.io/fixtures?"
                                            f"date={date_str}&league={league_id}&season={season_year}")
                        else:
                            fixtures_url = f"https://v3.football.api-sports.io/fixtures?date={date_str}&league={league_id}"
                        headers = {"x-apisports-key": apisports_key}
                        async with session.get(fixtures_url, headers=headers) as resp:
                            if resp.status == 200:
                                api_data = await resp.json()
                            else:
                                api_data = None
                        fixture_id = None
                        if api_data and "response" in api_data:
                            for fixture in api_data["response"]:
                                # Each fixture contains teams info
                                teams = fixture.get("teams", {})
                                home_team_name = teams.get("home", {}).get("name", "").lower()
                                away_team_name = teams.get("away", {}).get("name", "").lower()
                                if home_name == home_team_name and away_name == away_team_name:
                                    fixture_id = fixture.get("fixture", {}).get("id")
                                    # If final score available:
                                    goals = fixture.get("goals", {})
                                    home_goals = goals.get("home")
                                    away_goals = goals.get("away")
                                    if home_goals is not None and away_goals is not None:
                                        ft = f"{home_goals}-{away_goals}"
                                        fill_field("ft_score", ft)
                                        # If half-time score available in score->halftime:
                                        score_obj = fixture.get("score", {})
                                        halftime = score_obj.get("halftime")
                                        if halftime and "home" in halftime and "away" in halftime:
                                            ht = f"{halftime['home']}-{halftime['away']}"
                                            fill_field("ht_score", ht)
                                    break
                        # If we got a fixture_id and still missing odds or total, fetch odds for that fixture
                        if fixture_id and (result["total"] is None or result["home_h2h"] is None or result["away_h2h"] is None):
                            odds_url = f"https://v3.football.api-sports.io/odds?fixture={fixture_id}"
                            headers = {"x-apisports-key": apisports_key}
                            async with session.get(odds_url, headers=headers) as resp:
                                if resp.status == 200:
                                    odds_json = await resp.json()
                                else:
                                    odds_json = None
                            if odds_json and "response" in odds_json and odds_json["response"]:
                                # API Sports returns an array of bookmakers for the fixture
                                bookmaker_data = odds_json["response"][0]  # pick first bookmaker (e.g., Pinnacle)
                                bets = bookmaker_data.get("odds", [])
                                home_ml = away_ml = None
                                total_line = None
                                # Iterate bets (markets)
                                for bet in bets:
                                    # Identify 1X2 or Moneyline market
                                    # In soccer, "Match Winner" might be 1X2 including draw
                                    if bet.get("name", "").lower() in ["match winner", "moneyline", "1x2"]:
                                        values = bet.get("values", [])
                                        for val in values:
                                            val_label = val.get("value", "").lower()
                                            odd = val.get("odd")
                                            # home/away identification may be by team name or "Home" etc.
                                            if val_label == req.home.lower() or val_label == home_name:
                                                home_ml = odd
                                            if val_label == req.away.lower() or val_label == away_name:
                                                away_ml = odd
                                        # If draw exists and above didn't catch, ignore draw.
                                    # Identify total goals O/U market
                                    if bet.get("name", "").lower() in ["total goals", "over/under", "totals"] or any(val.get("value") == "Over" for val in bet.get("values", [])):
                                        values = bet.get("values", [])
                                        # Typically for O/U, values list has Over and Under entries with a "handicap"
                                        for val in values:
                                            if val.get("value") == "Over":
                                                # handicap is the total line
                                                if val.get("handicap") is not None:
                                                    total_line = float(val["handicap"])
                                                else:
                                                    total_line = None
                                                break
                                        # break out if total_line found
                                        if total_line is not None:
                                            break
                                fill_field("home_h2h", home_ml)
                                fill_field("away_h2h", away_ml)
                                fill_field("total", total_line)
                    # For other sports via API Sports: if needed, similar approach (API Sports also has NBA, NFL, etc, but skipping due to complexity)
            except Exception:
                pass

            # 5. Balldontlie (final fallback for scores or any missing data)
            try:
                # Use Balldontlie free API for final scores if game date is in the past or today.
                if game_date and balldontlie_key is not None:
                    # Determine sport path for API (balldontlie uses sub-URL for sports except NBA which can be default v1)
                    sport_path = None
                    if league == "NBA":
                        sport_path = "v1/games"
                    elif league == "NFL":
                        sport_path = "nfl/v1/games"
                    elif league == "MLB":
                        sport_path = "mlb/v1/games"
                    elif league == "NHL":
                        sport_path = "nhl/v1/games"
                    elif league == "EPL":
                        sport_path = "epl/v1/games"
                    # (Add other sports as needed)
                    if sport_path:
                        games_url = f"https://api.balldontlie.io/{sport_path}?dates[]={date_str}"
                        headers = {"Authorization": balldontlie_key}
                        async with session.get(games_url, headers=headers) as resp:
                            if resp.status == 200:
                                games_data = await resp.json()
                            else:
                                games_data = None
                        if games_data and "data" in games_data:
                            for game in games_data["data"]:
                                # Identify teams
                                home_team = None
                                away_team = None
                                # The structure may differ by sport, but typically:
                                if "home_team" in game:
                                    home_team = game["home_team"]
                                    away_team = game.get("visitor_team") or game.get("away_team")
                                elif "teams" in game:
                                    # Some sports might use 'teams' object
                                    teams = game["teams"]
                                    home_team = teams.get("home")
                                    away_team = teams.get("away")
                                # Determine team names/full_names
                                home_full = home_team.get("full_name", "").lower() if home_team else ""
                                away_full = away_team.get("full_name", "").lower() if away_team else ""
                                home_abbr = home_team.get("abbreviation", "").lower() if home_team else ""
                                away_abbr = away_team.get("abbreviation", "").lower() if away_team else ""
                                # If any match with input names
                                if home_name in (home_full, home_abbr) and away_name in (away_full, away_abbr):
                                    # Found matching game
                                    # Get final scores
                                    if "home_team_score" in game and "visitor_team_score" in game:
                                        home_score = game["home_team_score"]
                                        away_score = game["visitor_team_score"]
                                    elif "home_score" in game and "away_score" in game:
                                        home_score = game["home_score"]
                                        away_score = game["away_score"]
                                    else:
                                        home_score = None
                                        away_score = None
                                    if home_score is not None and away_score is not None:
                                        ft = f"{home_score}-{away_score}"
                                        fill_field("ft_score", ft)
                                    # Get half-time score if available (for NBA, etc.)
                                    # For NBA, half-time is Q1+Q2:
                                    if "home_q2" in game and "visitor_q2" in game:
                                        # sum Q1+Q2 if Q1 present
                                        if "home_q1" in game and "visitor_q1" in game:
                                            ht_home = game.get("home_q1", 0) + game.get("home_q2", 0)
                                            ht_away = game.get("visitor_q1", 0) + game.get("visitor_q2", 0)
                                        else:
                                            # If only half-time score is directly given (not likely), use it.
                                            ht_home = game.get("home_q2")
                                            ht_away = game.get("visitor_q2")
                                        if ht_home is not None and ht_away is not None:
                                            ht = f"{ht_home}-{ht_away}"
                                            fill_field("ht_score", ht)
                                    elif "score" in game and isinstance(game["score"], dict):
                                        # Some sports might have 'score': {'halftime': {...}}
                                        half = game["score"].get("halftime")
                                        if half and "home" in half and "away" in half:
                                            ht = f"{half['home']}-{half['away']}"
                                            fill_field("ht_score", ht)
                                    break
            except Exception:
                pass

        # Ensure we have at least the required keys present (with None if not filled)
        # Already initialized, so just return
        return result
