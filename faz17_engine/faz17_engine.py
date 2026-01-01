from dataclasses import dataclass
from typing import Any, Dict, Optional
import os
import asyncio
import aiohttp
from aiohttp import ClientTimeout, ClientError

@dataclass
class MarketRequest:
    league: str        # Lig ismi (örn: "NBA", "NFL", "EPL", "MLB", "NHL")
    date_str: str      # Maç tarihi, 'YYYY-MM-DD' formatında
    home: str          # Ev sahibi takım ismi
    away: str          # Deplasman takım ismi

class Faz17Engine:
    """
    ESPN, SportsDataIO, The Odds API, API Sports ve Balldontlie servislerinden
    market toplam skor verilerini (over/under) asenkron olarak toplayan motor.
    Öncelikle ESPN, ardından SportsDataIO, The Odds API, API Sports ve son olarak 
    Balldontlie kaynakları sırayla denenerek toplam skor (oyun için belirlenen 
    over/under değeri veya skor toplamı) verisi alınır.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        Faz17Engine yapıcısı. opsiyonel parametreler:
        - api_key: The Odds API için kullanılacak anahtar. Verilmezse ortam değişkeni ODDS_API_KEY kullanılır.
        - base_url: The Odds API temel URL'si. Verilmezse ortam değişkeni ODDS_BASE ya da varsayılan URL kullanılır.
        Diğer API anahtarları (SportsDataIO, API-Sports, Balldontlie) fetch_market_total içinde ortamdan okunur.
        """
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        self.base_url = base_url or os.getenv("ODDS_BASE") or "https://api.the-odds-api.com/v4"

    async def fetch_market_total(self, market_request: MarketRequest) -> Optional[float]:
        """
        Belirtilen maç için kaynaklardan sırayla toplam skor bilgisini getirir.
        Kaynak sırası: ESPN -> SportsDataIO -> The Odds API -> API Sports -> Balldontlie.
        Bulunursa toplam skor (over/under) float olarak döner, hiçbir kaynakta
        bulunamazsa None döner.
        """
        # İzin verilen elit ligler
        allowed_leagues = {"NBA", "NFL", "EPL", "MLB", "NHL"}
        league = market_request.league.upper()
        if league not in allowed_leagues:
            return None  # Desteklenmeyen lig
        
        # Ortam değişkenlerinden diğer API anahtarlarını çek
        sportsdata_key = os.getenv("SPORTSDATA_API_KEY") or os.getenv("SPORTSDATAIO_API_KEY")
        apisports_key = os.getenv("APISPORTS_API_KEY") or os.getenv("API_SPORTS_KEY")
        balldontlie_key = os.getenv("BALLDONTLIE_API_KEY")

        # Takım isimlerini küçük harfe çevir
        home = market_request.home.lower()
        away = market_request.away.lower()
        date_str = market_request.date_str
        date_no_dash = date_str.replace("-", "")

        # Tarih objesine dönüştür (gerekirse)
        from datetime import datetime
        try:
            game_date = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            game_date = None

        # Tek tek kaynakları sırayla dene:
        timeout = ClientTimeout(total=8.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # --- 1. ESPN ---
            try:
                # Lig key'lerini ESPN path'ine dönüştür
                league_map = {
                    "NBA": "basketball/nba",
                    "NFL": "football/nfl",
                    "MLB": "baseball/mlb",
                    "NHL": "hockey/nhl",
                    "EPL": "soccer/eng.1"
                }
                sport_path = league_map.get(league)
                if sport_path:
                    scoreboard_url = (
                        f"https://site.api.espn.com/apis/site/v2/sports/"
                        f"{sport_path}/scoreboard?dates={date_no_dash}"
                    )
                    async with session.get(scoreboard_url) as resp:
                        data = await resp.json() if resp.status == 200 else None
                    if data and "events" in data:
                        for ev in data["events"]:
                            comps = ev.get("competitions", [])
                            if comps:
                                comp = comps[0]
                                competitors = comp.get("competitors", [])
                                # Belirtilen takımların maçını bul
                                names = {c.get("team", {}).get("displayName", "").lower()
                                         for c in competitors}
                                if home in names and away in names:
                                    event_id = comp.get("id")
                                    if event_id:
                                        summary_url = (
                                            f"https://site.api.espn.com/apis/v2/sports/"
                                            f"{sport_path}/summary?event={event_id}"
                                        )
                                        async with session.get(summary_url) as resp2:
                                            sum_data = await resp2.json() if resp2.status == 200 else None
                                        if sum_data:
                                            # ESPN pickcenter'da consensus (id=1004) varsa, yoksa ilk overUnder
                                            pickcenter = sum_data.get("pickcenter", [])
                                            over_under = None
                                            # id=1004 consensus
                                            for pc in pickcenter:
                                                provider = pc.get("provider", {})
                                                if str(provider.get("id")) == "1004" and pc.get("overUnder") is not None:
                                                    over_under = pc["overUnder"]
                                                    break
                                            if over_under is None:
                                                for pc in pickcenter:
                                                    if pc.get("overUnder") is not None:
                                                        over_under = pc["overUnder"]
                                                        break
                                            if over_under is not None:
                                                try:
                                                    return float(over_under)
                                                except:
                                                    return over_under
                                    break  # maç bulunduğunda ESPN'den diğer maçları aramaya gerek yok
            except (asyncio.TimeoutError, ClientError, Exception):
                pass

            # --- 2. SportsDataIO ---
            try:
                if sportsdata_key:
                    # SportsDataIO endpoint liglere göre
                    sd_map = {
                        "NBA": "nba",
                        "NFL": "nfl",
                        "MLB": "mlb",
                        "NHL": "nhl",
                        "EPL": "soccer"
                    }
                    sport_key = sd_map.get(league)
                    if sport_key:
                        sd_url = f"https://api.sportsdata.io/v3/{sport_key}/odds/json/GameOddsByDate/{date_str}"
                        headers = {"Ocp-Apim-Subscription-Key": sportsdata_key}
                        async with session.get(sd_url, headers=headers) as resp:
                            sd_data = await resp.json() if resp.status == 200 else None
                        if sd_data:
                            for game in sd_data:
                                home_team = str(game.get("HomeTeam", "")).lower()
                                away_team = str(game.get("AwayTeam", "")).lower()
                                home_full = str(game.get("HomeTeamName", home_team)).lower()
                                away_full = str(game.get("AwayTeamName", away_team)).lower()
                                if home in home_full and away in away_full:
                                    # sportsdata ilgili odds alanlarında OverUnder veya Total
                                    ou = None
                                    if isinstance(game.get("PregameOdds"), list) and game["PregameOdds"]:
                                        for odds in game["PregameOdds"]:
                                            ou = odds.get("OverUnder") or odds.get("Total")
                                            if ou:
                                                break
                                    ou = ou or game.get("OverUnder") or game.get("Total")
                                    if ou:
                                        try:
                                            return float(ou)
                                        except:
                                            return ou
                                    break
            except (asyncio.TimeoutError, ClientError, Exception):
                pass

            # --- 3. The Odds API ---
            try:
                if self.api_key:
                    odds_map = {
                        "NBA": "basketball_nba",
                        "NFL": "americanfootball_nfl",
                        "MLB": "baseball_mlb",
                        "NHL": "icehockey_nhl",
                        "EPL": "soccer_epl"
                    }
                    sport_key = odds_map.get(league)
                    if sport_key:
                        odds_url = (
                            f"{self.base_url}/sports/{sport_key}/odds"
                            f"?apiKey={self.api_key}&regions=us,uk&markets=totals&oddsFormat=american"
                        )
                        async with session.get(odds_url) as resp:
                            odds_data = await resp.json() if resp.status == 200 else None
                        if odds_data:
                            for g in odds_data:
                                home_team = str(g.get("home_team", "")).lower()
                                away_team = str(g.get("away_team", "")).lower()
                                if home in home_team and away in away_team:
                                    bookmakers = g.get("bookmakers", [])
                                    for book in bookmakers:
                                        markets = book.get("markets", [])
                                        for market in markets:
                                            if market.get("key") == "totals":
                                                outcomes = market.get("outcomes", [])
                                                # 'Over' outcome point veya ilk outcome
                                                for outc in outcomes:
                                                    if outc.get("name") == "Over" and outc.get("point") is not None:
                                                        try:
                                                            return float(outc["point"])
                                                        except:
                                                            return outc["point"]
                                                if outcomes and outcomes[0].get("point") is not None:
                                                    try:
                                                        return float(outcomes[0]["point"])
                                                    except:
                                                        return outcomes[0]["point"]
                                    break
            except (asyncio.TimeoutError, ClientError, Exception):
                pass

            # --- 4. API Sports ---
            try:
                if apisports_key:
                    # Her lig için URL ve parametre hazırlığı
                    base_url = None
                    params = {}
                    headers = {"x-apisports-key": apisports_key}
                    year = None
                    try:
                        year = int(date_str.split("-")[0])
                    except:
                        pass
                    if league == "NBA":
                        base_url = "https://v1.basketball.api-sports.io/games"
                        params["date"] = date_str
                        params["league"] = "12"
                        # Sezon parametresi: NBA sezonu Ekim'de başlar, Haziran'da biter
                        if year:
                            month = int(date_str.split("-")[1])
                            params["season"] = f"{year-1}-{year}" if month <= 6 else f"{year}-{year+1}"
                    elif league == "NFL":
                        base_url = "https://v1.american-football.api-sports.io/games"
                        params.update({"date": date_str, "league": "1"})
                        if year:
                            month = int(date_str.split("-")[1])
                            # NFL sezonu genelde Eylül'de başlar, Şubat'ta biter
                            params["season"] = str(year-1) if month <= 2 else str(year)
                    elif league == "MLB":
                        base_url = "https://v1.baseball.api-sports.io/games"
                        params.update({"date": date_str, "league": "1"})
                        params["season"] = str(year) if year else ""
                    elif league == "NHL":
                        base_url = "https://v1.hockey.api-sports.io/games"
                        params.update({"date": date_str, "league": "57"})
                        if year:
                            month = int(date_str.split("-")[1])
                            params["season"] = f"{year-1}-{year}" if month <= 6 else f"{year}-{year+1}"
                    elif league == "EPL":
                        base_url = "https://v3.football.api-sports.io/fixtures"
                        params.update({"date": date_str, "league": "39"})
                        params["season"] = str(year-1) if year and int(date_str.split("-")[1]) <= 7 else str(year)
                    if base_url:
                        async with session.get(base_url, params=params, headers=headers) as resp:
                            api_data = await resp.json() if resp.status == 200 else None
                        if api_data:
                            games = api_data.get("response") or api_data.get("games")
                            if games and isinstance(games, list):
                                for game in games:
                                    # Takım eşleşmesi (API Sports'un formatına göre)
                                    if "teams" in game:
                                        home_name = str(game["teams"]["home"]["name"]).lower()
                                        away_name = str(game["teams"]["away"]["name"]).lower()
                                    else:
                                        home_name = str(game.get("home_team") or game.get("home", "")).lower()
                                        away_name = str(game.get("away_team") or game.get("away", "")).lower()
                                    if home in home_name and away in away_name:
                                        total = None
                                        # Skor toplamı
                                        if "scores" in game:
                                            h_score = game["scores"].get("home")
                                            a_score = game["scores"].get("away")
                                            if h_score is not None and a_score is not None:
                                                total = h_score + a_score
                                        elif "runs" in game:
                                            h_score = game["runs"].get("home")
                                            a_score = game["runs"].get("away")
                                            if h_score is not None and a_score is not None:
                                                total = h_score + a_score
                                        elif "goals" in game:
                                            h_score = game["goals"].get("home")
                                            a_score = game["goals"].get("away")
                                            if h_score is not None and a_score is not None:
                                                total = h_score + a_score
                                        if total is not None:
                                            try:
                                                return float(total)
                                            except:
                                                return total
                                        # Odds (total/over-under)
                                        if "odds" in game:
                                            odds_info = game["odds"]
                                            ou_val = odds_info.get("total") or odds_info.get("over_under") or odds_info.get("overUnder")
                                            if ou_val:
                                                try:
                                                    return float(ou_val)
                                                except:
                                                    return ou_val
                                        break
            except (asyncio.TimeoutError, ClientError, Exception):
                pass

            # --- 5. Balldontlie (NBA için son fallback) ---
            try:
                if balldontlie_key and league == "NBA":
                    bdl_url = f"https://www.balldontlie.io/api/v1/games?dates[]={date_str}"
                    async with session.get(bdl_url) as resp:
                        bdl_data = await resp.json() if resp.status == 200 else None
                    if bdl_data and "data" in bdl_data:
                        for game in bdl_data["data"]:
                            home_team = game.get("home_team", {})
                            away_team = game.get("visitor_team", {})
                            if home in home_team.get("full_name", "").lower() and away in away_team.get("full_name", "").lower():
                                home_score = game.get("home_team_score")
                                away_score = game.get("visitor_team_score")
                                if home_score is not None and away_score is not None:
                                    total = home_score + away_score
                                    try:
                                        return float(total)
                                    except:
                                        return total
                                break
            except (asyncio.TimeoutError, ClientError, Exception):
                pass

            # Hiçbir kaynakta bulunamadı
            return None

    def enrich_with_market(self, market_request: MarketRequest) -> Optional[float]:
        """
        Async olmayan arayanlar için sarmalayıcı:
        fetch_market_total metodunu senkron şekilde çağırır ve sonucu döndürür.
        """
        try:
            return asyncio.run(self.fetch_market_total(market_request))
        except RuntimeError:
            # Var olan event loop varsa, onun üzerinde çalıştırmak için new event loop
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(self.fetch_market_total(market_request))
            finally:
                asyncio.set_event_loop(None)
                loop.close()
