from __future__ import annotations
from pathlib import Path

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from faz13_engine import Faz13CoreOutput


class Faz23Engine:
    """
    FAZ-23 v3 – REAL STRONG SIDE DECISION ENGINE

    - FAZ-13: sayısal projeksiyonları okur
    - FAZ-17: market çizgileri ile karşılaştırır
    - FAZ-22: risk / confidence / uncertainty filtresi uygular
    - SADECE güçlü sinyal varsa konuşur
    - 1Y / 2Y / MS ayrı ayrı değerlendirir
    - Bahis dili YOKTUR (analiz/simülasyon)
    """

    def __init__(self, storage_path: str = "faz23_storage.sqlite") -> None:
        self.path = storage_path
        Path(self.path).parent.mkdir(
            parents=True, exist_ok=True
        )
        self._init_db()

        # sayısal eşikler
        self.MIN_CONFIDENCE = 60.0
        self.MIN_EDGE = 5.0  # net fark
        self.MAX_RISK = "MEDIUM"

    # -------------------------------------------------
    # DB
    # -------------------------------------------------
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
            con.commit()
        finally:
            con.close()

    async def record_snapshot(self, out: Faz13CoreOutput) -> None:
        quality = getattr(out, "meta", None)
        if not isinstance(quality, dict) or not isinstance(quality.get("data_quality"), str) or not quality["data_quality"].strip():
            raise ValueError("Cannot record analysis without data-quality provenance")
        fixture_key = f"{out.ctx.date}:{out.ctx.home}:{out.ctx.away}:{out.ctx.league}"
        payload = {
            "ctx": out.ctx.__dict__,
            "meta": out.meta,
            "market": out.market,
            "notes": out.notes,
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

    def latest_snapshots_by_fixture(self) -> List[Dict[str, Any]]:
        """Return one latest inserted snapshot per fixture for calibration inputs.

        This is a read-only selection; all historical snapshots remain stored.
        Ordering by insertion id resolves equal-second timestamps deterministically.
        It does not match snapshots with actual results or validate prediction timing.
        """
        con = sqlite3.connect(self.path)
        try:
            rows = con.execute(
                """
                SELECT id, ts, fixture_key, payload
                FROM snapshots
                WHERE id IN (
                    SELECT MAX(id) FROM snapshots GROUP BY fixture_key
                )
                ORDER BY id
                """
            ).fetchall()
        finally:
            con.close()
        return [
            {"id": row[0], "ts": row[1], "fixture_key": row[2],
             "payload": json.loads(row[3])}
            for row in rows
        ]

    def prematch_snapshots_for_calibration(
        self, fixture_start_utc: Dict[str, int]
    ) -> List[Dict[str, Any]]:
        """One latest strictly pre-tipoff snapshot per fixture, fail closed.

        Caller must supply verified UTC Unix tipoff seconds keyed by fixture_key.
        Unknown fixtures and snapshots at/after tipoff are excluded. This method
        does not validate actual scores or calculate calibration metrics.
        """
        if not isinstance(fixture_start_utc, dict):
            raise TypeError("Verified fixture start times must be a dictionary")
        for key, start in fixture_start_utc.items():
            if not isinstance(key, str) or not key or type(start) is not int or start <= 0:
                raise ValueError("Invalid fixture key or UTC start timestamp")
        if not fixture_start_utc:
            return []
        con = sqlite3.connect(self.path)
        try:
            rows = con.execute(
                "SELECT id, ts, fixture_key, payload FROM snapshots ORDER BY id"
            ).fetchall()
        finally:
            con.close()
        selected: Dict[str, Dict[str, Any]] = {}
        for snapshot_id, ts, fixture_key, payload in rows:
            start = fixture_start_utc.get(fixture_key)
            if start is None or ts >= start:
                continue
            selected[fixture_key] = {
                "id": snapshot_id, "ts": ts, "fixture_key": fixture_key,
                "payload": json.loads(payload),
            }
        return sorted(selected.values(), key=lambda item: item["id"])

    # -------------------------------------------------
    # CORE DECISION
    # -------------------------------------------------
    def apply_decision(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        meta = core.meta
        notes: List[str] = []

        confidence = float(meta.get("confidence_pct", 0.0))
        risk = meta.get("risk")
        uncertainty = meta.get("uncertainty_level", "YÜKSEK")

        # Global filtre
        if (
            confidence < self.MIN_CONFIDENCE
            or risk == "HIGH"
            or uncertainty == "YÜKSEK"
        ):
            notes.append("📉 Güçlü bir istatistiksel sinyal oluşmadı.")
            notes.append("Bu karşılaşma analiz kapsamında izleme listesindedir.")
            core.notes = notes
            meta["analysis_status"] = "NO_STRONG_SIGNAL"
            meta["strong_signals"] = []
            return core

        strong_signals: List[str] = []

        # -------------------------
        # 1. İLK YARI
        # -------------------------
        strong_1h = self._check_side(
            expected=meta.get("expected_1h"),
            market=meta.get("market_1h"),
            label="İLK YARI",
            notes=notes,
        )
        if strong_1h:
            strong_signals.append(strong_1h)

        # -------------------------
        # 2. İKİNCİ YARI
        # -------------------------
        strong_2h = self._check_side(
            expected=meta.get("expected_2h"),
            market=meta.get("market_2h"),
            label="İKİNCİ YARI",
            notes=notes,
        )
        if strong_2h:
            strong_signals.append(strong_2h)

        # -------------------------
        # 3. MAÇ SONU
        # -------------------------
        strong_ms = self._check_side(
            expected=meta.get("expected_total"),
            market=meta.get("market_total"),
            label="MAÇ SONU",
            notes=notes,
        )
        if strong_ms:
            strong_signals.append(strong_ms)

        # -------------------------
        # FINAL
        # -------------------------
        if strong_signals:
            notes.insert(0, "📊 Güçlü istatistiksel yön tespit edildi:")
            for s in strong_signals:
                notes.append(f"• {s}")
            meta["analysis_status"] = "STRONG_SIGNAL"
        else:
            notes.append("📉 Güçlü bir istatistiksel yön oluşmadı.")
            meta["analysis_status"] = "NO_STRONG_SIGNAL"

        meta["strong_signals"] = strong_signals
        core.notes = notes
        return core

    # -------------------------------------------------
    # SIDE CHECK
    # -------------------------------------------------
    def _check_side(
        self,
        expected: Optional[float],
        market: Optional[float],
        label: str,
        notes: List[str],
    ) -> Optional[str]:
        if expected is None or market is None:
            return None

        diff = expected - market

        if diff >= self.MIN_EDGE:
            notes.append(f"{label}: İstatistik {expected:.1f}, Market {market:.1f} → ÜST yönü güçlü.")
            return f"{label} ÜST"
        if diff <= -self.MIN_EDGE:
            notes.append(f"{label}: İstatistik {expected:.1f}, Market {market:.1f} → ALT yönü güçlü.")
            return f"{label} ALT"

        return None
