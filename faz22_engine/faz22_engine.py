from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from faz13_engine.faz13_engine import Faz13CoreOutput


class Faz22Engine:
    def score_and_finalize(self, core: "Faz13CoreOutput") -> "Faz13CoreOutput":
        """
        FAZ-22 scoring + meta enrichment.
        Bu versiyon, sezon edge-case’ini NBA resolver ile temiz şekilde geçirir.
        """

        total_low, total_high = core.total_band
        sim_mean = core.meta.get("sim_mean")
        sim_std = core.meta.get("sim_std")

        meta = core.meta.copy()

        if sim_mean is not None:
            expected = sim_mean
        else:
            expected = (total_low + total_high) / 2

        # NBA resolver signal
        season_resolved = bool(meta.get("season"))

        # confidence hesaplama
        try:
            center = expected
            width = (total_high - total_low) / 2
            if width > 0:
                confidence = float(1.0 - abs(center - expected) / width) * 100
            else:
                confidence = 10.0
        except Exception:
            confidence = 10.0

        risk = "LOW" if confidence >= 50 else "HIGH"

        # Eğer sezon resolved olarak geldiyse artık NO_PLAY kilidini aç
        if season_resolved:
            # override risk thresholds
            risk = risk
        else:
            # fallback
            risk = "NO_PLAY"

        meta.update({
            "sim_mean": sim_mean,
            "sim_std": sim_std,
            "confidence": confidence,
            "risk": risk,
        })

        core.meta = meta
        return core
