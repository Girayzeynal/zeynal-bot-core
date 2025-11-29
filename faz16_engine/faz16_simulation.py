from typing import Dict, Any, Tuple

import numpy as np


def faz16_run_simulation(
    base_total: float,
    vol: float,
    n_iter: int = 10000,
    line: float | None = None,
) -> Dict[str, Any]:
    """
    Basit Monte Carlo:

    - Normal dağılmış toplam skor üretir.
    - Ortalama, std, percentieler hesaplar.
    - Eğer line verilirse OVER/UNDER olasılıklarını döner.
    """

    if vol <= 0:
        vol = max(8.0, base_total * 0.06)  # minimum volatilite

    rng = np.random.default_rng()
    samples = rng.normal(loc=base_total, scale=vol, size=n_iter)

    summary: Dict[str, Any] = {
        "mean": float(np.mean(samples)),
        "std": float(np.std(samples)),
        "p25": float(np.percentile(samples, 25)),
        "p50": float(np.percentile(samples, 50)),
        "p75": float(np.percentile(samples, 75)),
    }

    if line is not None:
        over = float(np.mean(samples > line))
        under = 1.0 - over
        summary["line"] = float(line)
        summary["p_over"] = over
        summary["p_under"] = under

    return summary
