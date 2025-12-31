import os
import logging
import html
import math
import random
import asyncio
import requests
from typing import Any, Dict, Optional, List, Tuple

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
# Helpers: League normalization (NO league baseline!)
# =========================================================
def norm_key(s: str) -> str:
    return "".join((s or "").strip().upper().split()).replace("-", "").replace("_", "")


LEAGUE_ALIASES = {
    # Basketball
    "NBA": "NBA",
    "EUROLEAGUE": "EUROLEAGUE",
    "EL": "EUROLEAGUE",
    "EUROCUP": "EUROCUP",
    "EC": "EUROCUP",
    "TBL": "BSL",
    "BSL": "BSL",
    "TURKIYE": "BSL",
    "TURKEY": "BSL",
    "ACB": "ACB",
    "SPAIN": "ACB",
    "LNB": "LNB",
    "FRANCE": "LNB",
    "BBL": "BBL",
    "GERMANY": "BBL",
    "LBA": "LBA",
    "ITALY": "LBA",
    "LKL": "LKL",
    "LITHUANIA": "LKL",
    "ABA": "ABA",
    "ADR": "ABA",
    "VTB": "VTB",
    "CBA": "CBA",
    # Soccer (API-Sports football)
    "EPL": "EPL",
    "PREMIERLEAGUE": "EPL",
    "LALIGA": "LaLiga",
    "SERIEA": "SerieA",
    "BUNDESLIGA": "Bundesliga",
    "LIGUE1": "Ligue1",
    "CHAMPIONSLEAGUE": "ChampionsLeague",
    # Others (keep as-is)
}


def normalize_league(league: str) -> str:
    k = norm_key(league)
    return LEAGUE_ALIASES.get(k, (league or "").strip())


# =========================================================
# FAZ-13 Engine (TEAM baseline ONLY)
# =========================================================
class FAZ13Engine:
    """
    TEAM-baseline only.
    - NBA: balldontlie team games avg
    - Soccer: api-sports football statistics avg
    - Other basketball leagues: api-sports basketball (league search + last N games)
    If team baseline missing => exp_score None (NO-PLAY downstream)
    """

    def __init__(self, balldontlie_api_key: str, api_sports_key: str):
        self.balldontlie_api_key = balldontlie_api_key
        self.api_sports_key = api_sports_key

        # Cache
        self.nba_team_cache: Dict[str, int] = {}
        self.basket_league_cache: Dict[str, int] = {}  # normalized league -> league_id
        self.basket_team_cache: Dict[Tuple[int, str], int] = {}  # (league_id, team_name_norm) -> team_id

        # Soccer league id map (API-Sports Football)
        self.football_league_id_map = {
            "EPL": 39,
            "LaLiga": 140,
            "SerieA": 135,
            "Bundesliga": 78,
            "Ligue1": 61,
            "ChampionsLeague": 2,
        }

        self.bdl_headers = {"Authorization": self.balldontlie_api_key}
        self.api_sports_headers = {"x-apisports-key": self.api_sports_key}

    # ---------- NBA ----------
    def _get_nba_team_id(self, team_name: str) -> Optional[int]:
        key = (team_name or "").strip().lower()
        if not key:
            return None
        if self.nba_team_cache:
            return self.nba_team_cache.get(key)

        url = "https://api.balldontlie.io/v1/teams"
        try:
            resp = requests.get(url, headers=self.bdl_headers, timeout=15)
            resp.raise_for_status()
            data = resp.json().get("data", [])
        except Exception as e:
            logger.error(f"NBA teams fetch failed: {e}")
            return None

        for t in data:
            fn = (t.get("full_name") or "").strip().lower()
            tid = t.get("id")
            if fn and tid:
                self.nba_team_cache[fn] = tid
        return self.nba_team_cache.get(key)

    def _get_nba_team_stats(self, team_id: int, season_year: int) -> Optional[Dict[str, Any]]:
        url = f"https://api.balldontlie.io/v1/games?team_ids[]={team_id}&seasons[]={season_year}&per_page=100"
        try:
            resp = requests.get(url, headers=self.bdl_headers, timeout=15)
            resp.raise_for_status()
            games = resp.json().get("data", [])
        except Exception as e:
            logger.error(f"NBA games fetch failed team_id={team_id}: {e}")
            return None

        if not games:
            return None

        pf = pa = n = 0
        for g in games:
            home_id = g["home_team"]["id"]
            away_id = g["visitor_team"]["id"]
            hs = g["home_team_score"]
            as_ = g["visitor_team_score"]

            if team_id == home_id:
                pf += hs
                pa += as_
                n += 1
            elif team_id == away_id:
                pf += as_
                pa += hs
                n += 1

        if n < 5:
            return None

        return {"points_for": pf / n, "points_against": pa / n, "sample_n": n}

    # ---------- Football (soccer) ----------
    def _get_soccer_team_id(self, team_name: str) -> Optional[int]:
        try:
            r = requests.get(
                f"https://v3.football.api-sports.io/teams?search={team_name}",
                headers=self.api_sports_headers,
                timeout=15,
            )
            r.raise_for_status()
            teams = r.json().get("response", [])
        except Exception:
            return None

        if not teams:
            return None
        return teams[0].get("team", {}).get("id")

    def _get_soccer_team_stats(self, league_id: int, season: int, team_id: int) -> Optional[Dict[str, Any]]:
        try:
            r = requests.get(
                f"https://v3.football.api-sports.io/teams/statistics?league={league_id}&season={season}&team={team_id}",
                headers=self.api_sports_headers,
                timeout=15,
            )
            r.raise_for_status()
            stats = r.json().get("response", {})
        except Exception:
            return None

        if not stats:
            return None

        goals = stats.get("goals", {})
        avg_for = goals.get("for", {}).get("average", {}).get("total")
        avg_against = goals.get("against", {}).get("average", {}).get("total")

        try:
            gf = float(avg_for) if avg_for not in [None, ""] else None
            ga = float(avg_against) if avg_against not in [None, ""] else None
        except Exception:
            gf = ga = None

        if gf is None or ga is None:
            return None

        return {"goals_for": gf, "goals_against": ga}

    # ---------- Basketball (Europe/others) via API-Sports Basketball ----------
    def _resolve_basket_league_id(self, league_norm: str) -> Optional[int]:
        """
        NO league baseline. Only used to fetch TEAM baseline.
        Resolve league_id by searching API-Sports Basketball leagues endpoint and cache it.
        """
        league_norm_u = (league_norm or "").strip().upper()
        if not league_norm_u:
            return None
        if league_norm_u in self.basket_league_cache:
            return self.basket_league_cache[league_norm_u]

        try:
            r = requests.get(
                "https://v1.basketball.api-sports.io/leagues",
                headers=self.api_sports_headers,
                timeout=15,
            )
            r.raise_for_status()
            resp = r.json().get("response", []) or []
        except Exception:
            return None

        # best-effort match by name
        picked = None
        for item in resp:
            nm = (item.get("name") or "").strip().upper()
            if nm == league_norm_u:
                picked = item
                break
        if not picked and resp:
            # fallback: first match by "contains"
            for item in resp:
                nm = (item.get("name") or "").strip().upper()
                if league_norm_u in nm or nm in league_norm_u:
                    picked = item
                    break

        if not picked:
            return None

        lid = picked.get("id")
        if isinstance(lid, int):
            self.basket_league_cache[league_norm_u] = lid
            return lid
        return None

    def _resolve_basket_team_id(self, league_id: int, team_name: str) -> Optional[int]:
        key = (league_id, norm_key(team_name))
        if key in self.basket_team_cache:
            return self.basket_team_cache[key]

        try:
            r = requests.get(
                f"https://v1.basketball.api-sports.io/teams?search={team_name}",
                headers=self.api_sports_headers,
                timeout=15,
            )
            r.raise_for_status()
            resp = r.json().get("response", []) or []
        except Exception:
            return None

        if not resp:
            return None

        # prefer exact normalized match
        team_id = None
        tn = norm_key(team_name)
        for t in resp:
            nm = norm_key(t.get("name", ""))
            if nm == tn:
                team_id = t.get("id")
                break
        if team_id is None:
            team_id = resp[0].get("id")

        if isinstance(team_id, int):
            self.basket_team_cache[key] = team_id
            return team_id
        return None

    def _get_basket_team_stats_last_n(
        self, league_norm: str, season: int, team_name: str, last_n: int = 10
    ) -> Optional[Dict[str, Any]]:
        league_id = self._resolve_basket_league_id(league_norm)
        if league_id is None:
            return None
        team_id = self._resolve_basket_team_id(league_id, team_name)
        if team_id is None:
            return None

        try:
            r = requests.get(
                f"https://v1.basketball.api-sports.io/games?league={league_id}&season={season}&team={team_id}&last={last_n}",
                headers=self.api_sports_headers,
                timeout=15,
            )
            r.raise_for_status()
            games = r.json().get("response", []) or []
        except Exception:
            return None

        if not games:
            return None

        pf = pa = n = 0
        home_pf = home_pa = home_n = 0
        away_pf = away_pa = away_n = 0

        for g in games:
            try:
                hid = g["teams"]["home"]["id"]
                aid = g["teams"]["away"]["id"]
                hs = g["scores"]["home"]["total"]
                as_ = g["scores"]["away"]["total"]
            except Exception:
                continue

            if hs is None or as_ is None:
                continue

            if team_id == hid:
                pf += hs
                pa += as_
                n += 1
                home_pf += hs
                home_pa += as_
                home_n += 1
            elif team_id == aid:
                pf += as_
                pa += hs
                n += 1
                away_pf += as_
                away_pa += hs
                away_n += 1

        if n < 5:
            return None

        return {
            "points_for": pf / n,
            "points_against": pa / n,
            "sample_n": n,
            "home_points_for": (home_pf / home_n) if home_n >= 3 else None,
            "away_points_for": (away_pf / away_n) if away_n >= 3 else None,
        }

    # ---------- analyze ----------
    def analyze(self, league: str, date: str, home_team: str, away_team: str) -> Dict[str, Any]:
        league_norm = normalize_league(league)
        try:
            year = int(str(date)[:4])
        except Exception:
            year = None

        result: Dict[str, Any] = {
            "league": league_norm,
            "date": date,
            "home": home_team,
            "away": away_team,
            "home_exp_score": None,
            "away_exp_score": None,
            "baseline_fallback": [],
            "baseline_n_home": 0,
            "baseline_n_away": 0,
        }

        # Football path
        if league_norm in self.football_league_id_map:
            league_id = self.football_league_id_map[league_norm]
            season = year if year else 2025
            hid = self._get_soccer_team_id(home_team)
            aid = self._get_soccer_team_id(away_team)
            hs = self._get_soccer_team_stats(league_id, season, hid) if hid else None
            as_ = self._get_soccer_team_stats(league_id, season, aid) if aid else None

            if hs and as_:
                home_exp = (hs["goals_for"] + as_["goals_against"]) / 2.0
                away_exp = (as_["goals_for"] + hs["goals_against"]) / 2.0
                result["home_exp_score"] = home_exp
                result["away_exp_score"] = away_exp
            else:
                result["baseline_fallback"].append("TEAM_BASELINE_MISSING")
                result["home_exp_score"] = None
                result["away_exp_score"] = None
            return result

        # NBA path
        if league_norm.upper() == "NBA":
            season_year = year if year else 2025
            hid = self._get_nba_team_id(home_team)
            aid = self._get_nba_team_id(away_team)
            hs = self._get_nba_team_stats(hid, season_year) if hid else None
            as_ = self._get_nba_team_stats(aid, season_year) if aid else None

            if hs and as_:
                result["home_exp_score"] = (hs["points_for"] + as_["points_against"]) / 2.0
                result["away_exp_score"] = (as_["points_for"] + hs["points_against"]) / 2.0
                result["baseline_n_home"] = int(hs["sample_n"])
                result["baseline_n_away"] = int(as_["sample_n"])
            else:
                result["baseline_fallback"].append("TEAM_BASELINE_MISSING")
                result["home_exp_score"] = None
                result["away_exp_score"] = None
            return result

        # Other basketball leagues
        season_year = year if year else 2025
        home_stats = self._get_basket_team_stats_last_n(league_norm, season_year, home_team, last_n=10)
        away_stats = self._get_basket_team_stats_last_n(league_norm, season_year, away_team, last_n=10)

        if home_stats and away_stats:
            home_pf = home_stats.get("home_points_for") or home_stats["points_for"]
            away_pf = away_stats.get("away_points_for") or away_stats["points_for"]
            result["home_exp_score"] = float(home_pf)
            result["away_exp_score"] = float(away_pf)
            result["baseline_n_home"] = int(home_stats["sample_n"])
            result["baseline_n_away"] = int(away_stats["sample_n"])
        else:
            result["baseline_fallback"].append("TEAM_BASELINE_MISSING")
            result["home_exp_score"] = None
            result["away_exp_score"] = None

        return result


# =========================================================
# FAZ-16 Engine (Simulation)
# =========================================================
class FAZ16Engine:
    def simulate(self, analysis: Dict[str, Any], iterations: int = 2000) -> Optional[Dict[str, Any]]:
        home_exp = analysis.get("home_exp_score")
        away_exp = analysis.get("away_exp_score")
        league = str(analysis.get("league", "")).upper()

        # NO-PLAY guard
        if home_exp is None or away_exp is None:
            return None

        is_soccer = league in ["EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "CHAMPIONSLEAGUE"]

        results: Dict[str, Any] = {
            "home_wins": 0,
            "away_wins": 0,
            "draws": 0,
            "margin_counts": {"home_1": 0, "home_big": 0, "away_1": 0, "away_big": 0},
            "total_points": [],
            "iterations": iterations,
        }

        if is_soccer:
            # Poisson
            lambda_home = max(0.01, float(home_exp))
            lambda_away = max(0.01, float(away_exp))
            for _ in range(iterations):
                hg = self._poisson(lambda_home)
                ag = self._poisson(lambda_away)
                if hg > ag:
                    results["home_wins"] += 1
                    if hg - ag == 1:
                        results["margin_counts"]["home_1"] += 1
                    else:
                        results["margin_counts"]["home_big"] += 1
                elif ag > hg:
                    results["away_wins"] += 1
                    if ag - hg == 1:
                        results["margin_counts"]["away_1"] += 1
                    else:
                        results["margin_counts"]["away_big"] += 1
                else:
                    results["draws"] += 1
                results["total_points"].append(hg + ag)
            return results

        # Basketball-ish normal
        std_home = max(1.0, 0.15 * float(home_exp))
        std_away = max(1.0, 0.15 * float(away_exp))
        for _ in range(iterations):
            hp = max(0.0, random.gauss(float(home_exp), std_home))
            ap = max(0.0, random.gauss(float(away_exp), std_away))
            hp_i = int(round(hp))
            ap_i = int(round(ap))

            # tie-break
            if hp_i == ap_i:
                if random.random() < 0.5:
                    hp_i += 1
                else:
                    ap_i += 1

            # garbage-time mild clean on heavy blowouts
            margin_abs = abs(hp_i - ap_i)
            if margin_abs >= 18:
                shrink = int(0.06 * (hp_i + ap_i))
                if hp_i > ap_i:
                    hp_i -= shrink
                else:
                    ap_i -= shrink

            if hp_i > ap_i:
                results["home_wins"] += 1
                margin = hp_i - ap_i
                if margin <= 5:
                    results["margin_counts"]["home_1"] += 1
                else:
                    results["margin_counts"]["home_big"] += 1
            else:
                results["away_wins"] += 1
                margin = ap_i - hp_i
                if margin <= 5:
                    results["margin_counts"]["away_1"] += 1
                else:
                    results["margin_counts"]["away_big"] += 1

            results["total_points"].append(hp_i + ap_i)

        return results

    def _poisson(self, lam: float) -> int:
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
            "LaLiga": "soccer_spain_la_liga",
            "SerieA": "soccer_italy_serie_a",
            "Bundesliga": "soccer_germany_bundesliga",
            "Ligue1": "soccer_france_ligue_one",
            "ChampionsLeague": "soccer_uefa_champs_league",
        }

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").lower().replace(".", "").replace(",", "").split())

    def get_odds(self, league: str, home_team: str, away_team: str) -> Dict[str, Any]:
        league_norm = normalize_league(league)
        sport_key = self.sport_key_map.get(league_norm)
        if not sport_key:
            return {
                "status": "UNSUPPORTED_LEAGUE",
                "reason": f"No sport_key for league={league_norm}",
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

        book = None
        for bk in bookmakers:
            if bk.get("key") == "draftkings":
                book = bk
                break
        if not book:
            book = bookmakers[0]

        out: Dict[str, Any] = {
            "status": "OK",
            "reason": "-",
            "total": None,
            "spread_home": None,
            "spread_away": None,
            "bookmaker": book.get("key"),
        }

        for m in (book.get("markets") or []):
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
                        out["spread_home"] = ptf
                    elif away_n in nm:
                        out["spread_away"] = ptf

            elif key == "totals":
                for o in outs:
                    if o.get("name") in ["Over", "Under"]:
                        pt = o.get("point", None)
                        try:
                            out["total"] = float(pt) if pt is not None else None
                        except Exception:
                            out["total"] = None
                        break

        if out["total"] is None and out["spread_home"] is None and out["spread_away"] is None:
            out["status"] = "NO_MARKET"
            out["reason"] = "MARKETS_PRESENT_BUT_NO_POINTS_PARSED"

        return out


# =========================================================
# FAZ-22 Engine (Risk/Tempo/Confidence + NO-PLAY)
# =========================================================
class FAZ22Engine:
    def assess(self, analysis: Dict[str, Any], simulation: Optional[Dict[str, Any]], market: Dict[str, Any]) -> Dict[str, Any]:
        # NO-PLAY if missing TEAM baseline
        if analysis.get("home_exp_score") is None or analysis.get("away_exp_score") is None:
            return {
                "risk": "NO_PLAY",
                "tempo": None,
                "avg_total": None,
                "confidence": 0.10,
                "issues": ["TEAM_BASELINE_MISSING", "NO_PLAY"],
                "p_home": 0.0,
                "p_away": 0.0,
                "p_draw": 0.0,
            }

        if not simulation:
            return {
                "risk": "DATA_UNRELIABLE",
                "tempo": None,
                "avg_total": None,
                "confidence": 0.10,
                "issues": ["KRITIK_VERI_YOK"],
                "p_home": 0.0,
                "p_away": 0.0,
                "p_draw": 0.0,
            }

        it = int(simulation.get("iterations", 1))
        hw = int(simulation.get("home_wins", 0))
        aw = int(simulation.get("away_wins", 0))
        dr = int(simulation.get("draws", 0))

        p_home = hw / it if it else 0.0
        p_away = aw / it if it else 0.0
        p_draw = dr / it if it else 0.0

        max_prob = max(p_home, p_away, p_draw)
        confidence = min(0.95, max(0.10, max_prob))

        if max_prob >= 0.75:
            risk = "LOW"
        elif max_prob >= 0.58:
            risk = "MID"
        else:
            risk = "HIGH"

        totals = simulation.get("total_points") or []
        avg_total = (sum(totals) / len(totals)) if totals else None

        # Generic tempo buckets (NO league baseline used; this is just classification)
        league = str(analysis.get("league", "")).upper()
        if avg_total is None:
            tempo = None
        else:
            if league in ["EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "CHAMPIONSLEAGUE"]:
                tempo = "HIGH" if avg_total >= 3 else "LOW" if avg_total <= 2 else "MODERATE"
            else:
                tempo = "HIGH" if avg_total >= 220 else "LOW" if avg_total <= 180 else "MODERATE"

        issues: List[str] = []
        if analysis.get("baseline_fallback"):
            issues.extend(analysis["baseline_fallback"])

        # market warnings
        if (market.get("status") or "") != "OK":
            issues.append("MARKET_YOK")

        # sample warnings
        n_home = int(analysis.get("baseline_n_home", 0) or 0)
        n_away = int(analysis.get("baseline_n_away", 0) or 0)
        if league == "NBA" and (n_home < 5 or n_away < 5):
            issues.append("YETERSIZ_ORNEKLEM")

        # degrade if many issues
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
# FAZ-23 Engine (Telegram output)
# =========================================================
class FAZ23Engine:
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

        # Band values
        band_str = ""
        if simulation:
            it = int(simulation.get("iterations", 1))
            mc = simulation.get("margin_counts") or {}
            if it > 0:
                band_str = (
                    f"EV 1-5: {mc.get('home_1',0)*100/it:.1f}% | EV 6+: {mc.get('home_big',0)*100/it:.1f}% | "
                    f"DEP 1-5: {mc.get('away_1',0)*100/it:.1f}% | DEP 6+: {mc.get('away_big',0)*100/it:.1f}%"
                )

        risk = assess.get("risk")
        tempo = assess.get("tempo")
        avg_total = assess.get("avg_total")
        issues: List[str] = assess.get("issues") or []
        conf_pct = int(round(float(assess.get("confidence", 0.10)) * 100))

        # Market always shown
        m_status = market.get("status")
        m_reason = market.get("reason")
        m_total = market.get("total")
        m_sh = market.get("spread_home")
        m_sa = market.get("spread_away")
        m_bk = market.get("bookmaker")

        # edge line
        edge_line = "-"
        if pred_total is not None and m_total is not None:
            diff = pred_total - float(m_total)
            if diff >= 3:
                edge_line = f"ÜST eğilimi (+{diff:.1f})"
            elif diff <= -3:
                edge_line = f"ALT eğilimi ({diff:.1f})"
            else:
                edge_line = f"EDGE YOK ({diff:.1f})"

        esc = html.escape
        lines: List[str] = []
        lines.append("<b>FAZ-13 → FAZ-23</b>")
        lines.append(f"<b>{esc(home)} - {esc(away)}</b>")
        lines.append(f"• Lig: {esc(league)} | Tarih: {esc(date)}")
        lines.append("")
        lines.append("<b>BAZ SKOR</b>")
        lines.append(f"• Ev exp: {esc(str(home_exp))} | Dep exp: {esc(str(away_exp))}")
        lines.append(f"• Toplam exp: {esc(str(pred_total))}")
        lines.append("")
        lines.append("<b>SIMÜLASYON</b>")
        lines.append(f"• band: {esc(band_str)}")
        lines.append(f"• avg_total: {esc(str(avg_total))}")
        lines.append("")
        lines.append("<b>FAZ-22 RİSK</b>")
        lines.append(f"• risk: {esc(str(risk))} | tempo: {esc(str(tempo))} | güven: %{esc(str(conf_pct))}")
        lines.append("<b>HATA AVCISI</b>")
        if issues:
            lines.append("• " + esc(", ".join(map(str, issues[:12]))))
        else:
            lines.append("• YOK")
        lines.append("")
        lines.append("<b>MARKET ENTEGRASYONU</b>")
        lines.append(f"• status: {esc(str(m_status))}")
        lines.append(f"• reason: {esc(str(m_reason))}")
        lines.append(f"• bookmaker: {esc(str(m_bk))}")
        lines.append(f"• total: {esc(str(m_total))}")
        lines.append(f"• spread_home: {esc(str(m_sh))}")
        lines.append(f"• spread_away: {esc(str(m_sa))}")
        lines.append("")
        lines.append("<b>ALT/ÜST</b>")
        lines.append(f"• {esc(edge_line)}")
        lines.append("")
        lines.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(lines)


# =========================================================
# Telegram handlers
# =========================================================
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (update.message.text or "").strip()
    try:
        _, params = message.split(" ", 1)
    except ValueError:
        await update.message.reply_text("Kullanım: /analyze LIG YYYY-MM-DD HOME vs AWAY")
        return

    tokens = params.split()
    if len(tokens) < 4:
        await update.message.reply_text("Eksik parametre. Örn: /analyze NBA 2025-12-31 Los Angeles Lakers vs Detroit Pistons")
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

    logger.info(f"Analyze: league={league} date={date} home={home_team} away={away_team}")

    faz13: FAZ13Engine = context.application.bot_data["faz13"]
    faz16: FAZ16Engine = context.application.bot_data["faz16"]
    faz17: FAZ17Engine = context.application.bot_data["faz17"]
    faz22: FAZ22Engine = context.application.bot_data["faz22"]
    faz23: FAZ23Engine = context.application.bot_data["faz23"]

    # =========================================================
    # FIX: Bloklayıcı fazlar event-loop üstünde çalışmasın
    # =========================================================
    analysis = await asyncio.to_thread(faz13.analyze, league, date, home_team, away_team)
    simulation = await asyncio.to_thread(faz16.simulate, analysis)
    market = await asyncio.to_thread(faz17.get_odds, analysis.get("league", league), home_team, away_team)

    assess = faz22.assess(analysis, simulation, market)
    report = faz23.build_report_html(analysis, simulation, market, assess)

    try:
        await update.message.reply_text(report, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        await update.message.reply_text(html.unescape(report))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("Beklenmeyen hata oluştu. Tekrar dene.")


def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.bot_data["faz13"] = FAZ13Engine(BALLDONTLIE_API_KEY, API_SPORTS_KEY)
    application.bot_data["faz16"] = FAZ16Engine()
    application.bot_data["faz17"] = FAZ17Engine(ODDS_API_KEY)
    application.bot_data["faz22"] = FAZ22Engine()
    application.bot_data["faz23"] = FAZ23Engine()

    application.add_handler(CommandHandler("analyze", analyze_command))
    application.add_error_handler(error_handler)

    logger.info("Bot starting... /analyze is ready.")
    application.run_polling()


if __name__ == "__main__":
    main()
