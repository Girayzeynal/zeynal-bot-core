"""Deterministic percentile bootstrap for observed prediction-error uncertainty."""
from __future__ import annotations

import math
import random
from statistics import fmean


def bootstrap_mean_interval(values: list[float], *, draws: int = 2000,
                            seed: int = 2026, confidence: float = 0.95) -> dict | None:
    if len(values) < 2:
        return None
    if type(draws) is not int or draws < 100:
        raise ValueError("draws must be >= 100")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    if any(not math.isfinite(v) for v in values):
        raise ValueError("nonfinite error sample")
    rng = random.Random(seed)
    n = len(values)
    samples = sorted(fmean(values[rng.randrange(n)] for _ in range(n))
                     for _ in range(draws))
    lower = max(0, math.floor(draws * (1 - confidence) / 2))
    upper = min(draws - 1, math.ceil(draws * (1 + confidence) / 2) - 1)
    return {"estimate": fmean(values), "lower": samples[lower],
            "upper": samples[upper], "confidence": confidence,
            "method": "iid_percentile_bootstrap", "draws": draws, "n": n}
