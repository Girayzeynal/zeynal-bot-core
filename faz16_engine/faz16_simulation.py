from typing import Any
import numpy as np


def faz16_run_simulation(
    base_total: float,
    vol: float,
    n_iter: int = 10_000,
    line: float | None = None,
) -> dict[str, Any]:
    """
    Monte Carlo simülasyonu (heavy-tailed mixture).
    - base_total: beklenen toplam skor
    - vol: standart sapma
    - n_iter: örnek sayısı (INT olmalı) -> float gelirse int'e çevrilir
    - line: market çizgisi
    """

    # ✅ n_iter güvenliği (bazı yerlerde float gelebiliyor)
    try:
        n_iter = int(n_iter)
    except Exception:
        n_iter = 10_000
    if n_iter <= 0:
        n_iter = 10_000

    # vol güvenliği
    if vol <= 0:
        vol = max(8.0, base_total * 0.05)

    rng = np.random.default_rng()

    weights = rng.random(n_iter)
    samples_base = rng.normal(loc=base_total, scale=vol, size=n_iter)
    samples_heavy = rng.normal(loc=base_total, scale=vol * 1.5, size=n_iter)
    samples = np.where(weights < 0.8, samples_base, samples_heavy)

    summary: dict[str, Any] = {
        "mean": float(np.mean(samples)),
        "std": float(np.std(samples)),
        "p25": float(np.percentile(samples, 25)),
        "p50": float(np.percentile(samples, 50)),
        "p75": float(np.percentile(samples, 75)),
    }

    if line is not None:
        line = float(line)
        over_prob = float(np.mean(samples > line))
        under_prob = 1.0 - over_prob
        summary["line"] = line
        summary["p_over"] = over_prob
        summary["p_under"] = under_prob

    return summary 
