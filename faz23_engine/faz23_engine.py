from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from typing import Any, Dict

from faz13_engine import Faz13CoreOutput


class Faz23Engine:
    """
    Faz23Engine – Prediction snapshot storage and self-learning hooks.

    Bu sınıf, her analiz çıktısını bir SQLite veritabanında saklar.
    Kaydedilen snapshot, tam bağlam (ctx), takım ortalamaları (home_avg/away_avg),
    bandlar, market verisi ve meta bilgileri içerir.
    Böylece daha sonra yapılacak kalibrasyon ve model analizi için bu veriler kullanılabilir.
    """

    def __init__(self, storage_path: str = "faz23_storage.sqlite") -> None:
        self.path = storage_path
        self._init_db()

    def _init_db(self) -> None:
        """Ensure the SQLite table and index exist."""
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
            cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_fixture ON snapshots(fixture_key)")
            con.commit()
        finally:
            con.close()

    async def record_snapshot(self, out: Faz13CoreOutput) -> None:
        """
        Persist a prediction snapshot asynchronously.

        The fixture_key is derived from date, home, away and league to avoid collisions
        when fixture IDs are not used. Only the last 12 notes are stored.
        """
        fixture_key = f"{out.ctx.date}:{out.ctx.home}:{out.ctx.away}:{out.ctx.league}"

        payload: Dict[str, Any] = {
            "ctx": asdict(out.ctx),
            "home_avg": asdict(out.home_avg) if out.home_avg else None,
            "away_avg": asdict(out.away_avg) if out.away_avg else None,
            "total_band": out.total_band,
            "home_band": out.home_band,
            "away_band": out.away_band,
            "ou_direction": out.ou_direction,
            "quarters": out.quarters if out.quarters is not None else [],
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
                (int(time.time()), fixture_key, json.dumps(payload, ensure_ascii=False)),
            )
            con.commit()
        finally:
            con.close()
