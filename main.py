import os
import logging
import html
import math
import random
import requests
from typing import Any, Dict, Optional, Tuple, List

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -----------------------------
# Env
# -----------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
BALLDONTLIE_API_KEY = os.environ.get("BALLDONTLIE_API_KEY")
API_SPORTS_KEY = os.environ.get("API_SPORTS_KEY")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
if not BALLDONTLIE_API_KEY:
    raise RuntimeError("Missing BALLDONTLIE_API_KEY")
if not API_SPORTS_KEY:
    raise RuntimeError("Missing API_SPORTS_KEY")
if not ODDS_API_KEY:
    raise RuntimeError("Missing ODDS_API_KEY")


# =========================================================
# FAZ-13 Engine (Baseline / expected score)
# =========================================================
class FAZ13Engine:
    """
    Core analysis engine: fetches baseline data for teams and computes initial predictions.
    """

    def __init__(self, balldontlie_api_key: str, api_sports_key: str):
        self.balldontlie_api_key = balldontlie_api_key
        self.api_sports_key = api_sports_key

        # Cache team data to reduce API calls
        self.team_cache: Dict[str, Dict[str, int]] = {
            "NBA": {},
            "NFL": {},
            "MLB": {},
            "NHL": {},
            "EPL": {},
            "LaLiga": {},
            "SerieA": {},
            "Bundesliga": {},
            "Ligue1": {},
            "ChampionsLeague": {},
        }

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
            "football": {"goals_for": 1.2, "goals_against": 1.2},
        }

        # API headers
        # balldontlie v1 uses Authorization header with API key
        self.bdl_headers = {"Authorization": self.balldontlie_api_key}
        self.api_sports_headers = {"x-apisports-key": self.api_sports_key}

    def _get_nba_team_id(self, team_name: str) -> Optional[int]:
        if not self.team_cache["NBA"]:
            url = "https://api.balldontlie.io/v1/teams"
            try:
                resp = requests.get(url, headers=self.bdl_headers, timeout=15)
                resp.raise_for_status()
                data = resp.json().get("data", [])
            except Exception as e:
                logger.error(f"Error fetching NBA teams: {e}")
                return None

            for team in data:
                full_name = team.get("full_name")
                tid = team.get("id")
                if full_name and tid:
                    self.team_cache["NBA"][full_name.lower()] = tid

        return self.team_cache["NBA"].get(team_name.lower())

    def _get_nba_team_stats(self, team_id: int, season_year: int) -> Optional[Dict[str, float]]:
        url = f"https://api.balldontlie.io/v1/games?team_ids[]={team_id}&seasons[]={season_year}&per_page=100"
        try:
            resp = requests.get(url, headers=self.bdl_headers, timeout=15)
            resp.raise_for_status()
            games = resp.json().get("data", [])
        except Exception as e:
            logger.error(f"Error fetching NBA games for team {team_id}: {e}")
            return None

        if not games:
            return None

        total_points_for = 0
        total_points_against = 0
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

        return {
            "points_for": total_points_for / count,
            "points_against": total_points_against / count,
            "sample_n": float(count),
        }

    def _get_soccer_team_id(self, league_id: int, season: int, team_name: str) -> Optional[int]:
        try:
            search_url = f"https://v3.football.api-sports.io/teams?search={team_name}"
            resp = requests.get(search_url, headers=self.api_sports_headers, timeout=15)
            resp.raise_for_status()
            teams = resp.json().get("response", [])
        except Exception as e:
            logger.error(f"Error searching team {team_name}: {e}")
            teams = []

        team_id: Optional[int] = None
        for t in teams:
            team = t.get("team", {})
            if team and team.get("id"):
                cand_id = team["id"]
                try:
                    stats_url = (
                        f"https://v3.football.api-sports.io/teams/statistics"
                        f"?team={cand_id}&league={league_id}&season={season}"
                    )
                    stats_resp = requests.get(stats_url, headers=self.api_sports_headers, timeout=10)
                    if stats_resp.status_code == 200:
                        team_id = cand_id
                        break
                except Exception:
                    continue
        return team_id

    def _get_soccer_team_stats(self, league_id: int, season: int, team_id: int) -> Optional[Dict[str, float]]:
        url = f"https://v3.football.api-sports.io/teams/statistics?league={league_id}&season={season}&team={team_id}"
        try:
            resp = requests.get(url, headers=self.api_sports_headers, timeout=15)
            resp.raise_for_status()
            stats = resp.json().get("response", {})
        except Exception as e:
            logger.error(f"Error fetching stats for team {team_id} in league {league_id}: {e}")
            return None

        if not stats:
            return None

        goals = stats.get("goals", {})
        avg_for = None
        avg_against = None

        if goals:
            avg_for_str = goals.get("for", {}).get("average", {}).get("total")
            avg_against_str = goals.get("against", {}).get("average", {}).get("total")
            try:
                avg_for = float(avg_for_str) if avg_for_str not in [None, ""] else None
            except Exception:
                avg_for = None
            try:
                avg_against = float(avg_against_str) if avg_against_str not in [None, ""] else None
            except Exception:
                avg_against = None

        if avg_for is None or avg_against is None:
            fixtures = stats.get("fixtures", {})
            played = fixtures.get("played", {}).get("total")
            goals_for_total = goals.get("for", {}).get("total", {}).get("total")
            goals_against_total = goals.get("against", {}).get("total", {}).get("total")
            if played and played > 0 and goals_for_total is not None and goals_against_total is not None:
                avg_for = goals_for_total / played
                avg_against = goals_against_total / played

        if avg_for is None or avg_against is None:
            return None

        return {"goals_for": float(avg_for), "goals_against": float(avg_against)}

    def analyze(self, league: str, date: str, home_team: str, away_team: str) -> Dict[str, Any]:
        league_key = "EPL" if league in ["PremierLeague", "EPL"] else league
        is_soccer = league_key in self.league_id_map

        try:
            year = int(date[:4])
        except Exception:
            year = None

        result: Dict[str, Any] = {
            "league": league,
            "date": date,
            "home": home_team,
            "away": away_team,
            "home_exp_score": None,
            "away_exp_score": None,
            "baseline_fallback": [],
            "baseline_n_home": 0,
            "baseline_n_away": 0,
        }

        if is_soccer:
            league_id = self.league_id_map.get(league_key)
            season = year if year else 2023

            home_id = self._get_soccer_team_id(league_id, season, home_team) if league_id else None
            away_id = self._get_soccer_team_id(league_id, season, away_team) if league_id else None

            home_stats = self._get_soccer_team_stats(league_id, season, home_id) if home_id and league_id else None
            away_stats = self._get_soccer_team_stats(league_id, season, away_id) if away_id and league_id else None

            if home_stats and away_stats:
                home_exp = (home_stats["goals_for"] + away_stats["goals_against"]) / 2.0
                away_exp = (away_stats["goals_for"] + home_stats["goals_against"]) / 2.0
                result["home_exp_score"] = home_exp
                result["away_exp_score"] = away_exp
                # sample N soccer is not cleanly available here → leave 0
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

                season_year = year if year and year > 0 else 2023

                home_stats = self._get_nba_team_stats(home_id, season_year) if home_id else None
                away_stats = self._get_nba_team_stats(away_id, season_year) if away_id else None

                if home_stats and away_stats:
                    home_exp = (home_stats["points_for"] + away_stats["points_against"]) / 2.0
                    away_exp = (away_stats["points_for"] + home_stats["points_against"]) / 2.0
                    result["home_exp_score"] = home_exp
                    result["away_exp_score"] = away_exp
                    result["baseline_n_home"] = int(home_stats.get("sample_n", 0))
                    result["baseline_n_away"] = int(away_stats.get("sample_n", 0))
                else:
                    default = self.default_values["basketball"]
                    if not home_stats:
                        result["baseline_fallback"].append(f"No data for {home_team}")
                    if not away_stats:
                        result["baseline_fallback"].append(f"No data for {away_team}")
                    result["home_exp_score"] = default["points_for"]
                    result["away_exp_score"] = default["points_for"]
            else:
                default = self.default_values["basketball"]
                result["baseline_fallback"].append("Using neutral baseline for non-specific league")
                result["home_exp_score"] = default["points_for"]
                result["away_exp_score"] = default["points_for"]

        return result


# =========================================================
# FAZ-16 Engine (Simulation)
# =========================================================
class FAZ16Engine:
    def simulate(self, analysis: Dict[str, Any], iterations: int = 2000) -> Optional[Dict[str, Any]]:
        home_exp = analysis.get("home_exp_score")
        away_exp = analysis.get("away_exp_score")
        league = (analysis.get("league") or "").upper()

        if home_exp is None or away_exp is None:
            return None

        is_soccer = league in [
            "EPL",
            "PREMIERLEAGUE",
            "LALIGA",
            "SERIEA",
            "BUNDESLIGA",
            "LIGUE1",
            "CHAMPIONSLEAGUE",
        ]

        results: Dict[str, Any] = {
            "home_wins": 0,
            "away_wins": 0,
            "draws": 0,
            "margin_counts": {"home_1": 0, "home_big": 0, "away_1": 0, "away_big": 0},
            "total_points": [],
            "iterations": iterations,
        }

        if is_soccer:
            lambda_home = max(0.01, float(home_exp))
            lambda_away = max(0.01, float(away_exp))
            for _ in range(iterations):
                home_goals = self._poisson_sample(lambda_home)
                away_goals = self._poisson_sample(lambda_away)
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
            std_home = max(1.0, 0.15 * float(home_exp))
            std_away = max(1.0, 0.15 * float(away_exp))

            for _ in range(iterations):
                home_pts = max(0.0, random.gauss(float(home_exp), std_home))
                away_pts = max(0.0, random.gauss(float(away_exp), std_away))
                home_pts_i = int(round(home_pts))
                away_pts_i = int(round(away_pts))

                # Resolve tie
                if home_pts_i == away_pts_i:
                    if random.random() < 0.5:
                        home_pts_i += 1
                    else:
                        away_pts_i += 1

                if home_pts_i > away_pts_i:
                    results["home_wins"] += 1
                    margin = home_pts_i - away_pts_i
                    if margin <= 5:
                        results["margin_counts"]["home_1"] += 1
                    else:
                        results["margin_counts"]["home_big"] += 1
                else:
                    results["away_wins"] += 1
                    margin = away_pts_i - home_pts_i
                    if margin <= 5:
                        results["margin_counts"]["away_1"] += 1
                    else:
                        results["margin_counts"]["away_big"] += 1

                results["total_points"].append(home_pts_i + away_pts_i)

        return results

    def _poisson_sample(self, lam: float) -> int:
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= random.random()
        return k - 1


# =========================================================
# FAZ-17 Engine (Market)
# =========================================================
class FAZ17Engine:
    def __init__(self, odds_api_key: str):
        self.odds_api_key = odds_api_key
        self.base_url = "https://api.the-odds-api.com/v4/sports"
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

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").lower().replace(".", "").replace(",", "").split())

    def get_odds(self, league: str, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        HER ZAMAN dict döner.
        - status: OK | NO_MARKET | API_CONNECTION_ERROR | UNSUPPORTED_LEAGUE
        - reason: detay
        - total, spread_home, spread_away: float|None
        """
        sport_key = self.sport_key_map.get(league)
        if not sport_key:
            return {
                "status": "UNSUPPORTED_LEAGUE",
                "reason": f"No sport_key for league={league}",
                "total": None,
                "spread_home": None,
                "spread_away": None,
                "bookmaker": None,
            }

        url = f"{self.base_url}/{sport_key}/odds"
        params = {
            "apiKey": self.odds_api_key,
            "regions": "us",
            "markets": "spreads,totals",
            "oddsFormat": "decimal",
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            games = resp.json()
        except Exception as e:
            logger.error(f"Odds API error: {e}")
            return {
                "status": "API_CONNECTION_ERROR",
                "reason": str(e),
                "total": None,
                "spread_home": None,
                "spread_away": None,
                "bookmaker": None,
            }

        if not games:
            return {
                "status": "NO_MARKET",
                "reason": "EMPTY_GAMES",
                "total": None,
                "spread_home": None,
                "spread_away": None,
                "bookmaker": None,
            }

        home_n = self._norm(home_team)
        away_n = self._norm(away_team)

        match = None
        for g in games:
            teams = [self._norm(t) for t in (g.get("teams") or [])]
            if home_n in teams and away_n in teams:
                match = g
                break

        if not match:
            return {
                "status": "NO_MARKET",
                "reason": "MATCH_NOT_FOUND_IN_ODDS_LIST",
                "total": None,
                "spread_home": None,
                "spread_away": None,
                "bookmaker": None,
            }

        bookmakers = match.get("bookmakers") or []
        if not bookmakers:
            return {
                "status": "NO_MARKET",
                "reason": "NO_BOOKMAKERS",
                "total": None,
                "spread_home": None,
                "spread_away": None,
                "bookmaker": None,
            }

        # Prefer DraftKings if exists, else first
        book = None
        for bk in bookmakers:
            if bk.get("key") == "draftkings":
                book = bk
                break
        if not book:
            book = bookmakers[0]

        odds_info: Dict[str, Any] = {
            "status": "OK",
            "reason": "-",
            "total": None,
            "spread_home": None,
            "spread_away": None,
            "bookmaker": book.get("key"),
        }

        markets = book.get("markets") or []
        for m in markets:
            key = m.get("key")
            outs = m.get("outcomes") or []
            if key == "spreads":
                for o in outs:
                    nm = self._norm(o.get("name", ""))
                    pt = o.get("point", None)
                    if pt is None:
                        continue
                    try:
                        ptf = float(pt)
                    except Exception:
                        continue
                    if home_n in nm:
                        odds_info["spread_home"] = ptf
                    elif away_n in nm:
                        odds_info["spread_away"] = ptf
            elif key == "totals":
                # totals outcomes include Over/Under with same point
                for o in outs:
                    if o.get("name") in ["Over", "Under"]:
                        pt = o.get("point", None)
                        try:
                            odds_info["total"] = float(pt) if pt is not None else None
                        except Exception:
                            odds_info["total"] = None
                        break

        # If both are None, treat as NO_MARKET but still return with status to show always
        if odds_info["total"] is None and odds_info["spread_home"] is None and odds_info["spread_away"] is None:
            odds_info["status"] = "NO_MARKET"
            odds_info["reason"] = "MARKETS_PRESENT_BUT_NO_POINTS_PARSED"

        return odds_info


# =========================================================
# FAZ-22 Engine (Risk / Tempo / Confidence)
# =========================================================
class FAZ22Engine:
    def assess(self, analysis: Dict[str, Any], simulation: Optional[Dict[str, Any]], market: Dict[str, Any]) -> Dict[str, Any]:
        if not simulation:
            return {
                "risk": "DATA_UNRELIABLE",
                "tempo": None,
                "avg_total": None,
                "confidence": 0.10,
                "issues": ["KRITIK_VERI_YOK"],
            }

        iterations = int(simulation.get("iterations", 1))
        home_wins = int(simulation.get("home_wins", 0))
        away_wins = int(simulation.get("away_wins", 0))
        draws = int(simulation.get("draws", 0))

        p_home = home_wins / iterations if iterations else 0.0
        p_away = away_wins / iterations if iterations else 0.0
        p_draw = draws / iterations if iterations else 0.0
        max_prob = max(p_home, p_away, p_draw)

        # Confidence: clamp into [0.10, 0.95]
        confidence = min(0.95, max(0.10, max_prob))

        # Risk: invert-ish
        if max_prob >= 0.75:
            risk = "LOW"
        elif max_prob >= 0.58:
            risk = "MID"
        else:
            risk = "HIGH"

        totals = simulation.get("total_points") or []
        avg_total = (sum(totals) / len(totals)) if totals else None

        league = (analysis.get("league") or "").upper()
        if avg_total is None:
            tempo = None
        else:
            if league in ["NBA", "NFL", "MLB", "NHL"] or league not in [
                "EPL", "PREMIERLEAGUE", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "CHAMPIONSLEAGUE"
            ]:
                tempo = "HIGH" if avg_total >= 220 else "LOW" if avg_total <= 180 else "MODERATE"
            else:
                tempo = "HIGH" if avg_total >= 3 else "LOW" if avg_total <= 2 else "MODERATE"

        issues: List[str] = []
        # baseline warnings
        if analysis.get("baseline_fallback"):
            issues.append("KRITIK_VERI_YOK")
        # sample warnings (NBA)
        n_home = int(analysis.get("baseline_n_home", 0) or 0)
        n_away = int(analysis.get("baseline_n_away", 0) or 0)
        if league == "NBA" and (n_home < 5 or n_away < 5):
            issues.append("YETERSIZ_ORNEKLEM")

        # market warnings
        if (market.get("status") or "") != "OK":
            issues.append("MARKET_YOK")

        # If issues too many, down-weight confidence and raise risk label
        if len(issues) >= 2:
            confidence = max(0.10, confidence - 0.12)
            if risk == "LOW":
                risk = "MID"
            elif risk == "MID":
                risk = "HIGH"

        return {
            "risk": risk,
            "tempo": tempo,
            "avg_total": avg_total,
            "confidence": confidence,
            "issues": issues,
            "p_home": p_home,
            "p_away": p_away,
            "p_draw": p_draw,
        }


# =========================================================
# FAZ-23 Engine (Telegram Output)
# =========================================================
class FAZ23Engine:
    """
    Bu engine çıktıyı üretir. main.py sadece köprü.
    """

    def build_report_html(
        self,
        analysis: Dict[str, Any],
        simulation: Optional[Dict[str, Any]],
        market: Dict[str, Any],
        assess: Dict[str, Any],
    ) -> str:
        league = str(analysis.get("league", ""))
        date = str(analysis.get("date", ""))
        home = str(analysis.get("home", ""))
        away = str(analysis.get("away", ""))

        home_exp = analysis.get("home_exp_score")
        away_exp = analysis.get("away_exp_score")

        pred_total = None
        if home_exp is not None and away_exp is not None:
            pred_total = float(home_exp) + float(away_exp)

        # Band values (simple from simulation margins)
        band_str = ""
        if simulation:
            it = int(simulation.get("iterations", 1))
            mc = simulation.get("margin_counts") or {}
            # basketball style
            home_1 = mc.get("home_1", 0)
            home_big = mc.get("home_big", 0)
            away_1 = mc.get("away_1", 0)
            away_big = mc.get("away_big", 0)
            if it > 0:
                band_str = (
                    f"EV 1-5: {home_1*100/it:.1f}% | EV 6+: {home_big*100/it:.1f}% | "
                    f"DEP 1-5: {away_1*100/it:.1f}% | DEP 6+: {away_big*100/it:.1f}%"
                )

        risk = assess.get("risk")
        tempo = assess.get("tempo")
        avg_total = assess.get("avg_total")
        issues: List[str] = assess.get("issues") or []

        conf = float(assess.get("confidence", 0.10))
        conf_pct = int(round(conf * 100))

        # Market block ALWAYS
        m_status = market.get("status")
        m_reason = market.get("reason")
        m_total = market.get("total")
        m_sh = market.get("spread_home")
        m_sa = market.get("spread_away")
        m_bk = market.get("bookmaker")

        # Edge calc (Alt/Üst)
        edge_str = "EDGE: N/A"
        if m_total is not None and pred_total is not None:
            diff = float(pred_total) - float(m_total)
            if diff > 0.5:
                direction = "ÜST"
            elif diff < -0.5:
                direction = "ALT"
            else:
                direction = "NO_EDGE"
            edge_str = f"Alt/Üst: {direction} | Model-Çizgi Farkı: {diff:+.1f}"

        # Notes (minimal but useful)
        notes: List[str] = []
        if analysis.get("baseline_fallback"):
            notes.append("baseline_fallback=" + "; ".join(analysis.get("baseline_fallback") or []))
        n_home = int(analysis.get("baseline_n_home", 0) or 0)
        n_away = int(analysis.get("baseline_n_away", 0) or 0)
        if league.upper() == "NBA":
            notes.append(f"baseline_n(home/away)={n_home}/{n_away}")
        if pred_total is not None:
            notes.append(f"model_total={pred_total:.1f}")
        if avg_total is not None:
            notes.append(f"sim_avg_total={avg_total:.1f}")

        # Build HTML message
        lines: List[str] = []
        title = f"<b>FAZ-13 ÖN ANALİZ</b>\n<b>{html.escape(league)} | {html.escape(date)}</b>\n<b>{html.escape(home)} - {html.escape(away)}</b>"
        lines.append(title)

        if home_exp is not None and away_exp is not None:
            lines.append(f"<b>Model Skor:</b> {html.escape(home)} {home_exp:.1f} - {away_exp:.1f} {html.escape(away)}")
        if band_str:
            lines.append(f"<b>Band Values:</b> {html.escape(band_str)}")

        # Risk indicators
        lines.append("<b>RİSK GÖSTERGELERİ</b>")
        lines.append(f"• risk: {html.escape(str(risk))}")
        if tempo is not None:
            t = str(tempo)
            if avg_total is not None:
                if league.upper() in ["EPL", "PREMIERLEAGUE", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "CHAMPIONSLEAGUE"]:
                    t += f" (toplam~{avg_total:.1f} gol)"
                else:
                    t += f" (toplam~{avg_total:.1f} sayı)"
            lines.append(f"• tempo: {html.escape(t)}")
        lines.append(f"• confidence: <b>{conf_pct}%</b>")

        # Notes
        lines.append("<b>NOTLAR</b>")
        if notes:
            for n in notes[:10]:
                lines.append(f"• {html.escape(n)}")
        else:
            lines.append("• -")

        # Hata Avcısı
        lines.append("<b>HATA AVCISI</b>")
        if issues:
            lines.append("• " + html.escape(", ".join(issues)))
        else:
            lines.append("• YOK")

        # Market Integration ALWAYS
        lines.append("<b>MARKET ENTEGRASYONU</b>")
        lines.append(f"• status: {html.escape(str(m_status))}")
        lines.append(f"• reason: {html.escape(str(m_reason))}")
        lines.append(f"• bookmaker: {html.escape(str(m_bk))}")
        lines.append(f"• total: {html.escape(str(m_total))}")
        lines.append(f"• spread_home: {html.escape(str(m_sh))}")
        lines.append(f"• spread_away: {html.escape(str(m_sa))}")

        # Meta score
        lines.append("<b>META SKOR</b>")
        lines.append(f"• issues_count: {len(issues)}")
        lines.append(f"• outcome_probs: EV {assess.get('p_home',0):.2f} | DEP {assess.get('p_away',0):.2f} | BER {assess.get('p_draw',0):.2f}")

        # O/U
        lines.append("<b>ALT/ÜST</b>")
        lines.append(f"• {html.escape(edge_str)}")

        # Final disclaimer
        lines.append("\n<i>Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.</i>")

        return "\n".join(lines)


# =========================================================
# Telegram command handler
# =========================================================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (update.message.text or "").strip()
    try:
        _, params = message.split(" ", 1)
    except ValueError:
        await update.message.reply_text("Kullanım: /analyze <Lig> <YYYY-MM-DD> <Home Team> vs <Away Team>")
        return

    tokens = params.split()
    if len(tokens) < 4:
        await update.message.reply_text("Eksik parametre. Örn: /analyze NBA 2025-12-30 Dallas Mavericks vs Portland Trail Blazers")
        return

    league = tokens[0]
    date = tokens[1]
    team_tokens = tokens[2:]

    if any(tok.lower() in ["vs", "vs."] for tok in team_tokens):
        vs_index = next(i for i, tok in enumerate(team_tokens) if tok.lower().startswith("vs"))
        home_team = " ".join(team_tokens[:vs_index]).strip().strip(",")
        away_team = " ".join(team_tokens[vs_index + 1 :]).strip().strip(",")
    else:
        half = len(team_tokens) // 2
        home_team = " ".join(team_tokens[:half]).strip().strip(",")
        away_team = " ".join(team_tokens[half:]).strip().strip(",")

    logger.info(f"Analyzing: league={league} date={date} home={home_team} away={away_team}")

    faz13: FAZ13Engine = context.application.bot_data["faz13"]
    faz16: FAZ16Engine = context.application.bot_data["faz16"]
    faz17: FAZ17Engine = context.application.bot_data["faz17"]
    faz22: FAZ22Engine = context.application.bot_data["faz22"]
    faz23: FAZ23Engine = context.application.bot_data["faz23"]

    analysis = faz13.analyze(league, date, home_team, away_team)
    simulation = faz16.simulate(analysis)

    # Market: ALWAYS dict
    market_data = faz17.get_odds(league, home_team, away_team)

    assessment = faz22.assess(analysis, simulation, market_data)
    report_html = faz23.build_report_html(analysis, simulation, market_data, assessment)

    try:
        await update.message.reply_text(report_html, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Failed to send HTML message: {e}")
        # fallback plain
        await update.message.reply_text(html.unescape(report_html))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("Beklenmeyen hata oluştu. Biraz sonra tekrar dene.")


def main() -> None:
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

    application.add_handler(CommandHandler("analyze", analyze_command))
    application.add_error_handler(error_handler)

    logger.info("Bot starting... Listening for /analyze commands.")
    application.run_polling()


if __name__ == "__main__":
    main()
