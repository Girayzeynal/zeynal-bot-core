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

Dönen veri formatı (standart):
    {
        "status": "ok" | "error",
        "mode": "auto" | "risk" | ...,
        "result": {
            "predictions": [ ... ],   # veya "portfolio"
            ... ek meta alanları ...
        },
        "context": {...}
    }

Bu format, main.py içindeki:
    - format_faz6_message(...)
    - build_coupon_message(...)
ile %100 uyumludur.
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


# ---------------------------------------------------------------------------
#  Yardımcı tipler
# ---------------------------------------------------------------------------

Prediction = Dict[str, Any]
EngineResult = Dict[str, Any]


# ---------------------------------------------------------------------------
#  Ortak yardımcı fonksiyonlar
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
        veya
        result["result"]["portfolio"]
    """
    if not isinstance(result, dict):
        return []

    payload = result.get("result") or result.get("data") or {}
    if not isinstance(payload, dict):
        return []

    preds = payload.get("predictions") or payload.get("portfolio") or []
    if not isinstance(preds, list):
        return []

    return preds


def _merge_predictions(*lists: List[Prediction]) -> List[Prediction]:
    """
    Birden fazla prediction listesini birleştirir.
    Aynı maç + market kombinasyonunu tekilleştirir.
    """
    merged: List[Prediction] = []
    seen: set[Tuple[str, str]] = set()

    for lst in lists:
        if not lst:
            continue
        for p in lst:
            pid = str(p.get("id") or p.get("match_id") or "")
            market = str(p.get("market") or "")
            key = (pid, market)
            if key in seen:
                continue
            seen.add(key)
            merged.append(p)

    return merged


def _score_prediction(p: Prediction) -> float:
    """
    Ultimate Mode için skor fonksiyonu.
    Temel mantık:
        - edge önemli (0.7 ağırlık)
        - confidence da önemli (0.3 ağırlık)
        - bazı liglere küçük bonus / ceza uygulanabilir.
    """
    edge = _safe_float(p.get("edge"), 0.0)
    conf = _safe_float(p.get("confidence"), 0.0)

    score = edge * 0.7 + conf * 0.3

    league = str(p.get("league") or "").lower()
    if "euroleague" in league:
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
    Ultimate Mode seçim filtresi:
        - edge ve confidence threshold
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
#  FAZ-6 ULTIMATE MODE (üst beyin)
# ---------------------------------------------------------------------------

def _run_faz6_ultimate(context: Dict[str, Any]) -> EngineResult:
    """
    FAZ-6 Ultimate Mode:
        - auto, risk, edge, real, balance modlarından çıkan tahminleri toplar
        - tekilleştirir
        - skorlar ve en iyi N tanesini seçer
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
        # balance modu context ile çalışıyor
        raw_outputs["balance"] = run_faz6_balance(context=context, mode="auto")
    except Exception as e:  # noqa: BLE001
        errors["balance"] = f"run_faz6_balance hata: {e!r}"

    # 2) Tüm tahminleri topla
    all_predictions = _merge_predictions(
        _extract_predictions(raw_outputs.get("auto")),
        _extract_predictions(raw_outputs.get("risk")),
        _extract_predictions(raw_outputs.get("edge")),
        _extract_predictions(raw_outputs.get("real")),
        _extract_predictions(raw_outputs.get("balance")),
    )

    # 3) Filtre + sıralama + seçim
    max_picks = int(context.get("ultimate_max_picks") or 6)
    min_edge = float(context.get("ultimate_min_edge") or 0.01)
    min_conf = float(context.get("ultimate_min_conf") or 0.50)

    selected = _filter_and_rank_predictions(
        all_predictions,
        max_picks=max_picks,
        min_edge=min_edge,
        min_conf=min_conf,
    )

    # 4) Sonuç objesini oluştur
    result_payload: Dict[str, Any] = {
        "predictions": selected,
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

    # Aynı anda "portfolio" alanı da doldurulsun (bazı çağrılar bunu kullanıyor olabilir)
    result_payload["portfolio"] = selected

    return {
        "status": "ok",
        "mode": "ultimate",
        "result": result_payload,
        "context": context,
    }


# ---------------------------------------------------------------------------
#  ANA GİRİŞ NOKTASI: run_faz6_engine
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

    # --- Standart modlar ---

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
        # Balance modu AUTO modunda çalışır ve context taşır
        return run_faz6_balance(context=context, mode="auto")

    # --- ULTIMATE MODE ---

    if mode == "ultimate":
        return _run_faz6_ultimate(context=context)

    # --- Geçersiz mod ---

    return {
        "status": "error",
        "mode": mode,
        "module": "FAZ-6 ENGINE",
        "detail": f"Geçersiz FAZ-6 modu: {mode}",
        "context": context,
    }


__all__ = ["run_faz6_engine"]
