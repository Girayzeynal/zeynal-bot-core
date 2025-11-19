"""
FAZ-6 ENGINE – ANA GİRİŞ NOKTASI
Bu motor tüm FAZ-6 modlarını tek çatıdan yönetir.

Telegram ve main.py tarafından çağrılır:
    from faz6_engine.faz6_engine_main import run_faz6_engine
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

# ------------------------------------------------------
# DOĞRU IMPORT BLOĞU (FAZ-6 MİMARİSİNE %100 UYUMLU)
# ------------------------------------------------------

# Core sadece preset + filtre + format içerir
from .faz6_core import (
    get_preset,
    filter_and_rank_games,
    format_pick_for_telegram,
)

# Her modun kendi motoru kendi dosyasında
from .faz6_test import run_faz6_test
from .faz6_auto import run_faz6_auto
from .faz6_risk import run_faz6_risk
from .faz6_edge import run_faz6_edge
from .faz6_real import run_faz6_real
from .faz6_balance import run_faz6_balance


Prediction = Dict[str, Any]
EngineResult = Dict[str, Any]


# ------------------------------------------------------
#  Yardımcı Fonksiyonlar
# ------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except:
        return default


def _extract_predictions_from_raw(raw: EngineResult | None) -> List[Prediction]:
    """
    FAZ-6 mod çıkışlarından tahmin listesini çıkarır.
    Yeni / eski formatların hepsini destekler.
    """
    if not isinstance(raw, dict):
        return []

    payload = raw.get("result") or raw.get("data")
    if isinstance(payload, dict):
        preds = payload.get("predictions") or payload.get("portfolio")
        if isinstance(preds, list):
            return preds

    preds = raw.get("predictions") or raw.get("portfolio")
    if isinstance(preds, list):
        return preds

    return []


def _normalize_engine_result(raw: EngineResult | None, fallback_mode: str) -> EngineResult:
    """
    Tüm FAZ-6 modlarını tek, standart forma çevirir.
    """
    if raw is None:
        return {
            "status": "error",
            "mode": fallback_mode,
            "detail": "Mod çıktı üretmedi (None).",
            "result": {"predictions": [], "portfolio": [], "meta": {}},
            "context": {},
            "predictions": [],
            "portfolio": [],
        }

    if not isinstance(raw, dict):
        return {
            "status": "error",
            "mode": fallback_mode,
            "detail": f"Beklenmeyen tip: {type(raw).__name__}",
            "result": {
                "predictions": [],
                "portfolio": [],
                "meta": {"raw": repr(raw)},
            },
            "context": {},
            "predictions": [],
            "portfolio": [],
        }

    mode = str(raw.get("mode") or fallback_mode)
    status = str(raw.get("status") or "ok")
    preds = _extract_predictions_from_raw(raw)

    ml_meta = {}
    memory_snapshot = {}
    meta = {}

    result_block = raw.get("result")
    if isinstance(result_block, dict):
        ml_meta = result_block.get("ml_meta") or {}
        memory_snapshot = result_block.get("memory_snapshot") or {}
        meta = result_block.get("meta") or {}

    ml_meta = ml_meta or raw.get("ml_meta") or {}
    memory_snapshot = memory_snapshot or raw.get("memory_snapshot") or {}

    normalized_result = {"predictions": preds, "portfolio": preds}

    if ml_meta:
        normalized_result["ml_meta"] = ml_meta
    if memory_snapshot:
        normalized_result["memory_snapshot"] = memory_snapshot
    if meta:
        normalized_result["meta"] = meta

    normalized = {
        "status": status,
        "mode": mode,
        "result": normalized_result,
        "context": raw.get("context") or {},
        "predictions": preds,
        "portfolio": preds,
    }

    if "detail" in raw:
        normalized["detail"] = raw["detail"]

    return normalized


def _merge_predictions(*lists: List[Prediction]) -> List[Prediction]:
    """
    Tüm modlardan gelen tahminleri tek listeye toplar, tekrarları kaldırır.
    """
    merged: List[Prediction] = []
    seen = set()

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
    edge = _safe_float(p.get("edge"), 0.0)
    conf = _safe_float(p.get("confidence") or p.get("guven"), 0.0)
    score = edge * 0.7 + conf * 0.3

    league = str(p.get("league") or "").lower()
    if "euroleague" in league or league == "el":
        score *= 1.03
    if "friendly" in league:
        score *= 0.95

    return score


def _filter_and_rank_predictions(predictions: List[Prediction],
                                 max_picks: int = 6,
                                 min_edge: float = 0.01,
                                 min_conf: float = 0.50) -> List[Prediction]:

    filtered = []
    for p in predictions:
        if _safe_float(p.get("edge")) < min_edge:
            continue
        if _safe_float(p.get("confidence") or p.get("guven")) < min_conf:
            continue
        filtered.append(p)

    filtered.sort(key=_score_prediction, reverse=True)
    return filtered[:max_picks]


# ------------------------------------------------------
#  ULTIMATE MODE
# ------------------------------------------------------

def _run_faz6_ultimate(context: Dict[str, Any]) -> EngineResult:

    raw_auto = _normalize_engine_result(run_faz6_auto(), "auto")
    raw_risk = _normalize_engine_result(run_faz6_risk(), "risk")
    raw_edge = _normalize_engine_result(run_faz6_edge(), "edge")
    raw_real = _normalize_engine_result(run_faz6_real(), "real")
    raw_balance = _normalize_engine_result(
        run_faz6_balance(context=context, mode="auto"),
        "balance",
    )

    all_predictions = _merge_predictions(
        raw_auto["result"]["predictions"],
        raw_risk["result"]["predictions"],
        raw_edge["result"]["predictions"],
        raw_real["result"]["predictions"],
        raw_balance["result"]["predictions"],
    )

    selected = _filter_and_rank_predictions(
        all_predictions,
        max_picks=int(context.get("ultimate_max_picks") or 6),
        min_edge=float(context.get("ultimate_min_edge") or 0.01),
        min_conf=float(context.get("ultimate_min_conf") or 0.50),
    )

    return {
        "status": "ok",
        "mode": "ultimate",
        "result": {
            "predictions": selected,
            "portfolio": selected,
            "meta": {
                "source_modes": ["auto", "risk", "edge", "real", "balance"],
                "total_collected": len(all_predictions),
                "total_selected": len(selected),
            },
        },
        "context": context,
        "predictions": selected,
        "portfolio": selected,
    }


# ------------------------------------------------------
#  ANA GİRİŞ NOKTASI
# ------------------------------------------------------

def run_faz6_engine(mode: str = "auto",
                    context: Optional[Dict[str, Any]] = None) -> EngineResult:

    if context is None:
        context = {}

    mode = (mode or "auto").lower().strip()
    context["requested_mode"] = mode

    if mode == "test":
        return _normalize_engine_result(run_faz6_test(), "test")

    if mode == "auto":
        return _normalize_engine_result(run_faz6_auto(), "auto")

    if mode == "risk":
        return _normalize_engine_result(run_faz6_risk(), "risk")

    if mode == "edge":
        return _normalize_engine_result(run_faz6_edge(), "edge")

    if mode == "real":
        return _normalize_engine_result(run_faz6_real(), "real")

    if mode == "balance":
        return _normalize_engine_result(
            run_faz6_balance(context=context, mode="auto"),
            "balance",
        )

    if mode == "ultimate":
        return _run_faz6_ultimate(context=context)

    return {
        "status": "error",
        "mode": mode,
        "detail": f"Geçersiz mod: {mode}",
        "result": {"predictions": [], "portfolio": [], "meta": {}},
        "context": context,
        "predictions": [],
        "portfolio": [],
    } 
