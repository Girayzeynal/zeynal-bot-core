"""
FAZ-6 ENGINE - ULTIMATE CORE

Bu dosya FAZ-6'nın tek giriş noktasıdır.

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
            "predictions": [ ... ]  # veya "portfolio"
            ... ek meta alanları ...
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


def _extract_predictions(result: EngineResult | None) -> List[Prediction]:
    """
    Bir FAZ-6 modundan dönen dict içinden tahmin listesini çıkarır.

    Beklenen yapılar:
        result["result"]["predictions"]
        result["result"]["portfolio"]
        result["predictions"]
        result["portfolio"]
    """
    if not isinstance(result, dict):
        return []

    # Önce içteki "result"/"data"
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
    if not isinstance(preds, list):
        return []

    return preds


def _merge_predictions(*lists: List[Prediction]) -> List[Prediction]:
    """Aynı maç + market kombinasyonunu tekilleştirerek listeleri birleştirir."""
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

    Temel mantık:
        - edge önemli (0.7)
        - confidence da önemli (0.3)
        - bazı liglere küçük bonus / ceza
    """
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
    max_picks: int = 6,
    min_edge: float = 0.01,
    min_conf: float = 0.50,
) -> List[Prediction]:
    """
    Ultimate Mode filtresi:
        - edge/conf threshold
        - skora göre sıralama
        - en fazla max_picks adet seçim
    """
    filtered: List[Prediction] = []

    for p in predictions:
        edge = _safe_float(p.get("edge"), 0.0)
        conf = _safe_float(p.get("confidence"), 0.0)

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
    raw_outputs: Dict[str, EngineResult] = {}
    errors: Dict[str, str] = {}

    # 1) Alt modları çalıştır
    try:
        raw_outputs["auto"] = run_faz6_auto()
    except Exception as e:  # noqa: BLE001
        errors["auto"] = f"run_faz6_auto hata: {e!r}"

    try:
        raw_outputs["risk"] = run_faz6_risk()
    except Exception as e:  # noqa: BLE001
        errors["risk"] = f"run_faz6_risk hata: {e!r}"

    try:
        raw_outputs["edge"] = run_faz6_edge()
    except Exception as e:  # noqa: BLE001
        errors["edge"] = f"run_faz6_edge hata: {e!r}"

    try:
        raw_outputs["real"] = run_faz6_real()
    except Exception as e:  # noqa: BLE001
        errors["real"] = f"run_faz6_real hata: {e!r}"

    try:
        raw_outputs["balance"] = run_faz6_balance(context=context, mode="auto")
    except Exception as e:  # noqa: BLE001
        errors["balance"] = f"run_faz6_balance hata: {e!r}"

    # 2) Tahminleri topla
    all_predictions = _merge_predictions(
        _extract_predictions(raw_outputs.get("auto")),
        _extract_predictions(raw_outputs.get("risk")),
        _extract_predictions(raw_outputs.get("edge")),
        _extract_predictions(raw_outputs.get("real")),
        _extract_predictions(raw_outputs.get("balance")),
    )

    # 3) Filtre / sıralama
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
            "source_modes": list(raw_outputs.keys()),
            "total_collected": len(all_predictions),
            "total_selected": len(selected),
            "thresholds": {
                "max_picks": max_picks,
                "min_edge": min_edge,
                "min_conf": min_conf,
            },
            "errors": errors,
        },
    }

    return {
        "status": "ok",
        "mode": "ultimate",
        "result": result_payload,
        "context": context,
        # geri uyum
        "predictions": selected,
        "portfolio": selected,
    }


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
        return run_faz6_test()

    if mode == "auto":
        return run_faz6_auto()

    if mode == "risk":
        return run_faz6_risk()

    if mode == "edge":
        return run_faz6_edge()

    if mode == "real":
        return run_faz6_real()

    if mode == "balance":
        return run_faz6_balance(context=context, mode="auto")

    if mode == "ultimate":
        return _run_faz6_ultimate(context=context)

    return {
        "status": "error",
        "mode": mode,
        "module": "FAZ-6 ENGINE",
        "detail": f"Geçersiz FAZ-6 modu: {mode}",
        "context": context,
  }
