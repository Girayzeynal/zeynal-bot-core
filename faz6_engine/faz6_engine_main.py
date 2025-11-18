"""
FAZ-6 ENGINE - ULTIMATE CORE

Bu dosya FAZ-6'nın tek giriş noktasıdır.

Dış API (main.py ve Telegram için):
    from faz6_engine.faz6_engine_main import run_faz6_engine

Modlar:
    - test
    - auto
    - risk
    - edge
    - real
    - balance
    - ultimate

Tüm modlar FAZ-6 preset mimarisine göre yönetilir.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

# İç modüller
from .faz6_core import (
    get_preset,
    filter_and_rank_games,
)
from .faz6_test import build_test_predictions
from .faz6_real import build_real_predictions
from .faz6_balance import build_balance_predictions
from .faz6_risk import build_risk_predictions


Prediction = Dict[str, Any]
EngineResult = Dict[str, Any]


# ---------------------------------------------------------------------------
# Güvenli float
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Prediction extractor
# ---------------------------------------------------------------------------

def _extract_predictions(result: EngineResult | None) -> List[Prediction]:
    if not isinstance(result, dict):
        return []

    payload = result.get("result") or result.get("data") or result
    if not isinstance(payload, dict):
        return []

    preds = (
        payload.get("predictions")
        or payload.get("portfolio")
        or result.get("predictions")
        or result.get("portfolio")
        or []
    )

    return preds if isinstance(preds, list) else []


# ---------------------------------------------------------------------------
# Merge predictions (unique match + market)
# ---------------------------------------------------------------------------

def _merge_predictions(*lists: List[Prediction]) -> List[Prediction]:
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


# ---------------------------------------------------------------------------
# Ultimate Mode scorer
# ---------------------------------------------------------------------------

def _score_prediction(p: Prediction) -> float:
    edge = _safe_float(p.get("edge"), 0.0)
    conf = _safe_float(p.get("confidence"), 0.0)

    score = edge * 0.7 + conf * 0.3

    league = str(p.get("league") or "").lower()
    if "euroleague" in league or league == "el":
        score *= 1.03
    if "friendly" in league or "hazırlık" in league:
        score *= 0.95

    return score


def _filter_and_rank_predictions(
    predictions: List[Prediction],
    preset_overrides: Dict[str, Any],
) -> List[Prediction]:

    max_picks = int(preset_overrides.get("max_picks") or 6)
    min_edge = float(preset_overrides.get("min_edge") or 0.01)
    min_conf = float(preset_overrides.get("min_conf") or 0.50)

    selected = []
    for p in predictions:
        if _safe_float(p.get("edge")) < min_edge:
            continue
        if _safe_float(p.get("confidence")) < min_conf:
            continue
        selected.append(p)

    selected.sort(key=_score_prediction, reverse=True)
    return selected[:max_picks]


# ---------------------------------------------------------------------------
# Tek tek mod çalıştırıcılar
# ---------------------------------------------------------------------------

def _run_test() -> EngineResult:
    preset = get_preset("test")
    games = build_test_predictions()
    filtered = filter_and_rank_games(games, preset)

    return {
        "status": "ok",
        "mode": "test",
        "result": {
            "predictions": filtered,
            "preset": preset.code,
        },
        "predictions": filtered,
    }


def _run_risk() -> EngineResult:
    preset = get_preset("risk")
    games = build_risk_predictions()
    filtered = filter_and_rank_games(games, preset)

    return {
        "status": "ok",
        "mode": "risk",
        "result": {
            "predictions": filtered,
            "preset": preset.code,
        },
        "predictions": filtered,
    }


def _run_auto() -> EngineResult:
    preset = get_preset("auto")
    games = build_risk_predictions()
    filtered = filter_and_rank_games(games, preset)

    return {
        "status": "ok",
        "mode": "auto",
        "result": {
            "predictions": filtered,
            "preset": preset.code,
        },
        "predictions": filtered,
    }


def _run_balance(context: Dict[str, Any]) -> EngineResult:
    preset = get_preset("balance")
    games = build_balance_predictions(context=context)
    filtered = filter_and_rank_games(games, preset)

    return {
        "status": "ok",
        "mode": "balance",
        "result": {
            "predictions": filtered,
            "preset": preset.code,
        },
        "predictions": filtered,
    }


def _run_real() -> EngineResult:
    preset = get_preset("real")
    games = build_real_predictions()
    filtered = filter_and_rank_games(games, preset)

    return {
        "status": "ok",
        "mode": "real",
        "result": {
            "predictions": filtered,
            "preset": preset.code,
        },
        "predictions": filtered,
    }


# ---------------------------------------------------------------------------
# ULTIMATE MODE
# ---------------------------------------------------------------------------

def _run_ultimate(context: Dict[str, Any]) -> EngineResult:
    outputs = {}
    errors = {}

    try:
        outputs["auto"] = _run_auto()
    except Exception as e:
        errors["auto"] = str(e)

    try:
        outputs["risk"] = _run_risk()
    except Exception as e:
        errors["risk"] = str(e)

    try:
        outputs["real"] = _run_real()
    except Exception as e:
        errors["real"] = str(e)

    try:
        outputs["balance"] = _run_balance(context)
    except Exception as e:
        errors["balance"] = str(e)

    all_preds = _merge_predictions(
        _extract_predictions(outputs.get("auto")),
        _extract_predictions(outputs.get("risk")),
        _extract_predictions(outputs.get("real")),
        _extract_predictions(outputs.get("balance")),
    )

    overrides = {
        "max_picks": context.get("ultimate_max_picks", 6),
        "min_edge": context.get("ultimate_min_edge", 0.01),
        "min_conf": context.get("ultimate_min_conf", 0.50),
    }

    best = _filter_and_rank_predictions(all_preds, overrides)

    return {
        "status": "ok",
        "mode": "ultimate",
        "result": {
            "predictions": best,
            "source_modes": list(outputs.keys()),
            "errors": errors,
        },
        "predictions": best,
    }


# ---------------------------------------------------------------------------
# ANA GİRİŞ
# ---------------------------------------------------------------------------

def run_faz6_engine(mode: str = "auto", context: Optional[Dict[str, Any]] = None) -> EngineResult:
    if context is None:
        context = {}

    mode = (mode or "auto").lower().strip()
    context["requested_mode"] = mode

    if mode == "test":
        return _run_test()

    if mode == "risk":
        return _run_risk()

    if mode == "auto":
        return _run_auto()

    if mode == "balance":
        return _run_balance(context)

    if mode == "real":
        return _run_real()

    if mode == "ultimate":
        return _run_ultimate(context)

    return {
        "status": "error",
        "mode": mode,
        "detail": f"Geçersiz mod: {mode}",
        "context": context,
    }
