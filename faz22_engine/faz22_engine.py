from __future__ import annotations

from typing import Dict, Any, List, Optional


class Faz22Engine:
    """
    FAZ-22 v3 — STRONG SIDE FILTER

    Amaç:
    - Zorla tahmin YOK
    - Sadece güçlü istatistiksel + market uyumu varsa konuş
    - 1Y / 2Y / MS ayrı ayrı değerlendir
    - Market yoksa → NO_STRONG_SIGNAL
    """

    # ---- PARAMETRELER ----
    EDGE_MIN_ABS = 4.0          # minimum mutlak fark (puan)
    EDGE_STD_MULT = 0.30        # std'e göre minimum fark
    CONF_MIN = 0.62             # confidence_tight altı konuşmaz
    MAX_RISK_FOR_PLAY = "MEDIUM"

    def _risk_rank(self, risk: str) -> int:
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(risk, 3)

    def _eval_block(
        self,
        label: str,
        expected: Optional[float],
        market: Optional[float],
        std: Optional[float],
        conf_tight: float,
        risk: str,
        notes: List[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Tek blok (1H / 2H / MS) değerlendirmesi
        """
        if expected is None or market is None or std is None:
            return None

        diff = expected - market
        min_edge = max(self.EDGE_MIN_ABS, std * self.EDGE_STD_MULT)

        if abs(diff) < min_edge:
            return None

        if conf_tight < self.CONF_MIN:
            return None

        if self._risk_rank(risk) > self._risk_rank(self.MAX_RISK_FOR_PLAY):
            return None

        direction = "ÜST" if diff > 0 else "ALT"

        notes.append(
            f"✅ {label}: expected={expected:.1f} | market={market:.1f} | "
            f"diff={diff:+.1f} ≥ {min_edge:.1f}"
        )

        return {
            "segment": label,
            "direction": direction,
            "edge": round(diff, 2),
            "threshold": round(min_edge, 2),
        }

    # =====================================================
    # MAIN
    # =====================================================
    def score_and_finalize(self, core):
        meta = core.meta
        notes = core.notes

        strong_signals: List[Dict[str, Any]] = []

        # Ortak metrikler
        conf_tight = float(meta.get("confidence_tight", 0.0))
        risk = meta.get("risk", "HIGH")
        sim_std = meta.get("sim_std")

        # -------- MARKET --------
        market_total = meta.get("market_total")

        if market_total is None:
            meta["analysis_status"] = "NO_STRONG_SIGNAL"
            meta["uncertainty_level"] = "YÜKSEK"
            notes.append("⚠️ Market verisi yok → güçlü sinyal üretilemez.")
            meta["strong_signals"] = []
            return core

        # -------- MS --------
        strong = self._eval_block(
            label="MAÇ SONU",
            expected=meta.get("expected_total"),
            market=market_total,
            std=sim_std,
            conf_tight=conf_tight,
            risk=risk,
            notes=notes,
        )
        if strong:
            strong_signals.append(strong)

        # -------- 1Y --------
        strong = self._eval_block(
            label="İLK YARI",
            expected=meta.get("expected_1h"),
            market=market_total / 2 if market_total else None,
            std=sim_std * 0.7 if sim_std else None,
            conf_tight=conf_tight,
            risk=risk,
            notes=notes,
        )
        if strong:
            strong_signals.append(strong)

        # -------- 2Y --------
        strong = self._eval_block(
            label="İKİNCİ YARI",
            expected=meta.get("expected_2h"),
            market=market_total / 2 if market_total else None,
            std=sim_std * 0.7 if sim_std else None,
            conf_tight=conf_tight,
            risk=risk,
            notes=notes,
        )
        if strong:
            strong_signals.append(strong)

        # =====================================================
        # KARAR
        # =====================================================
        if strong_signals:
            meta["analysis_status"] = "STRONG_SIGNAL"
            meta["uncertainty_level"] = "DÜŞÜK"
            meta["strong_signals"] = strong_signals

            # Telegram'da net görünmesi için
            notes.append("🎯 Güçlü istatistiksel sinyal tespit edildi.")
        else:
            meta["analysis_status"] = "NO_STRONG_SIGNAL"
            meta["uncertainty_level"] = "YÜKSEK"
            meta["strong_signals"] = []

            notes.append(
                "📉 Güçlü bir istatistiksel + market uyumu yok. "
                "Bu karşılaşma analiz kapsamında izleme listesindedir."
            )

        return core 
