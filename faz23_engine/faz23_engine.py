"""
faz23_engine – Snapshot persistence and simple self‑learn hooks.

This engine persists every prediction into a SQLite database for
post‑hoc analysis and potential calibration.  Each snapshot records
the context, team averages, predicted bands, market data and meta
scores at the time of prediction.  Storing these results enables
future comparison with actual outcomes, facilitating model tuning and
league‑specific bias adjustments.

The storage schema is intentionally simple: a single table with an
auto‑incrementing ID, a Unix timestamp, the fixture identifier (or
hash of teams/date when no fixture ID is used), and a JSON payload.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from typing import Any, Dict

from faz13_engine import Faz13CoreOutput


class Faz23Engine:
    """Persist predictions for later evaluation and self‑learning."""

    def __init__(self, storage_path: str = "faz23_storage.sqlite") -> None:
        self.path = storage_path
        self._init_db()

    def _init_db(self) -> None:
        con = sqlite3.connect(self.path)
        try:
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    fixture_key TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_fixture ON snapshots(fixture_key)"
            )
            con.commit()
        finally:
            con.close()

    async def record_snapshot(self, out: Faz13CoreOutput) -> None:
        """Asynchronously persist a prediction snapshot into SQLite."""
        # Create a fixture key: use fixture_id if provided, else hash of date/home/away
        try:
            fk = f"{out.ctx.date}:{out.ctx.home}:{out.ctx.away}:{out.ctx.league}"
        except Exception:
            fk = str(int(time.time()))
        payload: Dict[str, Any] = {
            "ctx": {
                "league": out.ctx.league,
                "date": out.ctx.date,
                "home": out.ctx.home,
                "away": out.ctx.away,
            },
            "home_avg": asdict(out.home_avg),
            "away_avg": asdict(out.away_avg),
            "total_band": out.total_band,
            "home_band": out.home_band,
            "away_band": out.away_band,
            "ou_direction": out.ou_direction,
            "quarters": out.quarters,
            "blowout_risk": out.blowout_risk,
            "tempo_flag": out.tempo_flag,
            "notes": out.notes[-12:],
            "market": out.market,
            "meta": out.meta,
        }
        con = sqlite3.connect(self.path)
        try:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO snapshots(ts, fixture_key, payload) VALUES(?,?,?)",
                (int(time.time()), fk, json.dumps(payload, ensure_ascii=False)),
            )
            con.commit()
        finally:
            con.close()
