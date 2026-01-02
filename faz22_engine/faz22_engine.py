from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from faz13_engine.faz13_engine import Faz13CoreOutput


class Faz22Engine:
    """
    FAZ-22 v2 PRO-LEVEL RISK ENGINE (FINAL BUILD)

    Goals:
      - DO NOT break architecture: never recompute model outputs (expected_total/edge/market)
      - DO NOT overwrite FAZ-13 meta: only fill missing or add derived, explainable fields
      - Combine confidence + edge + tempo + market + degraded in a robust policy
      - Provide "neden bu karar" explanation in Telegram via meta fields

    Contract:
      - Keeps existing meta keys (market_total, edge_value, edge_threshold, confidence_pct, tempo_flag, degraded_mode)
      - Adds:
          meta["risk_score_0_100"]
          meta["risk_factors"] (list[str])
          meta["risk_policy"] (version tag)
          meta["risk_reason_short"] (single-line summary)
          meta["play_signal"] ("PLAY" | "NO_EDGE" | "NO_PLAY")
    """

    POLICY_VERSION = "FAZ22-RISK-v2.0"

    # -----------------------------
    # Utilities
    # -----------------------------
    @staticmethod
    def _safe_float(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(str(v).strip().replace(",", "."))
        except Exception:
            return None

    @staticmethod
    def _safe_str(v: Any) -> str:
        return "" if v is None else str(v)

    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        return lo if x < lo else hi if x > hi else x

    @staticmethod
    def _norm_tempo_flag(v: Any) -> str:
        s = str(v or "").strip().upper()
        if s in {"FAST", "SLOW", "NORMAL", "UNKNOWN"}:
            return s
        return "UNKNOWN"

    @staticmethod
    def _risk_label_from_score(score_0_100: float) -> str:
        # Lower score => lower risk => better
        if score_0_100 <= 35.0:
            return "LOW"
        if score_0_100 <= 60.0:
            return "MEDIUM"
        return "HIGH"

    @staticmethod
    def _play_signal(market_total: Optional[float], edge_value: Optional[float], degraded: bool) -> str:
        if degraded:
            return "NO_PLAY"
        if market_total is None:
            return "NO_PLAY"
        if edge_value is None:
            return "NO_EDGE"
        return "PLAY"

    # -----------------------------
    # Core policy
    # -----------------------------
    def _compute_risk_score(
        self,
        confidence_pct: Optional[float],
        market_total: Optional[float],
        edge_value: Optional[float],
        edge_threshold: Optional[float],
        tempo_flag: str,
        degraded: bool,
    ) -> Tuple[float, List[str], str]:
        """
        Returns:
          risk_score_0_100 (lower better),
          factors (list[str]),
          reason_short (one-liner)
        """
        factors: List[str] = []

        # Base risk starts at neutral
        risk = 50.0

        # 1) Degraded mode overrides
        if degraded:
            risk = 85.0
            factors.append("DEGRADED_MODE=TRUE → risk↑")
        else:
            factors.append("DEGRADED_MODE=FALSE")

        # 2) Market presence
        if market_total is None:
            risk += 15.0
            factors.append("MARKET_TOTAL=MISSING → risk↑")
        else:
            factors.append(f"MARKET_TOTAL={market_total:.1f}")

        # 3) Confidence contribution (higher confidence lowers risk)
        if confidence_pct is None:
            risk += 10.0
            factors.append("CONFIDENCE_PCT=MISSING → risk↑")
            conf = 0.0
        else:
            conf = self._clamp(float(confidence_pct), 0.0, 100.0)
            # map: 0..100 -> +12..-18 (higher conf => lower risk)
            conf_delta = 12.0 - (conf * 0.30)  # conf=0 => +12, conf=100 => -18
            risk += conf_delta
            factors.append(f"CONFIDENCE_PCT={conf:.1f} → risk{conf_delta:+.1f}")

        # 4) Tempo uncertainty (FAST/SLOW slightly higher variance)
        tempo = self._norm_tempo_flag(tempo_flag)
        if tempo == "FAST":
            risk += 5.0
            factors.append("TEMPO=FAST (variance↑) → risk+5")
        elif tempo == "SLOW":
            risk += 3.0
            factors.append("TEMPO=SLOW (variance↑) → risk+3")
        elif tempo == "UNKNOWN":
            risk += 6.0
            factors.append("TEMPO=UNKNOWN → risk+6")
        else:
            factors.append("TEMPO=NORMAL")

        # 5) Edge clarity (if present) lowers risk; unclear/no-edge increases
        thr = self._safe_float(edge_threshold)
        ev = self._safe_float(edge_value)

        if market_total is None:
            # can't judge edge without market; already penalized above
            pass
        else:
            if ev is None or thr is None or thr <= 0:
                risk += 8.0
                factors.append("EDGE=UNAVAILABLE → risk+8")
            else:
                abs_ev = abs(ev)
                # ratio: 0.. -> edge strength
                ratio = abs_ev / thr if thr > 0 else 0.0

                if ratio >= 2.0:
                    risk -= 14.0
                    factors.append(f"EDGE_STRONG |ev|/thr={ratio:.2f} → risk-14")
                elif ratio >= 1.2:
                    risk -= 9.0
                    factors.append(f"EDGE_GOOD |ev|/thr={ratio:.2f} → risk-9")
                elif ratio >= 0.8:
                    risk -= 3.0
                    factors.append(f"EDGE_BORDERLINE |ev|/thr={ratio:.2f} → risk-3")
                else:
                    risk += 6.0
                    factors.append(f"NO_EDGE |ev|/thr={ratio:.2f} → risk+6")

                # small extra penalty for extreme totals without strong edge (variance)
                if ratio < 1.2 and market_total is not None:
                    if market_total >= 245:
                        risk += 3.0
                        factors.append("TOTAL_VERY_HIGH + weak edge → risk+3")
                    elif market_total <= 205:
                        risk += 2.0
                        factors.append("TOTAL_VERY_LOW + weak edge → risk+2")

        risk = self._clamp(risk, 0.0, 100.0)

        # one-line reason
        reason_short = (
            f"risk={risk:.0f}/100 | conf={conf:.1f} | tempo={tempo} | "
            f"market={'ok' if market_total is not None else 'missing'} | "
            f"edge={'ok' if (ev is not None and thr is not None and thr > 0) else 'na'}"
        )
        return risk, factors, reason_short

    # -----------------------------
    # Public API
    # -----------------------------
    def score_and_finalize(self, core: "Faz13CoreOutput") -> "Faz13CoreOutput":
        meta: Dict[str, Any] = core.meta  # DO NOT copy / overwrite

        # Pull signals (do not assume they exist)
        confidence_pct = self._safe_float(meta.get("confidence_pct"))
        market_total = self._safe_float(meta.get("market_total"))  # should be wired in main.py
        edge_value = self._safe_float(meta.get("edge_value"))
        edge_threshold = self._safe_float(meta.get("edge_threshold"))
        tempo_flag = self._norm_tempo_flag(meta.get("tempo_flag") or getattr(core, "tempo_flag", None))
        degraded = bool(meta.get("degraded_mode", False))

        # If FAZ-13 only provided market via core.market but not meta, recover it (non-destructive)
        if market_total is None and isinstance(getattr(core, "market", None), dict):
            market_total = self._safe_float(core.market.get("total"))
            if market_total is not None:
                meta.setdefault("market_total", market_total)

        # Compute risk score + explainability
        score, factors, reason_short = self._compute_risk_score(
            confidence_pct=confidence_pct,
            market_total=market_total,
            edge_value=edge_value,
            edge_threshold=edge_threshold,
            tempo_flag=tempo_flag,
            degraded=degraded,
        )

        # Final risk label
        risk = self._risk_label_from_score(score)

        # "play signal" (high level decision)
        play_signal = self._play_signal(market_total, edge_value, degraded)

        # DO NOT overwrite if explicitly set by FAZ-13 unless it's missing/garbage
        # But we *do* want FAZ-22 to be the authoritative risk policy layer.
        meta["risk_policy"] = self.POLICY_VERSION
        meta["risk_score_0_100"] = round(score, 1)
        meta["risk"] = risk
        meta["play_signal"] = play_signal
        meta["risk_reason_short"] = reason_short
        meta["risk_factors"] = factors

        # Also ensure tempo_flag is present in meta for explainability
        meta.setdefault("tempo_flag", tempo_flag)

        # Optional: add a single clean note line for Telegram (without spamming)
        notes = getattr(core, "notes", None)
        if isinstance(notes, list):
            # Remove any previous FAZ-22 v2 note to avoid duplicates
            cleaned = []
            for n in notes:
                if isinstance(n, str) and n.startswith("🧭 FAZ-22 Risk:"):
                    continue
                cleaned.append(n)
            cleaned.append(f"🧭 FAZ-22 Risk: {risk} (score {score:.0f}/100) • {reason_short}")
            core.notes = cleaned

        return core 
