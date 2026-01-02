from __future__ import annotations

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
