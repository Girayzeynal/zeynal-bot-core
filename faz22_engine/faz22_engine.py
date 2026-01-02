from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, List

if TYPE_CHECKING:
    from faz13_engine import Faz13CoreOutput


class Faz22Engine:
    """
    FAZ-22 v3 — STRONG SIDE FILTER (ANALYSIS / SIMULATION MODE)

    - Zorla tahmin YOK
    - Bahis dili YOK
    - Sadece güçlü istatistiksel sinyal varsa konuşur
    - 1Y / 2Y / MS / Q1–Q4 ayrı ayrı değerlendirilir
    - İnsan okunur Telegram çıktısı üretir
    """

    # -------------------------
    # CONFIG (tunable thresholds)
    # -------------------------
    CONF_MIN = 70.0

    EDGE_MIN = {
        "1Y": 4.0,
        "2Y": 4.0,
        "MS": 6.0,
        "Q": 3.0,   # Q1–Q4
    }

    # -------------------------
    # HELPERS
    # -------------------------
    @staticmethod
    def _safe_float(v: Any) -> Optional[float]:
        try:
            return float(v)
        except Exception:
            return None

    @staticmethod
    def _direction(edge: float) -> str:
        return "ÜST" if edge > 0 else "ALT"

    # -------------------------
    # CORE STRONG-SIDE CHECK
    # -------------------------
    def _evaluate(
        self,
        label: str,
        expected: Optional[float],
        market: Optional[float],
        confidence: Optional[float],
        edge_min: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Returns dict if STRONG, else None
        """
        if expected is None or market is None or confidence is None:
            return None

        edge = expected - market

        if abs(edge) < edge_min:
            return None

        if confidence < self.CONF_MIN:
            return None

        return {
            "label": label,
            "expected": round(expected, 1),
            "market": round(market, 1),
            "edge": round(edge, 1),
            "direction": self._direction(edge),
            "confidence": round(confidence, 1),
        }

    # -------------------------
    # PUBLIC API
    # -------------------------
    def score_and_finalize(self, core: "Faz13CoreOutput") -> "Faz13CoreOutput":
        meta = core.meta
        notes: List[str] = []

        confidence = self._safe_float(meta.get("confidence_pct"))
        market_total = self._safe_float(meta.get("market_total"))

        strong_signals: List[Dict[str, Any]] = []

        # ---- MAÇ SONU ----
        ms = self._evaluate(
            "MAÇ SONU",
            self._safe_float(meta.get("expected_total")),
            market_total,
            confidence,
            self.EDGE_MIN["MS"],
        )
        if ms:
            strong_signals.append(ms)

        # ---- İLK YARI ----
        y1 = self._evaluate(
            "İLK YARI",
            self._safe_float(meta.get("expected_1h")),
            market_total / 2 if market_total else None,
            confidence,
            self.EDGE_MIN["1Y"],
        )
        if y1:
            strong_signals.append(y1)

        # ---- İKİNCİ YARI ----
        y2 = self._evaluate(
            "İKİNCİ YARI",
            self._safe_float(meta.get("expected_2h")),
            market_total / 2 if market_total else None,
            confidence,
            self.EDGE_MIN["2Y"],
        )
        if y2:
            strong_signals.append(y2)

        # ---- PERİYOTLAR ----
        for q in ("q1", "q2", "q3", "q4"):
            exp_q = self._safe_float(meta.get(f"expected_{q}"))
            q_res = self._evaluate(
                q.upper(),
                exp_q,
                market_total / 4 if market_total else None,
                confidence,
                self.EDGE_MIN["Q"],
            )
            if q_res:
                strong_signals.append(q_res)

        # ---- META WRITE (NON-DESTRUCTIVE) ----
        meta["strong_signals"] = strong_signals
        meta["analysis_status"] = "STRONG_SIGNAL" if strong_signals else "NO_STRONG_SIGNAL"

        if not strong_signals:
            meta["uncertainty_level"] = "YÜKSEK"
        elif len(strong_signals) == 1:
            meta["uncertainty_level"] = "ORTA"
        else:
            meta["uncertainty_level"] = "DÜŞÜK"

        # ---- TELEGRAM SUMMARY ----
        core.notes = self._render_summary(core)

        return core

    # -------------------------
    # TELEGRAM OUTPUT (HUMAN)
    # -------------------------
    def _render_summary(self, core: "Faz13CoreOutput") -> List[str]:
        ctx = core.ctx
        meta = core.meta
        lines: List[str] = []

        lines.append(f"🏀 {ctx.home} – {ctx.away}")
        lines.append(f"🗓 {ctx.date}")
        lines.append("")

        signals = meta.get("strong_signals") or []

        if not signals:
            lines.append("📉 Güçlü bir istatistiksel yön tespit edilmedi.")
            lines.append("Bu karşılaşma analiz kapsamında izleme listesindedir.")
        else:
            for s in signals:
                lines.append(f"📊 {s['label']} Analizi")
                lines.append(f"• Beklenen Toplam: {s['expected']}")
                lines.append(f"• Market Referansı: {s['market']}")
                lines.append(f"• Sapma (Edge): {s['edge']}")
                lines.append(f"📌 İstatistiksel Yön: {s['label']} {s['direction']}")
                lines.append(f"🔐 Model Güveni: {s['confidence']}%")
                lines.append("")

            lines.append(f"⚠️ Belirsizlik Seviyesi: {meta.get('uncertainty_level')}")

        lines.append("──────────────────")
        lines.append("ℹ️ Bu analiz ve simülasyon amaçlıdır.")
        lines.append("Herhangi bir şekilde bahis tavsiyesi değildir.")
        lines.append("İstatistiksel veriler ve model projeksiyonlarına dayanır.")

        return lines  
