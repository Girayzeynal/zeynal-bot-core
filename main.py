import os
import logging
import html
import math
import random
import requests

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Set up basic structured logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Retrieve required environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
BALLDONTLIE_API_KEY = os.environ.get("BALLDONTLIE_API_KEY")
API_SPORTS_KEY = os.environ.get("API_SPORTS_KEY")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN is not set in environment.")
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
if not BALLDONTLIE_API_KEY:
    logger.error("BALLDONTLIE_API_KEY is not set in environment.")
    raise RuntimeError("Missing BALLDONTLIE_API_KEY")
if not API_SPORTS_KEY:
    logger.error("API_SPORTS_KEY is not set in environment.")
    raise RuntimeError("Missing API_SPORTS_KEY")
if not ODDS_API_KEY:
    logger.error("ODDS_API_KEY is not set in environment.")
    raise RuntimeError("Missing ODDS_API_KEY")

# Define engine classes
class FAZ13Engine:
    """Core analysis engine: fetches baseline data for teams and computes initial predictions."""
    def __init__(self, balldontlie_api_key: str, api_sports_key: str):
        self.balldontlie_api_key = balldontlie_api_key
        self.api_sports_key = api_sports_key
        # Cache team data to reduce API calls
        self.team_cache = {"NBA": {}, "NFL": {}, "MLB": {}, "NHL": {}, "EPL": {}, "LaLiga": {}, "SerieA": {}, "Bundesliga": {}, "Ligue1": {}, "ChampionsLeague": {}}
        # Map league names to API-Sports league IDs for soccer
        self.league_id_map = {
            "EPL": 39,
            "PremierLeague": 39,
            "LaLiga": 140,
            "SerieA": 135,
            "Bundesliga": 78,
            "Ligue1": 61,
            "ChampionsLeague": 2,
        }
        # Default neutral baseline values if data missing
        self.default_values = {
            "basketball": {"points_for": 110.0, "points_against": 110.0},
            "football": {"goals_for": 1.2, "goals_against": 1.2}
        }
        # API headers
        self.bdl_headers = {"Authorization": self.balldontlie_api_key}
        self.api_sports_headers = {"x-apisports-key": self.api_sports_key}

    def _get_nba_team_id(self, team_name: str) -> int:
        # Fetch and cache NBA team list if not cached
        if not self.team_cache["NBA"]:
            url = "https://api.balldontlie.io/v1/teams"
            try:
                resp = requests.get(url, headers=self.bdl_headers, timeout=10)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"Error fetching NBA teams: {e}")
                return None
            data = resp.json().get("data", [])
            for team in data:
                full_name = team.get("full_name")
                tid = team.get("id")
                if full_name and tid:
                    self.team_cache["NBA"][full_name.lower()] = tid
        return self.team_cache["NBA"].get(team_name.lower())

    def _get_nba_team_stats(self, team_id: int, season_year: int):
        # Fetch games for team and compute average points for/against
        url = f"https://api.balldontlie.io/v1/games?team_ids[]={team_id}&seasons[]={season_year}&per_page=100"
        try:
            resp = requests.get(url, headers=self.bdl_headers, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Error fetching NBA games for team {team_id}: {e}")
            return None
        games = resp.json().get("data", [])
        if not games:
            return None
        total_points_for = total_points_against = 0
        count = 0
        for game in games:
            home_id = game["home_team"]["id"]
            away_id = game["visitor_team"]["id"]
            home_score = game["home_team_score"]
            away_score = game["visitor_team_score"]
            if team_id == home_id:
                total_points_for += home_score
                total_points_against += away_score
            elif team_id == away_id:
                total_points_for += away_score
                total_points_against += home_score
            else:
                continue
            count += 1
        if count == 0:
            return None
        avg_for = total_points_for / count
        avg_against = total_points_against / count
        return {"points_for": avg_for, "points_against": avg_against}

    def _get_soccer_team_id(self, league_id: int, season: int, team_name: str):
        # Find team ID in a given league by name
        try:
            search_url = f"https://v3.football.api-sports.io/teams?search={team_name}"
            resp = requests.get(search_url, headers=self.api_sports_headers, timeout=10)
            resp.raise_for_status()
            teams = resp.json().get("response", [])
        except Exception as e:
            logger.error(f"Error searching team {team_name}: {e}")
            teams = []
        team_id = None
        for t in teams:
            team = t.get("team", {})
            if team and team.get("id"):
                cand_id = team["id"]
                try:
                    stats_url = f"https://v3.football.api-sports.io/teams/statistics?team={cand_id}&league={league_id}&season={season}"
                    stats_resp = requests.get(stats_url, headers=self.api_sports_headers, timeout=5)
                    # If this team has stats for the league, we found the correct team
                    if stats_resp.status_code == 200:
                        team_id = cand_id
                        break
                except Exception:
                    continue
        return team_id

    def _get_soccer_team_stats(self, league_id: int, season: int, team_id: int):
        # Get average goals for and against for the team in the league
        url = f"https://v3.football.api-sports.io/teams/statistics?league={league_id}&season={season}&team={team_id}"
        try:
            resp = requests.get(url, headers=self.api_sports_headers, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Error fetching stats for team {team_id} in league {league_id}: {e}")
            return None
        stats = resp.json().get("response", {})
        if not stats:
            return None
        goals = stats.get("goals", {})
        avg_for = avg_against = None
        if goals:
            avg_for_str = goals.get("for", {}).get("average", {}).get("total")
            avg_against_str = goals.get("against", {}).get("average", {}).get("total")
            try:
                avg_for = float(avg_for_str) if avg_for_str not in [None, ""] else None
            except:
                avg_for = None
            try:
                avg_against = float(avg_against_str) if avg_against_str not in [None, ""] else None
            except:
                avg_against = None
        # Fallback to manual average if needed
        if (avg_for is None or avg_against is None) and stats.get("fixtures"):
            played = stats["fixtures"].get("played", {}).get("total")
            goals_for_total = stats.get("goals", {}).get("for", {}).get("total", {}).get("total")
            goals_against_total = stats.get("goals", {}).get("against", {}).get("total", {}).get("total")
            if played and played > 0 and goals_for_total is not None and goals_against_total is not None:
                avg_for = goals_for_total / played
                avg_against = goals_against_total / played
        if avg_for is None or avg_against is None:
            return None
        return {"goals_for": avg_for, "goals_against": avg_against}

    def analyze(self, league: str, date: str, home_team: str, away_team: str):
        """Compute baseline expected scores for given matchup."""
        league_key = "EPL" if league in ["PremierLeague", "EPL"] else league
        is_soccer = league_key in self.league_id_map
        try:
            year = int(date[:4])
        except:
            year = None
        result = {
            "league": league,
            "date": date,
            "home": home_team,
            "away": away_team,
            "home_exp_score": None,
            "away_exp_score": None,
            "baseline_fallback": []
        }
        if is_soccer:
            league_id = self.league_id_map.get(league_key)
            season = year if year else 2023
            home_id = self._get_soccer_team_id(league_id, season, home_team)
            away_id = self._get_soccer_team_id(league_id, season, away_team)
            if not home_id or not away_id:
                logger.warning("Could not find team ID for one or both teams. Using neutral baseline for missing.")
            home_stats = self._get_soccer_team_stats(league_id, season, home_id) if home_id else None
            away_stats = self._get_soccer_team_stats(league_id, season, away_id) if away_id else None
            if home_stats and away_stats:
                # Combine team offense and opponent defense
                home_exp = (home_stats["goals_for"] + away_stats["goals_against"]) / 2.0
                away_exp = (away_stats["goals_for"] + home_stats["goals_against"]) / 2.0
                result["home_exp_score"] = home_exp
                result["away_exp_score"] = away_exp
            else:
                default = self.default_values["football"]
                if not home_stats:
                    result["baseline_fallback"].append(f"No data for {home_team}")
                if not away_stats:
                    result["baseline_fallback"].append(f"No data for {away_team}")
                result["home_exp_score"] = default["goals_for"]
                result["away_exp_score"] = default["goals_for"]
        else:
            if league.upper() == "NBA":
                home_id = self._get_nba_team_id(home_team)
                away_id = self._get_nba_team_id(away_team)
                if not home_id or not away_id:
                    logger.warning("Could not find team ID for one or both NBA teams. Using neutral baseline.")
                season_year = year if year and year > 0 else 2023
                home_stats = self._get_nba_team_stats(home_id, season_year) if home_id else None
                away_stats = self._get_nba_team_stats(away_id, season_year) if away_id else None
                if home_stats and away_stats:
                    home_exp = (home_stats["points_for"] + away_stats["points_against"]) / 2.0
                    away_exp = (away_stats["points_for"] + home_stats["points_against"]) / 2.0
                    result["home_exp_score"] = home_exp
                    result["away_exp_score"] = away_exp
                else:
                    default = self.default_values["basketball"]
                    if not home_stats:
                        result["baseline_fallback"].append(f"No data for {home_team}")
                    if not away_stats:
                        result["baseline_fallback"].append(f"No data for {away_team}")
                    result["home_exp_score"] = default["points_for"]
                    result["away_exp_score"] = default["points_for"]
            else:
                # Unknown league: use neutral baseline
                default = self.default_values["basketball"]
                result["baseline_fallback"].append("Using neutral baseline for non-specific league")
                result["home_exp_score"] = default["points_for"]
                result["away_exp_score"] = default["points_for"]
        return result

class FAZ16Engine:
    """Monte Carlo simulation engine to simulate match outcomes."""
    def simulate(self, analysis: dict, iterations: int = 1000):
        home_exp = analysis.get("home_exp_score")
        away_exp = analysis.get("away_exp_score")
        league = analysis.get("league")
        if home_exp is None or away_exp is None:
            return None
        # Determine if draw is possible (soccer and similar)
        league_upper = league.upper()
        is_soccer = league_upper in ["EPL", "PREMIERLEAGUE", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "CHAMPIONSLEAGUE"]
        results = {
            "home_wins": 0,
            "away_wins": 0,
            "draws": 0,
            "margin_counts": {"home_1": 0, "home_big": 0, "away_1": 0, "away_big": 0},
            "total_points": []
        }
        if is_soccer:
            # Poisson simulate goals for soccer
            lambda_home = home_exp
            lambda_away = away_exp
            for _ in range(iterations):
                home_goals = random.poisson(lam=lambda_home) if hasattr(random, 'poisson') else self._poisson_sample(lambda_home)
                away_goals = random.poisson(lam=lambda_away) if hasattr(random, 'poisson') else self._poisson_sample(lambda_away)
                if home_goals > away_goals:
                    results["home_wins"] += 1
                    if home_goals - away_goals == 1:
                        results["margin_counts"]["home_1"] += 1
                    else:
                        results["margin_counts"]["home_big"] += 1
                elif away_goals > home_goals:
                    results["away_wins"] += 1
                    if away_goals - home_goals == 1:
                        results["margin_counts"]["away_1"] += 1
                    else:
                        results["margin_counts"]["away_big"] += 1
                else:
                    results["draws"] += 1
                results["total_points"].append(home_goals + away_goals)
        else:
            # Normally distributed points for high-scoring sports
            std_home = 0.15 * home_exp
            std_away = 0.15 * away_exp
            for _ in range(iterations):
                home_pts = max(0, random.gauss(home_exp, std_home))
                away_pts = max(0, random.gauss(away_exp, std_away))
                home_pts = int(round(home_pts))
                away_pts = int(round(away_pts))
                # Resolve potential tie (e.g., overtime)
                if home_pts == away_pts:
                    if random.random() < 0.5:
                        home_pts += 1
                    else:
                        away_pts += 1
                if home_pts > away_pts:
                    results["home_wins"] += 1
                    margin = home_pts - away_pts
                    if margin <= 5:
                        results["margin_counts"]["home_1"] += 1
                    else:
                        results["margin_counts"]["home_big"] += 1
                else:
                    results["away_wins"] += 1
                    margin = away_pts - home_pts
                    if margin <= 5:
                        results["margin_counts"]["away_1"] += 1
                    else:
                        results["margin_counts"]["away_big"] += 1
                results["total_points"].append(home_pts + away_pts)
        results["iterations"] = iterations
        return results

    def _poisson_sample(self, lam):
        # Simple Poisson sampling (for use when random.poisson is not available)
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= random.random()
        return k - 1

class FAZ17Engine:
    """Market enrichment engine: fetches betting odds/lines and integrates with analysis."""
    def __init__(self, odds_api_key: str):
        self.odds_api_key = odds_api_key
        self.base_url = "https://api.the-odds-api.com/v4/sports"
        # Map league to The Odds API sport key
        self.sport_key_map = {
            "NBA": "basketball_nba",
            "EPL": "soccer_epl",
            "PremierLeague": "soccer_epl",
            "LaLiga": "soccer_spain_la_liga",
            "SerieA": "soccer_italy_serie_a",
            "Bundesliga": "soccer_germany_bundesliga",
            "Ligue1": "soccer_france_ligue_one",
            "ChampionsLeague": "soccer_uefa_champs_league",
            "NFL": "americanfootball_nfl",
        }
    def get_odds(self, league: str, home_team: str, away_team: str):
        sport_key = self.sport_key_map.get(league)
        if not sport_key:
            logger.warning(f"Sport key for league {league} not found for odds API.")
            return None
        url = f"{self.base_url}/{sport_key}/odds"
        params = {
            "apiKey": self.odds_api_key,
            "regions": "us",
            "markets": "spreads,totals",
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Error fetching odds: {e}")
            return None
        games = resp.json()
        if not games:
            return None
        # Find the matching game by team names
        home_lower = home_team.lower()
        away_lower = away_team.lower()
        game_data = None
        for game in games:
            teams = [t.lower() for t in game.get("teams", [])]
            if home_lower in teams and away_lower in teams:
                game_data = game
                break
        if not game_data:
            return None
        # Select a bookmaker (prefer DraftKings if available)
        book = None
        for bk in game_data.get("bookmakers", []):
            if bk.get("key") == "draftkings":
                book = bk
                break
        if not book:
            book = game_data["bookmakers"][0] if game_data.get("bookmakers") else None
        if not book:
            return None
        odds_info = {"spread_home": None, "spread_away": None, "total": None}
        for market in book.get("markets", []):
            if market.get("key") == "spreads":
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    point = outcome.get("point", None)
                    if point is None:
                        continue
                    if home_lower in name:
                        odds_info["spread_home"] = float(point)
                    if away_lower in name:
                        odds_info["spread_away"] = float(point)
            if market.get("key") == "totals":
                for outcome in market.get("outcomes", []):
                    if outcome.get("name") in ["Over", "Under"]:
                        odds_info["total"] = float(outcome.get("point", 0.0))
                        break
        return odds_info

class FAZ22Engine:
    """Risk and additional analysis engine."""
    def assess(self, analysis: dict, simulation: dict):
        if not simulation:
            return {"risk": None, "tempo": None}
        iterations = simulation.get("iterations", 1)
        home_wins = simulation.get("home_wins", 0)
        away_wins = simulation.get("away_wins", 0)
        draws = simulation.get("draws", 0)
        # Outcome probabilities
        p_home = home_wins / iterations
        p_away = away_wins / iterations
        p_draw = draws / iterations
        max_prob = max(p_home, p_away, p_draw)
        # Classify risk: high risk if no outcome is very likely
        if max_prob > 0.75:
            risk = "Low"
        elif max_prob > 0.55:
            risk = "Medium"
        else:
            risk = "High"
        # Calculate average total points/goals
        total_avg = 0.0
        if simulation["total_points"]:
            total_avg = sum(simulation["total_points"]) / len(simulation["total_points"])
        # Determine tempo flag by comparing to typical scoring levels
        league = analysis.get("league", "").upper()
        if league in ["NBA", "NFL", "MLB", "NHL"] or league not in ["EPL", "PREMIERLEAGUE", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "CHAMPIONSLEAGUE"]:
            tempo = "High" if total_avg >= 220 else "Low" if total_avg <= 180 else "Moderate"
        else:
            tempo = "High" if total_avg >= 3 else "Low" if total_avg <= 2 else "Moderate"
        return {"risk": risk, "tempo": tempo, "avg_total": total_avg}

class FAZ23Engine:
    """Summary and output assembly engine."""
    def summarize(self, analysis: dict, simulation: dict, market: dict, risk: str, tempo: str):
        home = analysis.get("home")
        away = analysis.get("away")
        home_pred_score = analysis.get("home_exp_score")
        away_pred_score = analysis.get("away_exp_score")
        if home_pred_score is not None and away_pred_score is not None:
            home_pred_score = round(home_pred_score, 1)
            away_pred_score = round(away_pred_score, 1)
        band_str = ""
        if simulation:
            iterations = simulation.get("iterations", 1)
            if simulation.get("draws", 0) > 0:
                # Include draw and 1-goal/2+ goal margins for soccer
                home1 = simulation["margin_counts"]["home_1"]
                homeb = simulation["margin_counts"]["home_big"]
                draw = simulation["draws"]
                away1 = simulation["margin_counts"]["away_1"]
                awayb = simulation["margin_counts"]["away_big"]
                band_str = (f"Home by 1: {home1*100/iterations:.1f}%, "
                            f"Home by 2+: {homeb*100/iterations:.1f}%, "
                            f"Draw: {draw*100/iterations:.1f}%, "
                            f"Away by 1: {away1*100/iterations:.1f}%, "
                            f"Away by 2+: {awayb*100/iterations:.1f}%")
            else:
                # Non-soccer: use 1-5 and 6+ point margins
                home1 = simulation["margin_counts"]["home_1"]
                homeb = simulation["margin_counts"]["home_big"]
                away1 = simulation["margin_counts"]["away_1"]
                awayb = simulation["margin_counts"]["away_big"]
                band_str = (f"Home by 1-5: {home1*100/iterations:.1f}%, "
                            f"Home by 6+: {homeb*100/iterations:.1f}%, "
                            f"Away by 1-5: {away1*100/iterations:.1f}%, "
                            f"Away by 6+: {awayb*100/iterations:.1f}%")
        market_str = ""
        if market:
            spread_home = market.get("spread_home")
            spread_away = market.get("spread_away")
            total_line = market.get("total")
            if spread_home is not None and spread_away is not None:
                # Determine market favorite and line
                if spread_home < 0:
                    market_fav = home
                    market_line = -spread_home
                elif spread_away < 0:
                    market_fav = away
                    market_line = -spread_away
                else:
                    market_fav = home if spread_home <= spread_away else away
                    market_line = spread_home or spread_away or 0
                # Model predicted margin from home perspective
                pred_margin = (analysis.get("home_exp_score") or 0) - (analysis.get("away_exp_score") or 0)
                pred_margin_val = round(pred_margin, 1)
                # Compare predicted margin to market line
                if pred_margin * (1 if market_fav == home else -1) > market_line:
                    lean_spread = f"Lean {home}" if market_fav == home else f"Lean {away}"
                elif pred_margin * (1 if market_fav == home else -1) < market_line:
                    lean_spread = f"Lean {away} (underdog)" if market_fav == home else f"Lean {home} (underdog)"
                else:
                    lean_spread = "No lean"
                market_str += f"Spread: {market_fav} -{market_line} (Model: {pred_margin_val}; {lean_spread})"
            if total_line is not None:
                pred_total = (analysis.get("home_exp_score") or 0) + (analysis.get("away_exp_score") or 0)
                pred_total_val = round(pred_total, 1)
                if pred_total_val > total_line + 0.5:
                    lean_total = "Over"
                elif pred_total_val < total_line - 0.5:
                    lean_total = "Under"
                else:
                    lean_total = "No lean"
                if market_str:
                    market_str += "; "
                market_str += f"Total: {total_line} (Model: {pred_total_val}; {lean_total})"
        else:
            market_str = "Odds data not available"
        summary_str = ""
        if analysis.get("home_exp_score") is not None:
            # Determine which team has projected edge
            if analysis["home_exp_score"] > analysis["away_exp_score"]:
                winner = home
            elif analysis["away_exp_score"] > analysis["home_exp_score"]:
                winner = away
            else:
                winner = "Neither team"
            summary_str = (f"{winner} is expected to have an edge in this matchup. "
                           f"Risk level is {risk.lower()}, and the game tempo looks {tempo.lower()} based on projections.")
            if market and market_str and "Lean" in market_str:
                if "underdog" in market_str:
                    summary_str += " The model indicates potential value on the underdog."
                elif "Lean" in market_str:
                    summary_str += " The model's predictions suggest a betting lean as noted above."
        return {"band_str": band_str, "risk": risk, "tempo": tempo, "market_str": market_str, "summary_str": summary_str}

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /analyze command, parse input, run analysis, and send output."""
    message = update.message.text
    try:
        _, params = message.split(' ', 1)
    except ValueError:
        await update.message.reply_text("Usage: /analyze <League> <Date YYYY-MM-DD> <Home Team> vs <Away Team>")
        return
    tokens = params.split()
    if len(tokens) < 4:
        await update.message.reply_text("Please provide league, date, home team, and away team.")
        return
    league = tokens[0]
    date = tokens[1]
    team_tokens = tokens[2:]
    # Split teams by "vs" if present, otherwise split half-half
    if any(tok.lower() == "vs" or tok.lower() == "vs." for tok in team_tokens):
        vs_index = next(i for i, tok in enumerate(team_tokens) if tok.lower().startswith("vs"))
        home_team = " ".join(team_tokens[:vs_index])
        away_team = " ".join(team_tokens[vs_index+1:])
    else:
        half = len(team_tokens) // 2
        home_team = " ".join(team_tokens[:half])
        away_team = " ".join(team_tokens[half:])
    home_team = home_team.strip().strip(',')
    away_team = away_team.strip().strip(',')
    logger.info(f"Analyzing game: League={league}, Date={date}, Home={home_team}, Away={away_team}")
    # Retrieve engine instances from application context
    faz13: FAZ13Engine = context.application.bot_data.get("faz13")
    faz16: FAZ16Engine = context.application.bot_data.get("faz16")
    faz17: FAZ17Engine = context.application.bot_data.get("faz17")
    faz22: FAZ22Engine = context.application.bot_data.get("faz22")
    faz23: FAZ23Engine = context.application.bot_data.get("faz23")
    if not all([faz13, faz16, faz17, faz22, faz23]):
        logger.error("Engines not initialized properly.")
        await update.message.reply_text("Error: engines not initialized.")
        return
    # Perform analysis
    analysis = faz13.analyze(league, date, home_team, away_team)
    simulation = faz16.simulate(analysis)
    # Get market odds (handle failures gracefully)
    try:
        market_data = faz17.get_odds(league, home_team, away_team)
    except Exception as e:
        logger.error(f"Market data fetch error: {e}")
        market_data = None
    # Assess risk and tempo
    assessment = faz22.assess(analysis, simulation)
    risk_level = assessment.get("risk")
    tempo_flag = assessment.get("tempo")
    avg_total = assessment.get("avg_total")
    # Compile summary
    summary_data = faz23.summarize(analysis, simulation, market_data, risk_level, tempo_flag)
    band_str = summary_data.get("band_str", "")
    risk = summary_data.get("risk", "")
    tempo = summary_data.get("tempo", "")
    market_str = summary_data.get("market_str", "")
    summary_str = summary_data.get("summary_str", "")
    # Format output message (HTML)
    title_line = f"<b>{html.escape(league)} {html.escape(date)}: {html.escape(home_team)} vs {html.escape(away_team)}</b>"
    lines = []
    if band_str:
        lines.append(f"<b>Band Values:</b> {html.escape(band_str)}")
    if risk:
        lines.append(f"<b>Risk Level:</b> {html.escape(risk)}")
    if tempo:
        tempo_text = tempo
        if avg_total:
            if league.upper() in ['EPL', 'PREMIERLEAGUE', 'LALIGA', 'SERIEA', 'BUNDESLIGA', 'LIGUE1', 'CHAMPIONSLEAGUE']:
                tempo_text += f" (Total ~{avg_total:.1f} goals)"
            else:
                tempo_text += f" (Total ~{avg_total:.1f} points)"
        lines.append(f"<b>Tempo:</b> {html.escape(tempo_text)}")
    if market_str:
        lines.append(f"<b>Market:</b> {html.escape(market_str)}")
    if summary_str:
        lines.append(f"<b>Summary:</b> {html.escape(summary_str)}")
    output_text = title_line + "\n" + "\n".join(lines)
    try:
        await update.message.reply_text(output_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        # Fallback to unescaped text if formatting fails
        await update.message.reply_text(html.unescape(output_text))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler to log exceptions."""
    logger.error("Exception in update handling:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("An unexpected error occurred. Please try again later.")

def main():
    # Initialize engines and Telegram bot application
    faz13 = FAZ13Engine(BALLDONTLIE_API_KEY, API_SPORTS_KEY)
    faz16 = FAZ16Engine()
    faz17 = FAZ17Engine(ODDS_API_KEY)
    faz22 = FAZ22Engine()
    faz23 = FAZ23Engine()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.bot_data["faz13"] = faz13
    application.bot_data["faz16"] = faz16
    application.bot_data["faz17"] = faz17
    application.bot_data["faz22"] = faz22
    application.bot_data["faz23"] = faz23
    # Register command handler and error handler
    application.add_handler(CommandHandler("analyze", analyze_command))
    application.add_error_handler(error_handler)
    logger.info("Bot starting... Listening for /analyze commands.")
    application.run_polling()

if __name__ == "__main__":
    main()
