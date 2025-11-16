from .faz6_core import (
    run_faz6_test,
    run_faz6_auto,
    run_faz6_risk,
    run_faz6_edge,
    run_faz6_real,
)


def run_faz6_balance(context: dict | None = None, mode: str = "auto") -> dict:
    """
    FAZ-6 BALANCE modu.

    Amaç:
      - test / auto / risk / edge / real çıktılarından
        tek bir 'dengeli' skor üretmek.
    """

    if context is None:
        context = {}

    # Tüm modları çalıştır
    res_test = run_faz6_test()
    res_auto = run_faz6_auto()
    res_risk = run_faz6_risk()
    res_edge = run_faz6_edge()
    res_real = run_faz6_real()

    # Skorlara ağırlık verelim
    weights = {
        "test": 0.15,
        "auto": 0.30,
        "risk": 0.15,
        "edge": 0.20,
        "real": 0.20,
    }

    scores = [
        (res_test["score"], weights["test"]),
        (res_auto["score"], weights["auto"]),
        (res_risk["score"], weights["risk"]),
        (res_edge["score"], weights["edge"]),
        (res_real["score"], weights["real"]),
    ]

    total = sum(s * w for s, w in scores)
    total_w = sum(w for _, w in scores)
    balanced_score = round(total / total_w)

    # Ortalama güven
    confs = [
        res_test["confidence"],
        res_auto["confidence"],
        res_risk["confidence"],
        res_edge["confidence"],
        res_real["confidence"],
    ]
    balanced_conf = round(sum(confs) / len(confs), 2)

    return {
        "status": "ok",
        "module": "FAZ-6 BALANCE",
        "score": balanced_score,
        "confidence": balanced_conf,
        "mod": "balance",
        "context": {
            "raw": {
                "test": res_test,
                "auto": res_auto,
                "risk": res_risk,
                "edge": res_edge,
                "real": res_real,
            },
            "input_context": context,
            "mode": mode,
        },
    } 
