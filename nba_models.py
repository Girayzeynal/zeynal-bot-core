"""
FAZ-4 – NBA Veri Modelleri

Simülasyon motoru ile konuşacak temiz veri modelleri.
Bu modeller:
- nba_fetcher ham datayı aldığında dolduracağı
- data_pipe ile sim_engine'e aktaracağımız
standart yapılar olacak.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal

from nba_config import NBA_LEAGUE_CODE, LeagueCode


GameStatus = Literal["scheduled", "live", "finished"]


@dataclass(slots=True)
class NBABoxScoreLite:
    game_id: str
    home_score: int
    away_score: int
    quarter: int
    time_remaining: str  # "06:32" gibi


@dataclass(slots=True)
class NBATeamStatsLite:
    team_code: str
    pts: int
    reb: int
    ast: int
    tov: int
    fg_pct: float
    fg3_pct: float
    ft_pct: float
    pace_est: Optional[float] = None


@dataclass(slots=True)
class NBAGameState:
    league: LeagueCode
    game_id: str
    season: str
    status: GameStatus
    tipoff_utc: datetime

    home_team: str
    away_team: str

    # Skor / temel istatistikler (opsiyonel – maç başlamamış olabilir)
    home_stats: Optional[NBATeamStatsLite] = None
    away_stats: Optional[NBATeamStatsLite] = None

    # Son alınan oran seti (opsiyonel)
    last_odds_source: Optional[str] = None
    spread_home: Optional[float] = None
    spread_away: Optional[float] = None
    total_points: Optional[float] = None

    def is_live(self) -> bool:
        return self.status == "live"

    def is_finished(self) -> bool:
        return self.status == "finished"

    def is_scheduled(self) -> bool:
        return self.status == "scheduled"
