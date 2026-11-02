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


def moving_block_mean_interval(values: list[float], *, block_size: int = 5,
                               draws: int = 2000, seed: int = 2026,
                               confidence: float = 0.95) -> dict | None:
    """Circular moving-block bootstrap; input must be chronologically ordered."""
    n = len(values)
    if n < 2 or n < 2 * block_size:
        return None
    if type(block_size) is not int or block_size < 2:
        raise ValueError("block_size must be >= 2")
    if type(draws) is not int or draws < 100:
        raise ValueError("draws must be >= 100")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    if any(not math.isfinite(v) for v in values):
        raise ValueError("nonfinite error sample")
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(values[(start + offset) % n] for offset in range(block_size))
        estimates.append(fmean(sample[:n]))
    estimates.sort()
    lo = max(0, math.floor(draws * (1 - confidence) / 2))
    hi = min(draws - 1, math.ceil(draws * (1 + confidence) / 2) - 1)
    return {"estimate": fmean(values), "lower": estimates[lo],
            "upper": estimates[hi], "confidence": confidence,
            "method": "circular_moving_block_bootstrap",
            "draws": draws, "n": n, "block_size": block_size}


def block_length_sensitivity(values: list[float],
                             block_sizes: tuple[int, ...] = (3, 5, 7, 10)) -> dict:
    """Compare block lengths without silently choosing the narrowest interval."""
    if not block_sizes or len(set(block_sizes)) != len(block_sizes):
        raise ValueError("block sizes must be nonempty and unique")
    if any(type(size) is not int or size < 2 for size in block_sizes):
        raise ValueError("block sizes must be integers >= 2")
    results = {
        str(size): moving_block_mean_interval(values, block_size=size)
        for size in block_sizes
    }
    available = [entry for entry in results.values() if entry is not None]
    widths = [entry["upper"] - entry["lower"] for entry in available]
    return {
        "block_sizes": results,
        "eligible_block_lengths": len(available),
        "interval_width_min": min(widths) if widths else None,
        "interval_width_max": max(widths) if widths else None,
        "selection_policy": "descriptive_only_no_automatic_best_block",
    }
