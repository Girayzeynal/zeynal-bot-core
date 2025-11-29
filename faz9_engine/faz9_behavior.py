from typing import Dict, Any, List

import numpy as np
import pandas as pd


def faz9_compute_trend(
    totals: List[float],
    window: int = 12,
) -> Dict[str, float]:
    """
    Toplam skor serisi üzerinden:
    - Trend (EWMA)
    - Volatilite (std)
    - Noise index (std / mean) hesaplar.
    """

    arr = np.array(totals, dtype=float)
    if arr.size == 0:
        return {"trend": 0.0, "vol": 0.0, "noise": 0.0}

    s = pd.Series(arr)
    ewma = s.ewm(span=min(window, len(s)), adjust=False).mean().iloc[-1]
    vol = float(s.rolling(window=min(window, len(s))).std().iloc[-1] or 0.0)

    mean_val = float(s.mean())
    noise = float(vol / mean_val) if mean_val > 0 else 0.0

    return {
        "trend": float(ewma),
        "vol": vol,
        "noise": noise,
    }


def faz9_behavior_curve(
    totals: List[float],
    lines: List[float],
) -> Dict[str, Any]:
    """
    Basit behavior curve:
    - Fark dağılımını hesaplar (toplam - line)
    - Edge yoğunluğunu ölçen bir BehaviorIndex döner.
    """

    if not totals or not lines:
        return {
            "behavior_index": 0.0,
            "line_fit": None,
        }

    arr_totals = np.array(totals, dtype=float)
    arr_lines = np.array(lines, dtype=float)

    # güvenlik: uzunluklar eşit değilse en kısaya indir
    n = min(len(arr_totals), len(arr_lines))
    arr_totals = arr_totals[-n:]
    arr_lines = arr_lines[-n:]

    diffs = arr_totals - arr_lines
    mean_diff = float(np.mean(diffs))
    std_diff = float(np.std(diffs))

    # BehaviorIndex: mutlak avantaj / volatilite
    if std_diff == 0:
        behavior_index = abs(mean_diff)
    else:
        behavior_index = abs(mean_diff) / std_diff

    return {
        "behavior_index": float(behavior_index),
        "line_fit": {
            "mean_diff": mean_diff,
            "std_diff": std_diff,
        },
    }
