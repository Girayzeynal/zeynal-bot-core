from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from statistics import mean, pstdev


# =====================================================
# DATA MODELS
# =====================================================

@dataclass
class H2HGame:
    ts_utc: int
    home: str
    away: str
    pts_home: float
    pts_away: float
    pace: float


@dataclass
class H2HSummary:
    league: str
    home: str
    away: str
    n_games: int
    avg_total: float
    avg_home: float
    avg_away: float
    stdev_total: float
    updated_ts: int


# =====================================================
# STORE
# =====================================================

class H2HStore:
    """
    Head-to-Head (H2H) Store

    Rules:
    - Canonical keys (ABBR) ile çalışır
    - SADECE veri toplar
    - Karar / yön / edge üretmez
    - FAZ-13 için yardımcı istatistik sağlar
    """

    def __init__(self, base_dir: str = "data/h2h") -> None:
        self.base_dir = base_dir
        self.series_dir = os.path.join(self.base_dir, "series")
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.series_dir, exist_ok=True)

    # -------------------------
    # PATH HELPERS
    # -------------------------

    def _key(self, league: str, home: str, away: str) -> str:
        a = home.strip().upper()
        b = away.strip().upper()
        # yön bağımsız olsun diye alfabetik
        if a > b:
            a, b = b, a
        return f"{league.upper()}__{a}__{b}"

    def _series_path(self, league: str, home: str, away: str) -> str:
        return os.path.join(self.series_dir, f"H2H__{self._key(league, home, away)}.json")

    # -------------------------
    # WRITE
    # -------------------------

    def append_game(
        self,
        league: str,
        home: str,
        away: str,
        pts_home: float,
        pts_away: float,
        pace: float,
        ts_utc: Optional[int] = None,
        max_games: int = 20,
    ) -> None:
        ts = int(ts_utc or time.time())
        rec = H2HGame(
            ts_utc=ts,
            home=home,
            away=away,
            pts_home=float(pts_home),
            pts_away=float(pts_away),
            pace=float(pace),
        )

        path = self._series_path(league, home, away)
        series: List[Dict[str, Any]] = []

        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    series = json.load(f)
            except Exception:
                series = []

        series.append(asdict(rec))
        series = sorted(series, key=lambda x: x["ts_utc"])[-max_games:]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(series, f, ensure_ascii=False, indent=2)

    # -------------------------
    # READ
    # -------------------------

    def get_series(
        self, league: str, home: str, away: str, n_games: int
    ) -> List[H2HGame]:
        path = self._series_path(league, home, away)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return [H2HGame(**r) for r in raw][-n_games:]
        except Exception:
            return []

    # -------------------------
    # ANALYTIC SUMMARY
    # -------------------------

    def compute_summary(
        self, league: str, home: str, away: str, n_games: int
    ) -> Optional[H2HSummary]:
        series = self.get_series(league, home, away, n_games)

        # güvenlik: H2H < 3 ise YOK SAY
        if len(series) < 3:
            return None

        totals = [g.pts_home + g.pts_away for g in series]
        homes = [g.pts_home for g in series]
        aways = [g.pts_away for g in series]

        return H2HSummary(
            league=league,
            home=home,
            away=away,
            n_games=len(series),
            avg_total=mean(totals),
            avg_home=mean(homes),
            avg_away=mean(aways),
            stdev_total=pstdev(totals) if len(totals) >= 2 else 0.0,
            updated_ts=int(time.time()),
        )
