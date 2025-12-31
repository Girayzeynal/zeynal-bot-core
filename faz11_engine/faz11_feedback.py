# faz11_engine.py
from __future__ import annotations

import sqlite3
import time
from typing import Dict, Any, Optional

from baseline.team_baseline_store import TeamBaselineStore, TeamBaseline


class Faz11Engine:
    """
    FAZ-11 – SELF LEARNING ENGINE (PROD)

    Görev:
    - Maç SONU gerçek skorları alır
    - FAZ-13 prematch tahmini ile kıyaslar
    - Takım bazlı baseline'ları günceller
    - Hata (error), tempo ve volatility öğrenir

    Bu engine OYNAMAZ, TAHMİN ETMEZ.
    Sadece öğrenir ve FAZ-13'ü güçlendirir.
    """

    def __init__(
        self,
        baseline_store: TeamBaselineStore,
        storage_path: str = "faz11_learning.sqlite",
    ) -> None:
        self.store = baseline_store
        self.path = storage_path
        self._init_db()

    # =========================
    # DB INIT
    # =========================
    def _init_db(self) -> None:
        con = sqlite3.connect(self.path)
        try:
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    league TEXT NOT NULL,
                    team TEXT NOT NULL,
                    pts_for REAL NOT NULL,
                    pts_against REAL NOT NULL,
                    pace REAL NOT NULL,
                    stdev_total REAL NOT NULL,
                    n_games_add INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_team ON learning_events(league, team)"
            )
            con.commit()
        finally:
            con.close()

    # =========================
    # PUBLIC API
    # =========================
    def ingest_match_result(
        self,
        league: str,
        home: str,
        away: str,
        final_home: int,
        final_away: int,
    ) -> bool:
        """
        MAÇ SONU çağrılır.

        Örnek:
        faz11.ingest_match_result(
            league="NBA",
            home="Cleveland Cavaliers",
            away="Phoenix Suns",
            final_home=112,
            final_away=109
        )
        """

        total = final_home + final_away
        pace = total / 180.0  # NBA için normalize tempo

        # HOME update
        ok1 = self._update_team(
            league=league,
            team=home,
            pts_for=final_home,
            pts_against=final_away,
            pace=pace,
        )

        # AWAY update
        ok2 = self._update_team(
            league=league,
            team=away,
            pts_for=final_away,
            pts_against=final_home,
            pace=pace,
        )

        return ok1 and ok2

    # =========================
    # CORE LEARNING
    # =========================
    def _update_team(
        self,
        league: str,
        team: str,
        pts_for: float,
        pts_against: float,
        pace: float,
        n_games_add: int = 1,
    ) -> bool:
        """
        Takım bazlı running-average update
        """

        # mevcut baseline
        try:
            cur: Optional[TeamBaseline] = self.store.get(league, team)
        except Exception:
            cur = None

        if cur and cur.n_games > 0:
            n0 = int(cur.n_games)
            n1 = int(n_games_add)
            n = n0 + n1

            pf = (cur.pts_for * n0 + pts_for * n1) / n
            pa = (cur.pts_against * n0 + pts_against * n1) / n
            pace_new = (cur.pace * n0 + pace * n1) / n

            # volatility update (simple EMA)
            err = abs((pts_for + pts_against) - (cur.pts_for + cur.pts_against))
            stdev = (cur.stdev_total * 0.85) + (err * 0.15)

        else:
            # ilk kez öğrenme
            pf = pts_for
            pa = pts_against
            pace_new = pace
            stdev = 9.0
            n = max(1, n_games_add)

        # clamp
        pace_new = max(0.70, min(1.35, pace_new))
        stdev = max(4.0, min(18.0, stdev))

        # yeni baseline
        new_bl = TeamBaseline(
            league=league,
            team=team,
            pts_for=pf,
            pts_against=pa,
            pace=pace_new,
            stdev_total=stdev,
            n_games=n,
        )

        # store'a yaz
        self._store_baseline(new_bl)

        # learning log
        self._record_event(
            league=league,
            team=team,
            pts_for=pts_for,
            pts_against=pts_against,
            pace=pace_new,
            stdev_total=stdev,
            n_games_add=n_games_add,
        )

        return True

    # =========================
    # STORE WRITE (SAFE)
    # =========================
    def _store_baseline(self, baseline: TeamBaseline) -> None:
        """
        TeamBaselineStore implementasyonuna göre best-effort save
        """
        for fn_name in ("set", "upsert", "save", "put"):
            fn = getattr(self.store, fn_name, None)
            if callable(fn):
                try:
                    fn(baseline)
                    return
                except TypeError:
                    try:
                        fn(baseline.league, baseline.team, baseline)
                        return
                    except Exception:
                        pass
                except Exception:
                    pass

        # fallback: dict
        try:
            self.store.set(
                {
                    "league": baseline.league,
                    "team": baseline.team,
                    "pts_for": baseline.pts_for,
                    "pts_against": baseline.pts_against,
                    "pace": baseline.pace,
                    "stdev_total": baseline.stdev_total,
                    "n_games": baseline.n_games,
                }
            )
        except Exception:
            pass

    # =========================
    # LEARNING LOG
    # =========================
    def _record_event(
        self,
        league: str,
        team: str,
        pts_for: float,
        pts_against: float,
        pace: float,
        stdev_total: float,
        n_games_add: int,
    ) -> None:
        con = sqlite3.connect(self.path)
        try:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO learning_events(
                    ts, league, team,
                    pts_for, pts_against,
                    pace, stdev_total, n_games_add
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    int(time.time()),
                    league,
                    team,
                    float(pts_for),
                    float(pts_against),
                    float(pace),
                    float(stdev_total),
                    int(n_games_add),
                ),
            )
            con.commit()
        finally:
            con.close()
