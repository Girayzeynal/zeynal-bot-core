"""
FAZ-6 ENGINE - ANA GİRİŞ NOKTASI

Dış API (main.py ve Telegram için):
    from faz6_engine.faz6_engine_main import run_faz6_engine

Kullanılabilir modlar:
    - test
    - auto
    - risk
    - edge
    - real
    - balance
    - ultimate   (FAZ-6 Ultimate Mode)

Standart dönüş formatı:
    {
        "status": "ok" | "error",
        "mode": "...",
        "result": {
            "predictions": [ ... ],   # veya "portfolio"
            "portfolio": [ ... ],
            "ml_meta": {...},         # varsa
            "memory_snapshot": {...}, # varsa
            "meta": {...},            # varsa
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
    run_faz6_test,
    run_faz6_auto,
    run_faz6_risk,
    run_faz6_edge,
    run_faz6_real,
)
from .faz6_balance import run_faz6_balance

Prediction = Dict[str, Any]
EngineResult = Dict[str, Any]


# ---------------------------------------------------------------------------
#  Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_predictions_from_raw(raw: EngineResult | None) -> List[Prediction]:
    """
    Eski/Yeni tüm FAZ-6 mod çıktılarından tahmin listesini çıkar.
    """
    if not isinstance(raw, dict):
        return []

    # Yeni stil: içte result / data
    payload = raw.get("result") or raw.get("data")
    if isinstance(payload, dict):
        preds = payload.get("predictions") or payload.get("portfolio")
        if isinstance(preds, list):
            return preds

    # Eski stil: direkt top-level
    preds = raw.get("predictions") or raw.get("portfolio")
    if isinstance(preds, list):
        return preds

    return []


def _normalize_engine_result(raw: EngineResult | None, fallback_mode: str) -> EngineResult:
    """
    Her FAZ-6 modundan gelen çıktıyı tek, standart forma çevirir.

    Çıktı formatı:
        {
            "status": "ok" | "error",
            "mode": "...",
            "result": {
                "predictions": [...],
                "portfolio": [...],
                "ml_meta": {...}  # varsa
                "memory_snapshot": {...},  # varsa
                "meta": {...},  # varsa
            },
            "context": {...},  # varsa
            # geri uyum:
            "predictions": [...],
            "portfolio": [...],
        }
    """
    if raw is None:
        return {
            "status": "error",
            "mode": fallback_mode,
            "detail": "FAZ-6 modundan None döndü.",
            "result": {
                "predictions": [],
                "portfolio": [],
                "meta": {},
            },
            "context": {},
            "predictions": [],
            "portfolio": [],
        }

    if not isinstance(raw, dict):
        return {
            "status": "error",
            "mode": fallback_mode,
            "detail": f"FAZ-6 modundan beklenmeyen tip döndü: {type(raw).__name__}",
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

    # ml_meta & memory_snapshot hem eski hem yeni formatta aranıyor
    ml_meta: Dict[str, Any] = {}
    memory_snapshot: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}

    result_block = raw.get("result")
    if isinstance(result_block, dict):
        ml_meta = result_block.get("ml_meta") or {}
        memory_snapshot = result_block.get("memory_snapshot") or {}
        meta = result_block.get("meta") or {}

    # eski format alanları
    if not ml_meta:
        ml_meta = raw.get("ml_meta") or {}
    if not memory_snapshot:
        memory_snapshot = raw.get("memory_snapshot") or {}

    context = raw.get("context") or {}

    normalized_result: Dict[str, Any] = {
        "predictions": preds,
        "portfolio": preds,
    }

    if ml_meta:
        normalized_result["ml_meta"] = ml_meta
    if memory_snapshot:
        normalized_result["memory_snapshot"] = memory_snapshot
    if meta:
        normalized_result["meta"] = meta

    normalized: EngineResult = {
        "status": status,
        "mode": mode,
        "result": normalized_result,
        "context": context,
        # geri uyumluluk:
        "predictions": preds,
        "portfolio": preds,
    }

    # error durumunda detail alanını koru
    if "detail" in raw and "detail" not in normalized:
        normalized["detail"] = raw["detail"]

    return normalized


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
    edge = _safe_float(p.get("edge"), 0.0)
    conf = _safe_float(p.get("confidence") or p.get("guven"), 0.0)

    score = edge * 0.7 + conf * 0.3

    league = str(p.get("league") or "").lower()
    if "euroleague" in league or league == "el":
        score *= 1.03
    if "friendly" in league or "hazırlık" in league:
        score *= 0.95

    return score


def _filter_and_rank_predictions(
    predictions: List[Prediction],
    max_picks: int = 6,
    min_edge: float = 0.01,
    min_conf: float = 0.50,
) -> List[Prediction]:
    """
    Ultimate Mode filtresi:
        - edge / confidence eşikleri
        - skora göre sıralama
        - en fazla max_picks adet seçim
    """
    filtered: List[Prediction] = []

    for p in predictions:
        edge = _safe_float(p.get("edge"), 0.0)
        conf = _safe_float(p.get("confidence") or p.get("guven"), 0.0)

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

    max_picks = int(context.get("ultimate_max_picks") or 6)
    min_edge = float(context.get("ultimate_min_edge") or 0.01)
    min_conf = float(context.get("ultimate_min_conf") or 0.50)

    selected = _filter_and_rank_predictions(
        all_predictions,
        max_picks=max_picks,
        min_edge=min_edge,
        min_conf=min_conf,
    )

    result_payload: Dict[str, Any] = {
        "predictions": selected,
        "portfolio": selected,
        "meta": {
            "source_modes": ["auto", "risk", "edge", "real", "balance"],
            "total_collected": len(all_predictions),
            "total_selected": len(selected),
            "thresholds": {
                "max_picks": max_picks,
                "min_edge": min_edge,
                "min_conf": min_conf,
            },
        },
    }

    final: EngineResult = {
        "status": "ok",
        "mode": "ultimate",
        "result": result_payload,
        "context": context,
        "predictions": selected,
        "portfolio": selected,
    }

    return final


# ---------------------------------------------------------------------------
#  ANA GİRİŞ NOKTASI
# ---------------------------------------------------------------------------

def run_faz6_engine(mode: str = "auto", context: Optional[Dict[str, Any]] = None) -> EngineResult:
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
        "module": "FAZ-6 ENGINE",
        "detail": f"Geçersiz FAZ-6 modu: {mode}",
        "result": {
            "predictions": [],
            "portfolio": [],
            "meta": {},
        },
        "context": context,
        "predictions": [],
        "portfolio": [],
    }
