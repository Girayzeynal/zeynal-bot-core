from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, List

if TYPE_CHECKING:
    from faz13_engine.faz13_engine import Faz13CoreOutput


class Faz22Engine:
    """
    FAZ-22 v2.2 — STRONG SIDE FILTER (ANALYSIS / SIMULATION MODE)

    - Zorla tahmin YOK
    - Bahis dili YOK
    - Sadece güçlü istatistiksel yönler raporlanır
    - Analiz ve simülasyon amaçlıdır
    """

    EDGE_MIN_1H = 4.0
    EDGE_MIN_2H = 4.0
    CONF_MIN = 70.0

    @staticmethod
    def _safe_float(v: Any) -> Optional[float]:
        try:
            return float(v)
        except Exception:
            return None

    @staticmethod
    def _dir(edge: float) -> str:
        return "ÜST" if edge > 0 else "ALT"

    def _evaluate_half(
        self,
        name: str,
        expected: Optional[float],
        market: Optional[float],
        confidence: Optional[float],
        edge_min: float,
    ) -> Optional[Dict[str, Any]]:

        if expected is None or market is None or confidence is None:
            return None

        edge = expected - market

        if abs(edge) < edge_min:
            return None

        if confidence < self.CONF_MIN:
            return None

        return {
            "half": name,
            "expected": round(expected, 1),
            "market": round(market, 1),
            "edge": round(edge, 1),
            "direction": self._dir(edge),
            "confidence": round(confidence, 1),
        }

    def score_and_finalize(self, core: "Faz13CoreOutput") -> "Faz13CoreOutput":
        meta = core.meta

        conf = self._safe_float(meta.get("confidence_pct"))
        market_1h = self._safe_float(meta.get("market_1h"))
        market_2h = self._safe_float(meta.get("market_2h"))
        exp_1h = self._safe_float(meta.get("expected_1h"))
        exp_2h = self._safe_float(meta.get("expected_2h"))

        decisions: List[Dict[str, Any]] = []

        d1 = self._evaluate_half("İLK YARI", exp_1h, market_1h, conf, self.EDGE_MIN_1H)
        if d1:
            decisions.append(d1)

        d2 = self._evaluate_half("İKİNCİ YARI", exp_2h, market_2h, conf, self.EDGE_MIN_2H)
        if d2:
            decisions.append(d2)

        meta["half_analysis"] = decisions
        meta["analysis_status"] = "STRONG_SIGNAL" if decisions else "NO_STRONG_SIGNAL"

        if not decisions:
            meta["uncertainty_level"] = "YÜKSEK"
        elif len(decisions) == 1:
            meta["uncertainty_level"] = "ORTA"
        else:
            meta["uncertainty_level"] = "DÜŞÜK"

        core.notes = self.render_user_summary(core)
        return core

    def render_user_summary(self, core: "Faz13CoreOutput") -> List[str]:
        ctx = core.ctx
        meta = core.meta
        lines: List[str] = []

        lines.append(f"🏀 {ctx.home} – {ctx.away}")
        lines.append(f"🗓 {ctx.date}")
        lines.append("")

        decisions = meta.get("half_analysis") or []

        if not decisions:
            lines.append("📉 Güçlü bir istatistiksel yön tespit edilmedi.")
            lines.append("Bu karşılaşma analiz kapsamında izleme listesindedir.")
        else:
            for d in decisions:
                lines.append(f"📊 {d['half']} Analizi")
                lines.append(f"• Beklenen Toplam: {d['expected']}")
                lines.append(f"• Market Referansı: {d['market']}")
                lines.append(f"• Sapma (Edge): {d['edge']}")
                lines.append(f"📌 İstatistiksel Yön: {d['half']} {d['direction']}")
                lines.append(f"🔐 Model Güveni: {d['confidence']}%")
                lines.append("")

            lines.append(f"⚠️ Belirsizlik Seviyesi: {meta.get('uncertainty_level')}")

        lines.append("──────────────────")
        lines.append("ℹ️ Bu analiz ve simülasyon amaçlıdır.")
        lines.append("Herhangi bir şekilde bahis tavsiyesi değildir.")
        lines.append("İstatistiksel veriler ve model projeksiyonlarına dayanır.")

        return lines 
