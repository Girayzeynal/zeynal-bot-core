from dataclasses import dataclass
from typing import Any, Dict, Optional
import os
import asyncio
import aiohttp
from aiohttp import ClientTimeout, ClientError


@dataclass
class MarketRequest:
    league: str
    date_str: str  # YYYY-MM-DD
    home: str
    away: str


class Faz17Engine:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        self.base_url = base_url or os.getenv("ODDS_BASE") or "https://api.the-odds-api.com/v4"

    async def fetch_market_total(self, market_request: MarketRequest) -> Dict[str, Any]:
        # ---- FAZ-13 CONTRACT (ASLA BOZULMAZ) ----
        result: Dict[str, Any] = {
            "total": None,
            "home_h2h": None,
            "away_h2h": None,
            "ft_score": None,
            "ht_score": None,
        }

        allowed_leagues = {"NBA", "NFL", "EPL", "MLB", "NHL"}
        league = market_request.league.upper()
        if league not in allowed_leagues:
            return result

        sportsdata_key = os.getenv("SPORTSDATA_API_KEY") or os.getenv("SPORTSDATAIO_API_KEY")
        apisports_key = os.getenv("APISPORTS_API_KEY") or os.getenv("API_SPORTS_KEY")
        balldontlie_key = os.getenv("BALLDONTLIE_API_KEY")

        home = market_request.home.lower()
        away = market_request.away.lower()
        date_str = market_request.date_str
        date_no_dash = date_str.replace("-", "")

        from datetime import datetime
        try:
            game_date = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            game_date = None

        def fill(k: str, v: Any):
            if result[k] is None and v is not None:
                result[k] = v

        timeout = ClientTimeout(total=8.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:

            # ========== 1) ESPN ==========
            try:
                league_map = {
                    "NBA": "basketball/nba",
                    "NFL": "football/nfl",
                    "MLB": "baseball/mlb",
                    "NHL": "hockey/nhl",
                    "EPL": "soccer/eng.1",
                }
                sport_path = league_map.get(league)
                if sport_path:
                    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={date_no_dash}"
                    async with session.get(url) as r:
                        data = await r.json() if r.status == 200 else None

                    if data:
                        for ev in data.get("events", []):
                            comp = ev.get("competitions", [{}])[0]
                            names = {
                                c.get("team", {}).get("displayName", "").lower()
                                for c in comp.get("competitors", [])
                            }
                            if home in names and away in names:
                                eid = comp.get("id")
                                if eid:
                                    s_url = f"https://site.api.espn.com/apis/v2/sports/{sport_path}/summary?event={eid}"
                                    async with session.get(s_url) as sr:
                                        sd = await sr.json() if sr.status == 200 else None
                                    if sd:
                                        for pc in sd.get("pickcenter", []):
                                            if pc.get("overUnder") is not None:
                                                fill("total", pc.get("overUnder"))
                                                fill("home_h2h", pc.get("homeTeamOdds", {}).get("moneyLine"))
                                                fill("away_h2h", pc.get("awayTeamOdds", {}).get("moneyLine"))
                                                break
                                break
            except Exception:
                pass

            # ========== 2) SPORTSDATAIO ==========
            try:
                if sportsdata_key:
                    sd_map = {
                        "NBA": "nba",
                        "NFL": "nfl",
                        "MLB": "mlb",
                        "NHL": "nhl",
                        "EPL": "soccer",
                    }
                    sk = sd_map.get(league)
                    if sk:
                        url = f"https://api.sportsdata.io/v3/{sk}/odds/json/GameOddsByDate/{date_str}"
                        headers = {"Ocp-Apim-Subscription-Key": sportsdata_key}
                        async with session.get(url, headers=headers) as r:
                            games = await r.json() if r.status == 200 else None
                        if games:
                            for g in games:
                                if home in str(g.get("HomeTeamName", "")).lower() and away in str(g.get("AwayTeamName", "")).lower():
                                    fill("total", g.get("OverUnder") or g.get("Total"))
                                    fill("home_h2h", g.get("HomeTeamMoneyLine"))
                                    fill("away_h2h", g.get("AwayTeamMoneyLine"))
                                    break
            except Exception:
                pass

            # ========== 3) THE ODDS API ==========
            try:
                if self.api_key:
                    odds_map = {
                        "NBA": "basketball_nba",
                        "NFL": "americanfootball_nfl",
                        "MLB": "baseball_mlb",
                        "NHL": "icehockey_nhl",
                        "EPL": "soccer_epl",
                    }
                    sk = odds_map.get(league)
                    if sk:
                        url = f"{self.base_url}/sports/{sk}/odds?apiKey={self.api_key}&regions=us&markets=h2h,totals"
                        async with session.get(url) as r:
                            data = await r.json() if r.status == 200 else None
                        if data:
                            for g in data:
                                if home in g.get("home_team", "").lower() and away in g.get("away_team", "").lower():
                                    for b in g.get("bookmakers", []):
                                        for m in b.get("markets", []):
                                            if m.get("key") == "totals":
                                                fill("total", m.get("outcomes", [{}])[0].get("point"))
                                            if m.get("key") == "h2h":
                                                for o in m.get("outcomes", []):
                                                    if home in o.get("name", "").lower():
                                                        fill("home_h2h", o.get("price"))
                                                    if away in o.get("name", "").lower():
                                                        fill("away_h2h", o.get("price"))
                                    break
            except Exception:
                pass

            # ========== 4) API SPORTS ==========
            try:
                if apisports_key:
                    headers = {"x-apisports-key": apisports_key}
                    url = "https://v1.basketball.api-sports.io/games"
                    async with session.get(url, params={"date": date_str}, headers=headers) as r:
                        data = await r.json() if r.status == 200 else None
                    if data:
                        for g in data.get("response", []):
                            teams = g.get("teams", {})
                            if home in teams.get("home", {}).get("name", "").lower() and away in teams.get("away", {}).get("name", "").lower():
                                scores = g.get("scores", {})
                                if scores:
                                    fill("ft_score", f"{scores.get('home')}-{scores.get('away')}")
                                break
            except Exception:
                pass

            # ========== 5) BALLDONTLIE ==========
            try:
                if balldontlie_key and league == "NBA":
                    url = f"https://www.balldontlie.io/api/v1/games?dates[]={date_str}"
                    async with session.get(url) as r:
                        data = await r.json() if r.status == 200 else None
                    if data:
                        for g in data.get("data", []):
                            if home in g.get("home_team", {}).get("full_name", "").lower():
                                fill("ft_score", f"{g.get('home_team_score')}-{g.get('visitor_team_score')}")
                                break
            except Exception:
                pass

        return result

    def enrich_with_market(self, market_request: MarketRequest) -> Dict[str, Any]:
        try:
            return asyncio.run(self.fetch_market_total(market_request))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(self.fetch_market_total(market_request))
            finally:
                asyncio.set_event_loop(None)
                loop.close()
