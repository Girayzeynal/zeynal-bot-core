"""
faz22_engine – Meta scoring for basketball predictions.

This engine evaluates a ``Faz13CoreOutput`` (optionally enriched by
Faz17Engine) and produces a confidence score and risk label.  It
considers band width (volatility proxy), blowout risk, tempo flags
and market alignment to assign a score between 25 and 92.  It also
performs basic consistency checks on the bands to catch improbable
configurations.  Results are stored in ``core.meta`` and a concise
note is appended to ``core.notes``.
"""

from __future__ import annotations

import math
from typing import List

from faz13_engine import Faz13CoreOutput


class Faz22Engine:
    """Compute confidence and risk for a pre‑match prediction."""

    def __init__(self) -> None:
        pass

    def score_and_finalize(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        """Assign a confidence score and risk label to the prediction.

        The base confidence is inversely proportional to the width of the
        total band: a tighter band implies greater certainty.  The score
        is adjusted down for high blowout risk or tempo anomalies and
        slightly up or down depending on whether a market line lies
        outside the predicted band (suggesting a clearer edge) or inside
        (edge is weak).  Risk levels are derived from the final score
        and certain flags.  Consistency checks look for mismatches
        between team bands and the total band.
        """
        lo, hi = core.total_band
        width = max(1, hi - lo)
        # Base confidence: narrower band -> higher confidence
        conf = 72.0 - (width - 12) * 2.2
        conf = max(40.0, min(88.0, conf))
        # Adjust for blowout risk
        if core.blowout_risk == "HIGH":
            conf -= 10
        elif core.blowout_risk == "MID":
            conf -= 5
        # Adjust for tempo flags
        if core.tempo_flag == "FAKE_TEMPO_RISK":
            conf -= 6
        elif core.tempo_flag == "FAST":
            conf -= 2
        # Market alignment adjustments
        m = core.market or {}
        if m.get("status") == "OK":
            line = m.get("market_total")
            if isinstance(line, (int, float)):
                if line < lo or line > hi:
                    conf += 4
                else:
                    conf -= 4
        # Clamp final confidence
        conf = max(25.0, min(92.0, conf))
        # Determine risk label
        risk = "LOW"
        if conf < 52.0 or core.blowout_risk == "HIGH":
            risk = "HIGH"
        elif conf < 66.0 or core.blowout_risk == "MID" or core.tempo_flag == "FAKE_TEMPO_RISK":
            risk = "MID"
        # Consistency checks
        issues: List[str] = []
        hb_lo, hb_hi = core.home_band
        ab_lo, ab_hi = core.away_band
        if hb_lo + ab_lo > hi + 6:
            issues.append(
                "Takım bantlarının alt uçları toplam bandın üstünde (alt uç tutarsızlığı)"
            )
        if hb_hi + ab_hi < lo - 6:
            issues.append(
                "Takım bantlarının üst uçları toplam bandın altında (üst uç tutarsızlığı)"
            )
        if not issues:
            issues.append("OK")
        # Populate meta
        core.meta = {
            "confidence": round(conf, 1),
            "risk": risk,
            "issues": issues[:6],
            "mode": "FAZ‑22 META ENGINE",
        }
        # Append note summarising orientation, confidence and risk
        core.notes.append(
            f"Skor yönü: {core.ou_direction} | Güven: {round(conf)} | Risk: {risk}"
        )
        if any(i != "OK" for i in issues):
            core.notes.append(
                "Hata avcısı: " + " | ".join([i for i in issues if i != "OK"][:2])
            )
        return core
