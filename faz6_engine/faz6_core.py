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
EngineResult = Dict[str, Any]
Memory = Dict[str, Any]


# ------------------------------------------------
# Ortak çıktı wrapper
# ------------------------------------------------

def _wrap_result(
    mode: str,
    predictions: List[Prediction],
    ml_meta: Dict[str, Any],
    memory_before: Memory,
    memory_after_key: str,
    context: Dict[str, Any] | None = None,
    extra_result: Dict[str, Any] | None = None,
) -> EngineResult:
    """
    Tüm FAZ-6 modları için standart çıktı.
    main.py, faz6_coupon, faz6_balance ve ultimate ile uyumlu.
    """
    if context is None:
        context = {}

    # Hafızaya basit snapshot kaydı
    try:
        mem = dict(memory_before)
        mem[memory_after_key] = predictions
        save_memory(mem)
    except Exception:
        mem = memory_before

    result_body: Dict[str, Any] = {
        "predictions": predictions,
        "portfolio": predictions,
        "ml_meta": ml_meta,
    }
    if extra_result:
        result_body.update(extra_result)

    return {
        "status": "ok",
        "mode": mode,
        "result": result_body,
        "context": context,
        # geri uyum
        "predictions": predictions,
        "portfolio": predictions,
    }


# ------------------------------------------------
# AUTO MODE – genel otomatik portföy
# ------------------------------------------------

def _build_auto_predictions(memory: Memory) -> List[Prediction]:
    """
    Auto modu için temel prediction seti.
    Hafızadaki son risk/edge bilgilerini karıştırır.
    """
    base: List[Prediction] = []

    last_risk = memory.get("risk_last", [])
    last_edge = memory.get("edge_last", [])

    # Risk'ten güvenli parçalar
    for p in last_risk[:5]:
        q = dict(p)
        q.setdefault("tag", "risk_carry")
        base.append(q)

    # Edge'den yüksek edge'li olanlar
    for p in last_edge[:5]:
        if p.get("edge", 0) >= 0.05:
            q = dict(p)
            q.setdefault("tag", "edge_boost")
            base.append(q)

    # Hafıza boşsa test datasını kullan
    if not base:
        base = build_test_predictions(memory=None)

    return base


def run_faz6_auto(context: Dict[str, Any] | None = None) -> EngineResult:
    memory_before = load_memory()
    raw = _build_auto_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="auto")
    optimized = optimize_predictions(raw, ml_meta, mode="auto")

    return _wrap_result(
        mode="auto",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="auto_last",
        context=context,
    )


# ------------------------------------------------
# TEST MODE
# ------------------------------------------------

def run_faz6_test(context: Dict[str, Any] | None = None) -> EngineResult:
    memory_before = load_memory()
    raw = build_test_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="test")
    optimized = optimize_predictions(raw, ml_meta, mode="test")

    return _wrap_result(
        mode="test",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="test_last",
        context=context,
    )


# ------------------------------------------------
# RISK MODE
# ------------------------------------------------

def run_faz6_risk(context: Dict[str, Any] | None = None) -> EngineResult:
    memory_before = load_memory()
    raw = build_risk_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="risk")
    optimized = optimize_predictions(raw, ml_meta, mode="risk", risk=True)

    return _wrap_result(
        mode="risk",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="risk_last",
        context=context,
    )


# ------------------------------------------------
# EDGE MODE
# ------------------------------------------------

def run_faz6_edge(context: Dict[str, Any] | None = None) -> EngineResult:
    memory_before = load_memory()
    raw = build_edge_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="edge")
    optimized = optimize_predictions(raw, ml_meta, mode="edge", aggressive=True)

    return _wrap_result(
        mode="edge",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="edge_last",
        context=context,
    )


# ------------------------------------------------
# REAL MODE (Gerçek zaman odaklı)
# ------------------------------------------------

def run_faz6_real(context: Dict[str, Any] | None = None) -> EngineResult:
    memory_before = load_memory()
    raw = build_real_predictions(memory_before)

    ml_meta = evaluate_predictions(raw, memory_before, mode="real")
    optimized = optimize_predictions(raw, ml_meta, mode="real", realtime=True)

    return _wrap_result(
        mode="real",
        predictions=optimized,
        ml_meta=ml_meta,
        memory_before=memory_before,
        memory_after_key="real_last",
        context=context,
    )
