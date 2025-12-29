import os
import requests
from datetime import datetime
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Configuration and global settings
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
BALLDONTLIE_API_KEY = os.getenv('BALLDONTLIE_API_KEY')
USE_BALLDONTLIE_FALLBACK = True  # Flag to enable/disable BallDontLie API fallback

# Set up logging for debugging and tracking
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global caches for team IDs and baseline stats to reduce repeated API calls
team_id_cache = {}
team_list_fetched = False

class Faz13Engine:
    """FAZ-13: Main analysis engine (date processing, season calculations, baseline stats retrieval)"""
    # Static cache for baseline stats: keys as (team_id, season_year), values as dict of stats
    baseline_cache = {}

    def __init__(self):
        # Initialization if needed (e.g., load baseline data from a local source)
        pass

    @staticmethod
    def parse_date(date_str: str):
        """Parse a date string (multiple formats) into a date object."""
        if not date_str:
            return None
        date_str = date_str.strip()
        try:
            # Try ISO format YYYY-MM-DD
            dt = datetime.fromisoformat(date_str)
            return dt.date()
        except Exception:
            pass
        # Try common alternate formats
        for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.date()
            except Exception:
                continue
        logger.error(f"Unable to parse date string: {date_str}")
        return None

    @staticmethod
    def determine_season(date_obj):
        """Determine the season year for a given date (NBA seasons span two calendar years)."""
        if date_obj is None:
            date_obj = datetime.today().date()
        year = date_obj.year
        month = date_obj.month
        # Season year is the starting year of the NBA season
        if month < 7:
            season_year = year - 1  # Jan-June => season started last year
        else:
            if month >= 10:
                season_year = year  # Oct-Dec => season starts this year
            else:
                season_year = year - 1  # July-Aug-Sep (offseason) -> use previous season
        return season_year

    def _team_baseline(self, team_name: str, season_year: int):
        """Get baseline stats for a team in a season (offense, defense averages, W-L record).
        Uses local cache or falls back to BallDontLie API if enabled."""
        # Normalize team name for lookup
        name_key = team_name.strip().lower()
        # Check cache by team id (if already fetched)
        team_id = get_team_id(team_name)
        if team_id is None:
            logger.error(f"Team ID for '{team_name}' not found.")
            return None
        cache_key = (team_id, season_year)
        if cache_key in Faz13Engine.baseline_cache:
            return Faz13Engine.baseline_cache[cache_key]
        # If not in cache, attempt BallDontLie API (fallback)
        if USE_BALLDONTLIE_FALLBACK:
            if BALLDONTLIE_API_KEY is None:
                logger.error("BallDontLie API key not provided. Cannot fetch data.")
                return None
            try:
                games = []
                page = 1
                per_page = 100  # max results per page
                while True:
                    params = {
                        'team_ids[]': team_id,
                        'seasons[]': season_year,
                        'postseason': 'false',
                        'per_page': per_page,
                        'page': page
                    }
                    headers = {'Authorization': BALLDONTLIE_API_KEY}
                    resp = requests.get('https://api.balldontlie.io/v1/games', params=params, headers=headers)
                    if resp.status_code != 200:
                        logger.error(f"Failed to fetch games for team {team_id}, season {season_year}: HTTP {resp.status_code}")
                        return None
                    data = resp.json()
                    page_games = data.get('data', [])
                    if not page_games:
                        break
                    games.extend(page_games)
                    if len(page_games) < per_page:
                        break
                    page += 1
                if not games:
                    logger.warning(f"No games found for team {team_id} in season {season_year}")
                    return None
                total_for = total_against = 0
                wins = losses = 0
                for game in games:
                    home = game.get('home_team')
                    visitor = game.get('visitor_team')
                    home_score = game.get('home_team_score')
                    visitor_score = game.get('visitor_team_score')
                    if home and visitor:
                        if home['id'] == team_id:
                            points_for = home_score
                            points_against = visitor_score
                        elif visitor['id'] == team_id:
                            points_for = visitor_score
                            points_against = home_score
                        else:
                            continue
                        total_for += points_for
                        total_against += points_against
                        if points_for > points_against:
                            wins += 1
                        elif points_for < points_against:
                            losses += 1
                game_count = len(games)
                avg_for = total_for / game_count
                avg_against = total_against / game_count
                stats = {
                    'team_name': team_name,
                    'team_id': team_id,
                    'season': season_year,
                    'offense': avg_for,
                    'defense': avg_against,
                    'games': game_count,
                    'wins': wins,
                    'losses': losses
                }
                Faz13Engine.baseline_cache[cache_key] = stats
                return stats
            except Exception as e:
                logger.exception(f"Exception fetching baseline for {team_name}: {e}")
                return None
        else:
            logger.error(f"No baseline data for {team_name} (fallback disabled).")
            return None

    def analyze_matchup(self, team1: str, team2: str, date=None):
        """Perform main analysis: get baselines, compute predicted score, etc."""
        season_year = self.determine_season(date)
        baseline1 = self._team_baseline(team1, season_year)
        baseline2 = self._team_baseline(team2, season_year)
        if baseline1 is None or baseline2 is None:
            return None
        # Simple predicted score using average of team offense and opponent defense
        pred_score1 = (baseline1['offense'] + baseline2['defense']) / 2.0
        pred_score2 = (baseline2['offense'] + baseline1['defense']) / 2.0
        return {
            'team1': team1,
            'team2': team2,
            'team1_id': baseline1.get('team_id'),
            'team2_id': baseline2.get('team_id'),
            'season_year': season_year,
            'date': date,
            'baseline1': baseline1,
            'baseline2': baseline2,
            'pred_score1': pred_score1,
            'pred_score2': pred_score2
        }

class Faz16MonteCarlo:
    """FAZ-16: Monte Carlo simulation engine for matchup outcomes"""
    def simulate_matchup(self, pred_score1: float, pred_score2: float, simulations: int = 10000):
        import random
        std1 = max(8.0, 0.1 * pred_score1)
        std2 = max(8.0, 0.1 * pred_score2)
        wins1 = wins2 = 0
        total_score1 = total_score2 = 0.0
        for _ in range(simulations):
            s1 = random.gauss(pred_score1, std1)
            s2 = random.gauss(pred_score2, std2)
            if s1 < 0:
                s1 = 0
            if s2 < 0:
                s2 = 0
            total_score1 += s1
            total_score2 += s2
            if s1 > s2:
                wins1 += 1
            elif s2 > s1:
                wins2 += 1
            # ignore ties (very unlikely with continuous distribution)
        win_prob1 = wins1 / simulations * 100.0
        win_prob2 = wins2 / simulations * 100.0
        avg_score1 = total_score1 / simulations
        avg_score2 = total_score2 / simulations
        return {
            'win_prob1': win_prob1,
            'win_prob2': win_prob2,
            'avg_score1': avg_score1,
            'avg_score2': avg_score2
        }

class Faz17MarketEnrichment:
    """FAZ-17: Market enrichment engine (fetch betting market odds)"""
    def get_market_data(self, team1: str, team2: str, date=None):
        if date is None:
            return {}
        if BALLDONTLIE_API_KEY is None:
            logger.warning("No BallDontLie API key; skipping market data fetch.")
            return {}
        try:
            team1_id = get_team_id(team1)
            team2_id = get_team_id(team2)
            if team1_id is None or team2_id is None:
                logger.error(f"Team IDs not found for {team1} or {team2}.")
                return {}
            params = {
                'dates[]': date.strftime("%Y-%m-%d"),
                'team_ids[]': team1_id,
                'team_ids[]': team2_id,
                'per_page': 100
            }
            headers = {'Authorization': BALLDONTLIE_API_KEY}
            resp = requests.get('https://api.balldontlie.io/v1/games', params=params, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Failed to fetch game info for odds: HTTP {resp.status_code}")
                return {}
            games = resp.json().get('data', [])
            game_id = None
            home_id = away_id = None
            for game in games:
                home = game.get('home_team')
                visitor = game.get('visitor_team')
                if home and visitor:
                    h_id = home.get('id')
                    v_id = visitor.get('id')
                    if {h_id, v_id} == {team1_id, team2_id}:
                        game_id = game.get('id')
                        home_id = h_id
                        away_id = v_id
                        break
            if game_id is None:
                logger.info(f"No direct game found on {date} for {team1} vs {team2}.")
                return {}
            # Fetch odds for the identified game
            params = {'game_ids[]': game_id}
            resp2 = requests.get('https://api.balldontlie.io/v2/odds', params=params, headers=headers)
            if resp2.status_code != 200:
                logger.error(f"Failed to fetch odds for game {game_id}: HTTP {resp2.status_code}")
                return {}
            odds_entries = resp2.json().get('data', [])
            if not odds_entries:
                logger.info(f"No odds data available for game {game_id}.")
                return {}
            # Pick a vendor (e.g., draftkings) or default to first
            odds = None
            for entry in odds_entries:
                if entry.get('vendor') == 'draftkings':
                    odds = entry
                    break
            if odds is None:
                odds = odds_entries[0]
            ml_home = odds.get('moneyline_home_odds')
            ml_away = odds.get('moneyline_away_odds')
            if ml_home is None or ml_away is None:
                return {}
            # Identify which team is home in this matchup
            if home_id == team1_id:
                team1_odds_american = ml_home
                team2_odds_american = ml_away
            else:
                team1_odds_american = ml_away
                team2_odds_american = ml_home
            def american_to_decimal(odds):
                odds = float(odds)
                if odds < 0:
                    return 1 + (100 / -odds)
                else:
                    return 1 + (odds / 100)
            dec1 = american_to_decimal(team1_odds_american)
            dec2 = american_to_decimal(team2_odds_american)
            prob1 = (1/dec1) * 100
            prob2 = (1/dec2) * 100
            return {
                'team1_odds_dec': dec1,
                'team2_odds_dec': dec2,
                'team1_prob': prob1,
                'team2_prob': prob2,
                'team1_odds_american': team1_odds_american,
                'team2_odds_american': team2_odds_american
            }
        except Exception as e:
            logger.exception(f"Exception fetching market data: {e}")
            return {}

class Faz22ExtraAnalysis:
    """FAZ-22: Additional analysis engine (extra insights based on baseline stats)"""
    def analyze(self, baseline1: dict, baseline2: dict):
        if not baseline1 or not baseline2:
            return ""
        team1 = baseline1['team_name']
        team2 = baseline2['team_name']
        off1 = baseline1['offense']
        def1 = baseline1['defense']
        off2 = baseline2['offense']
        def2 = baseline2['defense']
        diff1 = off1 - def1
        diff2 = off2 - def2
        w1 = baseline1.get('wins', 0)
        l1 = baseline1.get('losses', 0)
        w2 = baseline2.get('wins', 0)
        l2 = baseline2.get('losses', 0)
        # Focus on point differential in analysis
        desc1 = (f"outscored opponents by {diff1:.1f} ppg" if diff1 >= 0 else f"were outscored by {abs(diff1):.1f} ppg")
        desc2 = (f"outscored opponents by {diff2:.1f} ppg" if diff2 >= 0 else f"were outscored by {abs(diff2):.1f} ppg")
        analysis_text = (f"{team1} {desc1}; {team2} {desc2}")
        return analysis_text

class Faz23ExtraAnalysis:
    """FAZ-23: Additional analysis engine (value bets or qualitative insights)"""
    def analyze(self, sim_result: dict, market_data: dict, team1: str, team2: str):
        if not sim_result:
            return ""
        win_prob1 = sim_result['win_prob1']
        win_prob2 = sim_result['win_prob2']
        text = ""
        if market_data and 'team1_prob' in market_data and market_data['team1_prob'] is not None:
            market_prob1 = market_data['team1_prob']
            market_prob2 = market_data['team2_prob']
            diff = win_prob1 - market_prob1
            if diff > 5.0:
                text = f"The model favors {team1} more than the market (Model {win_prob1:.1f}% vs Market {market_prob1:.1f}%). Value may be on {team1}."
            elif diff < -5.0:
                text = f"The model favors {team2} more than the market (Model {win_prob2:.1f}% vs Market {market_prob2:.1f}%). Value may be on {team2}."
            else:
                text = "The model's win probabilities are in line with the market odds."
        else:
            if abs(win_prob1 - win_prob2) < 1e-6:
                text = "This matchup is expected to be very even (50/50)."
            else:
                favorite = team1 if win_prob1 > win_prob2 else team2
                fav_prob = max(win_prob1, win_prob2)
                if fav_prob >= 75:
                    descriptor = "heavily favored"
                elif fav_prob >= 60:
                    descriptor = "favored"
                else:
                    descriptor = "slightly favored"
                text = f"{favorite} is {descriptor} to win (approximately {fav_prob:.0f}% chance)."
        return text

def get_team_id(team_name: str):
    """Get BallDontLie team ID from team name or abbreviation."""
    global team_id_cache, team_list_fetched
    if not team_name:
        return None
    key = team_name.strip().lower()
    if key in team_id_cache:
        return team_id_cache[key]
    if not team_list_fetched:
        if BALLDONTLIE_API_KEY is None:
            logger.warning("No API key provided for BallDontLie; cannot fetch team list.")
            return None
        try:
            headers = {'Authorization': BALLDONTLIE_API_KEY}
            resp = requests.get('https://api.balldontlie.io/v1/teams', headers=headers)
            if resp.status_code == 200:
                teams = resp.json().get('data', [])
                for team in teams:
                    tid = team.get('id')
                    fullname = team.get('full_name', "").lower()
                    abbr = team.get('abbreviation', "").lower()
                    nickname = team.get('name', "").lower()
                    if fullname:
                        team_id_cache[fullname] = tid
                    if abbr:
                        team_id_cache[abbr] = tid
                    if nickname:
                        team_id_cache[nickname] = tid
                team_list_fetched = True
            else:
                logger.error(f"Failed to fetch team list: HTTP {resp.status_code}")
        except Exception as e:
            logger.exception(f"Exception fetching team list: {e}")
    return team_id_cache.get(key)

# Telegram command handler
def analyze_command(update: Update, context: CallbackContext):
    """Handle /analyze or /predict command to analyze a matchup."""
    try:
        args = context.args
        if not args:
            update.message.reply_text("Lütfen iki takım ismi ve isteğe bağlı tarih belirtin. Örnek kullanım: /predict Lakers vs Warriors 2024-01-15")
            return
        # Combine args to a single string to handle multi-word team names
        input_text = " ".join(args)
        team1_str = team2_str = None
        date_str = None
        # Look for vs separator
        for sep in [" vs ", " VS ", " v ", " V "]:
            if sep in input_text:
                parts = input_text.split(sep)
                if len(parts) >= 2:
                    team1_str = parts[0].strip()
                    second_part = parts[1].strip()
                    # Check if last token in second_part is a date
                    tokens = second_part.split()
                    if len(tokens) > 1:
                        maybe_date = tokens[-1]
                        parsed_date = Faz13Engine.parse_date(maybe_date)
                        if parsed_date:
                            date_str = maybe_date
                            team2_str = " ".join(tokens[:-1]).strip()
                        else:
                            team2_str = second_part
                    else:
                        team2_str = second_part
                break
        if team1_str is None or team2_str is None:
            # If no explicit "vs", try splitting tokens in half
            tokens = input_text.split()
            if tokens:
                maybe_date = Faz13Engine.parse_date(tokens[-1])
                if maybe_date:
                    date_str = tokens[-1]
                    tokens = tokens[:-1]
            if len(tokens) >= 2:
                mid = len(tokens) // 2
                team1_str = " ".join(tokens[:mid]).strip()
                team2_str = " ".join(tokens[mid:]).strip()
            else:
                update.message.reply_text("Lütfen iki takım ismi girin.")
                return
        game_date = Faz13Engine.parse_date(date_str) if date_str else None
        faz13 = Faz13Engine()
        faz16 = Faz16MonteCarlo()
        faz17 = Faz17MarketEnrichment()
        faz22 = Faz22ExtraAnalysis()
        faz23 = Faz23ExtraAnalysis()
        result = faz13.analyze_matchup(team1_str, team2_str, game_date)
        if result is None:
            update.message.reply_text("Analiz için yeterli veri bulunamadı. Takım isimlerini kontrol edin.")
            return
        sim_result = faz16.simulate_matchup(result['pred_score1'], result['pred_score2'])
        market_data = {}
        if game_date:
            market_data = faz17.get_market_data(result['team1'], result['team2'], game_date)
        extra_analysis_text = faz22.analyze(result['baseline1'], result['baseline2'])
        extra_value_text = faz23.analyze(sim_result, market_data, result['team1'], result['team2'])
        # Build response message
        season_year = result['season_year']
        season_str = f"{season_year}-{(season_year+1)%100:02d}"
        team1 = result['team1']
        team2 = result['team2']
        pred1 = result['pred_score1']
        pred2 = result['pred_score2']
        win_prob1 = sim_result['win_prob1']
        win_prob2 = sim_result['win_prob2']
        base1 = result['baseline1']
        base2 = result['baseline2']
        message_lines = []
        message_lines.append(f"Season {season_str} stats:")
        message_lines.append(f"{team1}: Offense {base1['offense']:.1f} ppg, Defense {base1['defense']:.1f} ppg, Record {base1.get('wins',0)}-{base1.get('losses',0)}")
        message_lines.append(f"{team2}: Offense {base2['offense']:.1f} ppg, Defense {base2['defense']:.1f} ppg, Record {base2.get('wins',0)}-{base2.get('losses',0)}")
        message_lines.append(f"Predicted Score: {team1} {pred1:.0f} - {team2} {pred2:.0f}")
        message_lines.append(f"Win Probability: {team1} {win_prob1:.1f}%, {team2} {win_prob2:.1f}%")
        if market_data and 'team1_odds_dec' in market_data:
            odds1 = market_data['team1_odds_dec']
            odds2 = market_data['team2_odds_dec']
            prob1 = market_data.get('team1_prob')
            prob2 = market_data.get('team2_prob')
            if odds1 and odds2 and prob1 is not None and prob2 is not None:
                message_lines.append(f"Market Odds: {team1} {odds1:.2f} (impl. {prob1:.1f}%), {team2} {odds2:.2f} (impl. {prob2:.1f}%)")
        if extra_analysis_text:
            message_lines.append(extra_analysis_text)
        if extra_value_text:
            message_lines.append(extra_value_text)
        response = "\n".join(message_lines)
        update.message.reply_text(response)
    except Exception as e:
        logger.exception(f"Error in analyze_command: {e}")
        update.message.reply_text("Komut işlenirken bir hata oluştu.")

def main():
    if not TELEGRAM_TOKEN:
        logger.error("Telegram token is not set. Set the TELEGRAM_TOKEN environment variable.")
        return
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("analyze", analyze_command))
    dp.add_handler(CommandHandler("predict", analyze_command))
    updater.start_polling()
    logger.info("Bot is running...")
    updater.idle()

if __name__ == "__main__":
    main() 
