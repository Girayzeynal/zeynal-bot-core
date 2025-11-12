# data_pipe.py
# FAZ 3 – Data Link (mock + normalize)
from datetime import datetime, timezone

class Game:
    def __init__(self, league, home, away, tipoff_utc, odds=None, totals=None):
        self.league = league
        self.home = home
        self.away = away
        self.tipoff_utc = tipoff_utc  # ISO string
        self.odds = odds or {}
        self.totals = totals or {}

    def as_dict(self):
        return {
            "league": self.league,
            "home": self.home,
            "away": self.away,
            "tipoff_utc": self.tipoff_utc,
            "odds": self.odds,
            "totals": self.totals,
        }

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_upcoming_mock():
    # İlk sürüm: sabit örnek veri (EuroLeague + NBA)
    return [
        Game(
            league="EuroLeague",
            home="Anadolu Efes",
            away="Real Madrid",
            tipoff_utc=now_iso(),
            odds={"home_ml": 2.10, "away_ml": 1.75},
            totals={"ou": 163.5},
        ),
        Game(
            league="NBA",
            home="Celtics",
            away="Bucks",
            tipoff_utc=now_iso(),
            odds={"home_ml": 1.90, "away_ml": 1.95},
            totals={"ou": 228.5},
        ),
    ]
