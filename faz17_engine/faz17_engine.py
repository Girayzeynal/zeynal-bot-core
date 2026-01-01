from dataclasses import dataclass
import os
import asyncio
import aiohttp
from aiohttp import ClientTimeout, ClientError

@dataclass
class MarketRequest:
    league: str    # Lig ismi (örn: "NBA", "NFL", "EPL", "MLB", "NHL")
    date_str: str  # Maç tarihi, 'YYYY-MM-DD' formatında
    home: str      # Ev sahibi takım ismi
    away: str      # Deplasman takım ismi

class Faz17Engine:
    """
    ESPN, SportsDataIO, The Odds API, API Sports ve Balldontlie servislerinden
    market toplam skor verilerini (over/under) asenkron olarak toplayan motor.
    Öncelikle ESPN, ardından SportsDataIO, The Odds API, API Sports ve son olarak 
    Balldontlie kaynakları sırasıyla denenerek toplam skor (oyun için belirlenen 
    over/under değeri veya skor toplamı) verisi alınır.
    Sadece NBA, NFL, EPL, MLB, NHL gibi elit liglerde çalışır.
    API anahtarları environment değişkenlerinden (`os.getenv`) okunur.
    Hata durumları yakalanır ve istekler için belirli bir zaman aşımı (`aiohttp` 
    ClientTimeout) uygulanır.
    """
    def __init__(self):
        # API anahtarlarını ortam değişkenlerinden al
        self.sportsdata_key = os.getenv("SPORTSDATA_API_KEY") or os.getenv("SPORTSDATAIO_API_KEY")
        self.odds_api_key = os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
        self.apisports_key = os.getenv("APISPORTS_API_KEY") or os.getenv("API_SPORTS_KEY") or os.getenv("RAPIDAPI_KEY")
        # Not: ESPN ve Balldontlie için anahtar gerekmiyor
    
    async def fetch_market_total(self, market_request: MarketRequest):
        """
        Belirtilen maç için kaynaklardan sırayla toplam skor bilgisini getirir.
        Kaynak sırası: ESPN -> SportsDataIO -> The Odds API -> API Sports -> Balldontlie.
        Bulunursa toplam skor (over/under) float olarak döner, hiç bir kaynakta bulunamazsa None döner.
        """
        # Elit lig filtresi: Sadece belirlenen liglerde çalış
        allowed_leagues = {"NBA", "NFL", "EPL", "MLB", "NHL"}
        league = market_request.league.upper()
        if league not in allowed_leagues:
            # Desteklenmeyen lig
            return None
        
        # Kaynaklara yapılacak istekler için timeout ve oturum ayarları
        timeout = ClientTimeout(total=8.0)  # Her kaynak için toplam 8 saniye timeout
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 1. ESPN kaynağından çekme
            try:
                # ESPN sport path belirle
                if league == "NBA":
                    sport_path = "basketball/nba"
                elif league == "NFL":
                    sport_path = "football/nfl"
                elif league == "MLB":
                    sport_path = "baseball/mlb"
                elif league == "NHL":
                    sport_path = "hockey/nhl"
                elif league == "EPL":
                    sport_path = "soccer/eng.1"
                else:
                    sport_path = None
                
                if sport_path:
                    date_param = market_request.date_str.replace("-", "")
                    scoreboard_url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates={date_param}"
                    async with session.get(scoreboard_url) as resp:
                        data = await resp.json() if resp.status == 200 else None
                    if data and "events" in data:
                        events = data["events"]
                        # Takım eşleştirmesi (case-insensitive)
                        target_home = market_request.home.lower()
                        target_away = market_request.away.lower()
                        event_id = None
                        for event in events:
                            competitions = event.get("competitions", [])
                            if not competitions:
                                continue
                            comp = competitions[0]
                            competitors = comp.get("competitors", [])
                            home_name = away_name = ""
                            home_abbr = away_abbr = ""
                            home_display = away_display = ""
                            for comp_team in competitors:
                                team_info = comp_team.get("team", {})
                                loc = team_info.get("location", "").lower()
                                name = team_info.get("name", "").lower()
                                display = team_info.get("displayName", "").lower()
                                abbrev = team_info.get("abbreviation", "").lower()
                                if comp_team.get("homeAway") == "home":
                                    home_name = f"{loc} {name}".strip()
                                    home_abbr = abbrev
                                    home_display = display
                                else:
                                    away_name = f"{loc} {name}".strip()
                                    away_abbr = abbrev
                                    away_display = display
                            if ((target_home in home_display or target_home == home_abbr or target_home in home_name)
                                    and (target_away in away_display or target_away == away_abbr or target_away in away_name)):
                                event_id = comp.get("id")
                                break
                        if event_id:
                            summary_url = (f"https://site.web.api.espn.com/apis/site/v2/sports/{sport_path}/summary"
                                           f"?region=us&lang=en&contentorigin=espn&event={event_id}")
                            async with session.get(summary_url) as resp:
                                summary_data = await resp.json() if resp.status == 200 else None
                            if summary_data and "pickcenter" in summary_data:
                                pc = summary_data["pickcenter"]
                                if isinstance(pc, list):
                                    over_under_val = None
                                    # Önce consensus (id=1004) arıyoruz
                                    for entry in pc:
                                        prov = entry.get("provider", {})
                                        if str(prov.get("id")) == "1004" and "overUnder" in entry:
                                            over_under_val = entry["overUnder"]
                                            break
                                    # Eğer consensus bulunamadıysa, varsa ilk overUnder içeren girdi alınır
                                    if over_under_val is None:
                                        for entry in pc:
                                            if "overUnder" in entry:
                                                over_under_val = entry["overUnder"]
                                                break
                                    if over_under_val is not None:
                                        try:
                                            return float(over_under_val)
                                        except:
                                            return over_under_val
            except (asyncio.TimeoutError, ClientError, Exception):
                pass
            
            # 2. SportsDataIO kaynağından çekme
            try:
                if self.sportsdata_key:
                    sport_key = None
                    if league == "NBA":
                        sport_key = "nba"
                    elif league == "NFL":
                        sport_key = "nfl"
                    elif league == "MLB":
                        sport_key = "mlb"
                    elif league == "NHL":
                        sport_key = "nhl"
                    elif league == "EPL":
                        sport_key = "soccer"
                    if sport_key:
                        date = market_request.date_str
                        sportsdata_url = f"https://api.sportsdata.io/v3/{sport_key}/odds/json/GameOddsByDate/{date}"
                        headers = {"Ocp-Apim-Subscription-Key": self.sportsdata_key}
                        async with session.get(sportsdata_url, headers=headers) as resp:
                            sd_data = await resp.json() if resp.status == 200 else None
                        if sd_data:
                            target_home = market_request.home.lower()
                            target_away = market_request.away.lower()
                            for game in sd_data:
                                home_team = str(game.get("HomeTeam", "")).lower()
                                away_team = str(game.get("AwayTeam", "")).lower()
                                home_full = str(game.get("HomeTeamName", "")).lower() if game.get("HomeTeamName") else home_team
                                away_full = str(game.get("AwayTeamName", "")).lower() if game.get("AwayTeamName") else away_team
                                if ((target_home in home_full or target_home == home_team)
                                        and (target_away in away_full or target_away == away_team)):
                                    odds_list = game.get("PregameOdds") or game.get("Odds")
                                    if odds_list and isinstance(odds_list, list):
                                        for odds in odds_list:
                                            ou_val = odds.get("OverUnder") or odds.get("Total")
                                            if ou_val:
                                                try:
                                                    return float(ou_val)
                                                except:
                                                    return ou_val
                                    ou_val = game.get("OverUnder") or game.get("Total")
                                    if ou_val:
                                        try:
                                            return float(ou_val)
                                        except:
                                            return ou_val
            except (asyncio.TimeoutError, ClientError, Exception):
                pass
            
            # 3. The Odds API kaynağından çekme
            try:
                if self.odds_api_key:
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
                    if sport_key:
                        odds_url = (f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
                                    f"?apiKey={self.odds_api_key}&regions=us,uk&markets=totals&oddsFormat=american")
                        async with session.get(odds_url) as resp:
                            odds_data = await resp.json() if resp.status == 200 else None
                        if odds_data:
                            target_home = market_request.home.lower()
                            target_away = market_request.away.lower()
                            for game in odds_data:
                                home = str(game.get("home_team", "")).lower()
                                away = str(game.get("away_team", "")).lower()
                                if target_home in home and target_away in away:
                                    bookmakers = game.get("bookmakers")
                                    if bookmakers and isinstance(bookmakers, list):
                                        for book in bookmakers:
                                            markets = book.get("markets")
                                            if markets and isinstance(markets, list):
                                                for market in markets:
                                                    if market.get("key") == "totals":
                                                        outcomes = market.get("outcomes")
                                                        if outcomes and isinstance(outcomes, list):
                                                            for outcome in outcomes:
                                                                if outcome.get("name") == "Over" and outcome.get("point") is not None:
                                                                    try:
                                                                        return float(outcome["point"])
                                                                    except:
                                                                        return outcome["point"]
                                                            if outcomes[0].get("point") is not None:
                                                                try:
                                                                    return float(outcomes[0]["point"])
                                                                except:
                                                                    return outcomes[0]["point"]
            except (asyncio.TimeoutError, ClientError, Exception):
                pass
            
            # 4. API Sports kaynağından çekme
            try:
                if self.apisports_key:
                    base_url = None
                    params = {}
                    headers = {"x-apisports-key": self.apisports_key}
                    date = market_request.date_str
                    if league == "NBA":
                        base_url = "https://v1.basketball.api-sports.io/games"
                        params = {"date": date, "league": "12", "season": ""}
                        try:
                            year = int(date.split("-")[0])
                        except:
                            year = None
                        season_str = ""
                        if year:
                            month = int(date.split("-")[1])
                            if month <= 6:
                                season_str = f"{year-1}-{year}"
                            else:
                                season_str = f"{year}-{year+1}"
                        params["season"] = season_str if season_str else ""
                    elif league == "NFL":
                        base_url = "https://v1.american-football.api-sports.io/games"
                        params = {"date": date, "league": "1", "season": ""}
                        try:
                            year = int(date.split("-")[0])
                        except:
                            year = None
                        season_str = str(year) if year else ""
                        if year:
                            month = int(date.split("-")[1])
                            if month <= 2:
                                season_str = str(year-1)
                        params["season"] = season_str
                    elif league == "MLB":
                        base_url = "https://v1.baseball.api-sports.io/games"
                        params = {"date": date, "league": "1", "season": ""}
                        try:
                            year = int(date.split("-")[0])
                        except:
                            year = None
                        season_str = str(year) if year else ""
                        params["season"] = season_str
                    elif league == "NHL":
                        base_url = "https://v1.hockey.api-sports.io/games"
                        params = {"date": date, "league": "57", "season": ""}
                        try:
                            year = int(date.split("-")[0])
                        except:
                            year = None
                        season_str = ""
                        if year:
                            month = int(date.split("-")[1])
                            if month <= 6:
                                season_str = f"{year-1}-{year}"
                            else:
                                season_str = f"{year}-{year+1}"
                        params["season"] = season_str if season_str else ""
                    elif league == "EPL":
                        base_url = "https://v3.football.api-sports.io/fixtures"
                        params = {"date": date, "league": "39", "season": ""}
                        try:
                            year = int(date.split("-")[0])
                        except:
                            year = None
                        season_str = str(year-1) if year and int(date.split("-")[1]) <= 7 else str(year)
                        params["season"] = season_str if season_str else ""
                    if base_url:
                        async with session.get(base_url, params=params, headers=headers) as resp:
                            api_data = await resp.json() if resp.status == 200 else None
                        if api_data:
                            games = api_data.get("response") or api_data.get("games") or api_data.get("response")
                            if games and isinstance(games, list):
                                target_home = market_request.home.lower()
                                target_away = market_request.away.lower()
                                for game in games:
                                    home_name = away_name = ""
                                    if "teams" in game:
                                        home_name = str(game["teams"].get("home", {}).get("name", "")).lower()
                                        away_name = str(game["teams"].get("away", {}).get("name", "")).lower()
                                    else:
                                        home_name = str(game.get("home_team", "") or game.get("home", "")).lower()
                                        away_name = str(game.get("away_team", "") or game.get("away", "")).lower()
                                    if target_home in home_name and target_away in away_name:
                                        total = None
                                        if "scores" in game:
                                            home_score = game["scores"].get("home")
                                            away_score = game["scores"].get("away")
                                            if home_score is not None and away_score is not None:
                                                total = home_score + away_score
                                        elif "runs" in game:
                                            home_score = game["runs"].get("home")
                                            away_score = game["runs"].get("away")
                                            if home_score is not None and away_score is not None:
                                                total = home_score + away_score
                                        elif "goals" in game:
                                            home_score = game["goals"].get("home")
                                            away_score = game["goals"].get("away")
                                            if home_score is not None and away_score is not None:
                                                total = home_score + away_score
                                        if total is not None:
                                            try:
                                                return float(total)
                                            except:
                                                return total
                                        if "odds" in game:
                                            odds_info = game["odds"]
                                            ou_val = None
                                            if isinstance(odds_info, dict):
                                                ou_val = odds_info.get("total") or odds_info.get("over_under") or odds_info.get("overUnder")
                                            if ou_val:
                                                try:
                                                    return float(ou_val)
                                                except:
                                                    return ou_val
            except (asyncio.TimeoutError, ClientError, Exception):
                pass
            
            # 5. Balldontlie kaynağından çekme (sadece NBA için)
            try:
                if league == "NBA":
                    date = market_request.date_str
                    bdl_url = f"https://www.balldontlie.io/api/v1/games?dates[]={date}"
                    async with session.get(bdl_url) as resp:
                        bdl_data = await resp.json() if resp.status == 200 else None
                    if bdl_data and "data" in bdl_data:
                        games = bdl_data["data"]
                        target_home = market_request.home.lower()
                        target_away = market_request.away.lower()
                        for game in games:
                            home_team = game.get("home_team", {})
                            away_team = game.get("visitor_team", {})
                            home_name = str(home_team.get("full_name", "")).lower()
                            away_name = str(away_team.get("full_name", "")).lower()
                            if target_home in home_name and target_away in away_name:
                                home_score = game.get("home_team_score")
                                away_score = game.get("visitor_team_score")
                                if home_score is not None and away_score is not None:
                                    total = home_score + away_score
                                    try:
                                        return float(total)
                                    except:
                                        return total
            except (asyncio.TimeoutError, ClientError, Exception):
                pass
            
            # Hiçbir kaynak verisi bulunamadı
            return None
    
    def enrich_with_market(self, market_request: MarketRequest):
        """
        Market verisiyle zenginleştirme yapar: fetch_market_total fonksiyonunu çağırıp sonucunu döndürür.
        (Async çağrıyı senkron olarak sarmalar)
        """
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
