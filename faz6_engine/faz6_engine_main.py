"""
FAZ-6 ENGINE - ANA GİRİŞ NOKTASI

Dış API (main.py ve Telegram için):
    from faz6_engine import run_faz6_engine

Kullanılabilir modlar:
    - test
    - auto
    - risk
    - edge
    - real
    - balance
    - ultimate   (multi-mod fusion)

Standart dönüş formatı:
    {
        "status": "ok" | "error",
        "mode": "...",
        "result": {
            "predictions": [ ... ],
            "portfolio": [ ... ],
            "meta": {...},
        },
        "context": {...},

        # Geriye dönük uyum için:
        "predictions": [...],
        "portfolio": [...],
    }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .faz6_core import (
    Prediction,
    EngineResult,
    safe_float,
    get_preset,
    normalize_engine_result,
)
from .faz6_test import run_faz6_test
from .faz6_auto import run_faz6_auto
from .faz6_risk import run_faz6_risk
from .faz6_edge import run_faz6_edge
from .faz6_real import run_faz6_real
from .faz6_balance import run_faz6_balance


# ---------------------------------------------------------------------------
#  Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _extract_predictions(raw: EngineResult | None) -> List[Prediction]:
    if not isinstance(raw, dict):
        return []

    result_block = raw.get("result")
    if isinstance(result_block, dict):
        preds = result_block.get("predictions") or result_block.get("portfolio")
        if isinstance(preds, list):
            return preds

    preds = raw.get("predictions") or raw.get("portfolio")
    if isinstance(preds, list):
        return preds

    return []


def _merge_predictions(*lists: List[Prediction]) -> List[Prediction]:
    """
    Aynı maç + market kombinasyonunu tekilleştirerek listeleri birleştirir.
    """
    merged: List[Prediction] = []
    seen: set[Tuple[str, str]] = set()

    for lst in lists:
        if not lst:
            continue
        for p in lst:
            pid = str(p.get("id") or p.get("match_id") or p.get("code") or "")
            market = str(p.get("market") or p.get("type") or "")
            key = (pid, market)
            if key in seen:
                continue
            seen.add(key)
            merged.append(p)

    return merged


def _score_prediction(p: Prediction) -> float:
    """
    Ultimate Mode skor fonksiyonu.
    """
    edge = safe_float(p.get("edge"), 0.0)
    conf = safe_float(p.get("confidence") or p.get("guven"), 0.0)

    score = edge * 0.7 + conf * 0.3

    league = str(p.get("league") or "").lower()
    if "euroleague" in league or league == "el":
        score *= 1.03
    if "friendly" in league or "hazırlık" in league:
        score *= 0.95

    return score


def _filter_and_rank_for_ultimate(
    predictions: List[Prediction],
    context: Dict[str, Any],
) -> List[Prediction]:
    preset = get_preset("ultimate")

    max_picks = int(context.get("ultimate_max_picks") or preset.max_picks or 6)
    min_edge = float(context.get("ultimate_min_edge") or preset.min_edge)
    min_conf = float(context.get("ultimate_min_conf") or preset.min_confidence)

    filtered: List[Prediction] = []

    for p in predictions:
        edge = safe_float(p.get("edge"), 0.0)
        conf = safe_float(p.get("confidence") or p.get("guven"), 0.0)

        if edge < min_edge:
            continue
        if conf < min_conf:
            continue

        filtered.append(p)

    filtered.sort(key=_score_prediction, reverse=True)
    return filtered[:max_picks]


# ---------------------------------------------------------------------------
#  FAZ-6 ULTIMATE MODE
# ---------------------------------------------------------------------------

def _run_faz6_ultimate(context: Dict[str, Any]) -> EngineResult:
    """
    Ultimate Mode:
        - auto, risk, edge, real, balance modlarının çıktısını toplar,
        - tekilleştirir,
        - skorlar ve en iyi N seçimi döner.
    """
    auto_res = run_faz6_auto(context=context)
    risk_res = run_faz6_risk(context=context)
    edge_res = run_faz6_edge(context=context)
    real_res = run_faz6_real(context=context)
    balance_res = run_faz6_balance(context=context)

    all_predictions = _merge_predictions(
        _extract_predictions(auto_res),
        _extract_predictions(risk_res),
        _extract_predictions(edge_res),
        _extract_predictions(real_res),
        _extract_predictions(balance_res),
    )

    selected = _filter_and_rank_for_ultimate(all_predictions, context)

    meta: Dict[str, Any] = {
        "source_modes": ["auto", "risk", "edge", "real", "balance"],
        "total_collected": len(all_predictions),
        "total_selected": len(selected),
    }

    return normalize_engine_result(
        mode="ultimate",
        predictions=selected,
        context=context,
        meta=meta,
    )


# ---------------------------------------------------------------------------
#  ANA GİRİŞ NOKTASI
# ---------------------------------------------------------------------------

def run_faz6_engine(
    mode: str = "auto",
    context: Optional[Dict[str, Any]] = None,
) -> EngineResult:
    """
    FAZ-6 ana motoru - tüm modları tek çatıdan yönetir.

    Kullanılabilir Modlar:
        test / auto / risk / edge / real / balance / ultimate
    """
    if context is None:
        context = {}

    mode = (mode or "auto").lower().strip()
    context["requested_mode"] = mode

    if mode == "test":
        return run_faz6_test(context=context)

    if mode == "auto":
        return run_faz6_auto(context=context)

    if mode == "risk":
        return run_faz6_risk(context=context)

    if mode == "edge":
        return run_faz6_edge(context=context)

    if mode == "real":
        return run_faz6_real(context=context)

    if mode == "balance":
        return run_faz6_balance(context=context)

    if mode == "ultimate":
        return _run_faz6_ultimate(context=context)

    # Geçersiz mod
    return normalize_engine_result(
        mode=mode,
        predictions=[],
        context=context,
        status="error",
        meta={"module": "FAZ-6 ENGINE"},
        detail=f"Geçersiz FAZ-6 modu: {mode}",
    )
