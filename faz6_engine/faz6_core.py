# ================================================================
#                      FAZ-6 ÇEKİRDEK (CORE)
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any

from .memory_unit import load_memory, save_memory
from .ml_brain import evaluate_predictions
from .optimizer import optimize_predictions

from .faz6_test import build_test_predictions
from .faz6_risk import build_risk_predictions
from .faz6_edge import build_edge_predictions
from .faz6_real import build_real_predictions


Prediction = Dict[str, Any]


# ------------------------------------------------
# Ortak yardımcı: standart çıktı
# ------------------------------------------------

def _build_output(
    mode: str,
    predictions: List[Prediction],
    ml_meta: Dict[str, Any],
    memory_before: Dict[str, Any],
    memory_after_key: str,
) -> Dict[str, Any]:
    # Hafızaya kaydet
    save_memory({memory_after_key: predictions})

    return {
        "mode": mode,
        "predictions": predictions,
        "ml_meta": ml_meta,
        "memory_snapshot": memory_before,
    }


# ------------------------------------------------
# AUTO MODE – FAZ-6 genel otomatik portföy
# ------------------------------------------------

def _build_auto_predictions(memory: Dict[str, Any]) -> List[Prediction]:
    """
    Auto modu için temel prediction seti:
    Hafızadaki son risk/edge bilgilerini harmanlayarak
    dengeli ama fırsatçı bir liste üretir.
    """
    base: List[Prediction] = []

    last_risk = memory.get("risk_last", [])
    last_edge = memory.get("edge_last", [])

    # Önce risk tarafında güvenli olunanlardan seç
    for p in last_risk[:5]:
        q = dict(p)
        q.setdefault("tag", "risk_carry")
        base.append(q)

    # Sonra edge tarafında yüksek edge'li olanlardan ekle
    for p in last_edge[:5]:
        if p.get("edge", 0) >= 0.05:  # %5 ve üzeri edge
            q = dict(p)
            q.setdefault("tag", "edge_boost")
            base.append(q)

    # Eğer hafızada hiç veri yoksa test datasından doldur
    if not base:
        base = build_test_predictions(memory=None)

    return base


def run_faz6_auto() -> Dict[str, Any]:
    memory_before = load_memory()
    raw = _build_auto_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="auto")
    optimized = optimize_predictions(raw, ml_meta, mode="auto")

    return _build_output(
        mode="auto",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="auto_last",
    )


# ------------------------------------------------
# TEST MODE
# ------------------------------------------------

def run_faz6_test() -> Dict[str, Any]:
    memory_before = load_memory()
    raw = build_test_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="test")
    optimized = optimize_predictions(raw, ml_meta, mode="test")

    return _build_output(
        mode="test",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="test_last",
    )


# ------------------------------------------------
# RISK MODE
# ------------------------------------------------

def run_faz6_risk() -> Dict[str, Any]:
    memory_before = load_memory()
    raw = build_risk_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="risk")
    optimized = optimize_predictions(raw, ml_meta, mode="risk", risk=True)

    return _build_output(
        mode="risk",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="risk_last",
    )


# ------------------------------------------------
# EDGE MODE
# ------------------------------------------------

def run_faz6_edge() -> Dict[str, Any]:
    memory_before = load_memory()
    raw = build_edge_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="edge")
    optimized = optimize_predictions(raw, ml_meta, mode="edge", aggressive=True)

    return _build_output(
        mode="edge",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="edge_last",
    )


# ------------------------------------------------
# REAL MODE (Gerçek zaman odaklı)
# ------------------------------------------------

def run_faz6_real() -> Dict[str, Any]:
    memory_before = load_memory()
    raw = build_real_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="real")
    optimized = optimize_predictions(raw, ml_meta, mode="real", realtime=True)

    return _build_output(
        mode="real",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="real_last",
    )
