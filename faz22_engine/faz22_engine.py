from __future__ import annotations

from typing import Any, Dict, List, Optional


class Faz22Engine:
    """
    FAZ-22 v3.1 — Segment-Aware Strong Side Filter (ANALYSIS / SIMULATION)

    - Zorla tahmin yok
    - Bahis dili yok
    - Sadece güçlü sinyal varsa konuşur
    - MS / 1Y / 2Y / Q1-Q4 ayrı değerlendirilir
    - STD (sim_std) yüksekse full-game susabilir ama yarı/çeyrek konuşabilir
    """

    # -------------------------
    # Tunables (pratik eşikler)
    # -------------------------
    CONF_MIN_PCT = 60.0       # confidence_pct altı konuşmaz
    EDGE_MIN_MS = 6.0         # maç sonu minimum mutlak edge
    EDGE_MIN_1H = 4.0         # yarı minimum mutlak edge
    EDGE_MIN_Q = 3.0          # çeyrek minimum mutlak edge

    # STD oranları (NBA pratik segment ölçekleri)
    STD_RATIO_1H = 0.55
    STD_RATIO_2H = 0.60
    STD_RATIO_Q = 0.35

    # STD bazlı eşik çarpanı: |edge| >= max(min_edge, std_seg * k)
    STD_K_MS = 0.40
    STD_K_1H = 0.35
    STD_K_Q = 0.30

    # -------------------------
    # Utils
    # -------------------------
    @staticmethod
    def _sf(v: Any) -> Optional[float]:
        try:
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    @staticmethod
    def _dir(edge: float) -> str:
        return "ÜST" if edge > 0 else "ALT"

    @staticmethod
    def _fmt1(x: Optional[float]) -> str:
        return "?" if x is None else f"{x:.1f}"

    def _threshold(self, seg: str, std_seg: Optional[float]) -> float:
        if seg == "MS":
            base = self.EDGE_MIN_MS
            k = self.STD_K_MS
        elif seg in ("1Y", "2Y"):
            base = self.EDGE_MIN_1H
            k = self.STD_K_1H
        else:
            base = self.EDGE_MIN_Q
            k = self.STD_K_Q

        if std_seg is None:
            return base
        return max(base, float(std_seg) * k)

    # -------------------------
    # Core evaluation
    # -------------------------
    def _eval_segment(
        self,
        seg: str,
        expected: Optional[float],
        market: Optional[float],
        std_seg: Optional[float],
        conf_pct: float,
        out_notes: List[str],
    ) -> Optional[Dict[str, Any]]:
        if expected is None or market is None:
            return None

        edge = expected - market
        thr = self._threshold(seg, std_seg)

        # filtreler
        if conf_pct < self.CONF_MIN_PCT:
            return None
        if abs(edge) < thr:
            return None

        out_notes.append(
            f"✅ {seg}: beklenen={expected:.1f} | market={market:.1f} | edge={edge:+.1f} | eşik≥{thr:.1f}"
        )

        return {
            "segment": seg,
            "direction": self._dir(edge),
            "edge": round(edge, 2),
            "threshold": round(thr, 2),
            "expected": round(expected, 2),
            "market": round(market, 2),
        }

    # -------------------------
    # Public API
    # -------------------------
    def score_and_finalize(self, core):
        meta: Dict[str, Any] = getattr(core, "meta", {}) or {}
        base_notes: List[str] = getattr(core, "notes", []) or []

        # --- inputs ---
        conf_pct = self._sf(meta.get("confidence_pct")) or 0.0
        sim_std = self._sf(meta.get("sim_std"))  # FAZ-16'den gelir
        market_total = self._sf(meta.get("market_total"))

        # Market yoksa güçlü sinyal üretmeyiz (tasarım gereği)
        if market_total is None:
            meta["analysis_status"] = "NO_STRONG_SIGNAL"
            meta["uncertainty_level"] = "YÜKSEK"
            meta["strong_signals"] = []
            base_notes.append("⚠️ Market verisi yok → güçlü sinyal üretilemez.")
            core.meta = meta
            core.notes = base_notes
            return core

        # --- derive segment markets ---
        market_ms = market_total
        market_1h = self._sf(meta.get("market_1h"))
        market_2h = self._sf(meta.get("market_2h"))

        # Eğer 1Y/2Y market yoksa, MS/2 fallback (analiz için makul)
        if market_1h is None:
            market_1h = market_total / 2.0
        if market_2h is None:
            market_2h = market_total / 2.0

        market_q = market_total / 4.0

        # --- expected values from FAZ-13 ---
        exp_ms = self._sf(meta.get("expected_total"))
        exp_1h = self._sf(meta.get("expected_1h"))
        exp_2h = self._sf(meta.get("expected_2h"))
        exp_q1 = self._sf(meta.get("expected_q1"))
        exp_q2 = self._sf(meta.get("expected_q2"))
        exp_q3 = self._sf(meta.get("expected_q3"))
        exp_q4 = self._sf(meta.get("expected_q4"))

        # --- segment std derivation ---
        std_ms = sim_std
        std_1h = (sim_std * self.STD_RATIO_1H) if sim_std is not None else None
        std_2h = (sim_std * self.STD_RATIO_2H) if sim_std is not None else None
        std_q = (sim_std * self.STD_RATIO_Q) if sim_std is not None else None

        # store for debug / research
        meta["std_ms"] = None if std_ms is None else round(std_ms, 3)
        meta["std_1h"] = None if std_1h is None else round(std_1h, 3)
        meta["std_2h"] = None if std_2h is None else round(std_2h, 3)
        meta["std_q"] = None if std_q is None else round(std_q, 3)

        # --- evaluate segments ---
        decision_notes: List[str] = []
        strong: List[Dict[str, Any]] = []

        # MS
        r = self._eval_segment("MS", exp_ms, market_ms, std_ms, conf_pct, decision_notes)
        if r:
            strong.append(r)

        # 1Y / 2Y
        r = self._eval_segment("1Y", exp_1h, market_1h, std_1h, conf_pct, decision_notes)
        if r:
            strong.append(r)

        r = self._eval_segment("2Y", exp_2h, market_2h, std_2h, conf_pct, decision_notes)
        if r:
            strong.append(r)

        # Q1–Q4
        r = self._eval_segment("Q1", exp_q1, market_q, std_q, conf_pct, decision_notes)
        if r:
            strong.append(r)
        r = self._eval_segment("Q2", exp_q2, market_q, std_q, conf_pct, decision_notes)
        if r:
            strong.append(r)
        r = self._eval_segment("Q3", exp_q3, market_q, std_q, conf_pct, decision_notes)
        if r:
            strong.append(r)
        r = self._eval_segment("Q4", exp_q4, market_q, std_q, conf_pct, decision_notes)
        if r:
            strong.append(r)

        # --- finalize meta ---
        meta["strong_signals"] = strong
        meta["analysis_status"] = "STRONG_SIGNAL" if strong else "NO_STRONG_SIGNAL"
        meta["uncertainty_level"] = "DÜŞÜK" if strong else "YÜKSEK"

        # --- Human-readable output (notes) ---
        # Eski note yığınını silmeden, karar özetini en üste koyuyoruz.
        summary: List[str] = []
        summary.append(f"📌 Analiz Özeti: market={market_total:.1f} | conf={conf_pct:.1f}% | std≈{self._fmt1(sim_std)}")
        summary.append("")

        if not strong:
            summary.append("📉 Güçlü bir istatistiksel + market uyumu yok.")
            summary.append("Bu karşılaşma analiz kapsamında izleme listesindedir.")
        else:
            summary.append("✅ Güçlü sinyal tespit edildi (segment bazlı):")
            for s in strong:
                summary.append(
                    f"• {s['segment']} {s['direction']} | edge={s['edge']:+.1f} (eşik≥{s['threshold']:.1f})"
                )

        summary.append("──────────────────")
        summary.append("ℹ️ Bu analiz ve simülasyon amaçlıdır.")
        summary.append("Herhangi bir şekilde bahis tavsiyesi değildir.")
        summary.append("İstatistiksel veriler ve model projeksiyonlarına dayanır.")

        # notes'u replace edelim: karar odaklı olsun
        core.notes = summary

        core.meta = meta
        return core 
