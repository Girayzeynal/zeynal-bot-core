from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from faz13_engine.faz13_engine import Faz13CoreOutput


class Faz22Engine:
    """
    FAZ-22 FINAL ENGINE

    - FAZ-13 meta'yı KORUR
    - Confidence / risk'i override ETMEZ
    - Sadece eksik alanları tamamlar
    - DEGRADED_MODE'a saygı duyar
    """

    def score_and_finalize(self, core: "Faz13CoreOutput") -> "Faz13CoreOutput":
        meta = core.meta  # ❗ COPY YOK — DOĞRUDAN REFERANS

        # -------------------------------------------------
        # SIMULATION (varsa koru)
        # -------------------------------------------------
        sim_mean = meta.get("sim_mean")
        sim_std = meta.get("sim_std")

        if sim_mean is not None:
            meta["sim_mean"] = sim_mean
        if sim_std is not None:
            meta["sim_std"] = sim_std

        # -------------------------------------------------
        # CONFIDENCE / RISK
        # -------------------------------------------------
        # Eğer FAZ-13 zaten hesapladıysa ASLA dokunma
        if "confidence_pct" in meta and "risk" in meta:
            return core

        # Fallback (sadece hiç yoksa)
        try:
            total_low, total_high = core.total_band
            width = max(1.0, (total_high - total_low) / 2.0)
            expected = sim_mean if sim_mean is not None else (total_low + total_high) / 2.0
            center = (total_low + total_high) / 2.0

            confidence_pct = max(
                5.0,
                min(95.0, (1.0 - abs(expected - center) / width) * 100.0),
            )
        except Exception:
            confidence_pct = 10.0

        meta.setdefault("confidence_pct", round(confidence_pct, 1))

        # Risk mapping (modern)
        if meta.get("degraded_mode"):
            risk = "HIGH"
        else:
            if confidence_pct >= 75:
                risk = "LOW"
            elif confidence_pct >= 55:
                risk = "MEDIUM"
            else:
                risk = "HIGH"

        meta.setdefault("risk", risk)

        return core 
