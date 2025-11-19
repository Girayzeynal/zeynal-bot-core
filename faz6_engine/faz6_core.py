"""
FAZ-6 Core Helpers
------------------
Modlar arası paylaşılan çekirdek:
- Tipler
- Preset yapısı
- Filtre + sıralama
- Normalleştirilmiş çıktı formatı
- Telegram format helper
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional

Prediction = Dict[str, Any]
EngineResult = Dict[str, Any]


# ======================================================
#  PRESET YAPISI
# ======================================================

@dataclass
class Faz6Preset:
    code: str
    title: str
    min_confidence: float
    min_edge: float
    max_picks: Optional[int] = None


# Varsayılan preset’ler
PRESETS: Dict[str, Faz6Preset] = {
    "test": Faz6Preset(
        code="test",
        title="FAZ-6 TEST PRESET",
        min_confidence=0.55,
        min_edge=0.03,
        max_picks=5,
    ),
    "auto": Faz6Preset(
        code="auto",
        title="FAZ-6 AUTO PRESET",
        min_confidence=0.58,
        min_edge=0.04,
        max_picks=10,
    ),
    "risk": Faz6Preset(
        code="risk",
        title="FAZ-6 RISK PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=7,
    ),
    "edge": Faz6Preset(
        code="edge",
        title="FAZ-6 EDGE PRESET",
        min_confidence=0.62,
        min_edge=0.06,
        max_picks=8,
    ),
    "real": Faz6Preset(
        code="real",
        title="FAZ-6 REAL PRESET",
        min_confidence=0.57,
        min_edge=0.035,
        max_picks=None,
    ),
    "balance": Faz6Preset(
        code="balance",
        title="FAZ-6 BALANCE PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=12,
    ),
    "ultimate": Faz6Preset(
        code="ultimate",
        title="FAZ-6 ULTIMATE PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=6,
    ),
}


def get_preset(code: str) -> Faz6Preset:
    """
    Preset seçici.
    Bilinmeyen kod gelirse 'balance' preset'i döner.
    """
    code = (code or "").lower().strip()
    return PRESETS.get(code, PRESETS["balance"])


# ======================================================
#  YARDIMCI FONKSİYONLAR
# ======================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def filter_and_rank_games(
    games: Iterable[Prediction],
    preset: Faz6Preset,
) -> List[Prediction]:
    """
    Ortak FAZ-6 filtreleme:
        - confidence / guven >= preset.min_confidence
        - edge >= preset.min_edge
        - confidence DESC + edge DESC sıralama
        - max_picks uygula (varsa)
    """
    filtered: List[Prediction] = []

    for game in games:
        conf = safe_float(game.get("confidence", game.get("guven", 0.0)))
        edge = safe_float(game.get("edge", 0.0))

        if conf < preset.min_confidence:
            continue
        if edge < preset.min_edge:
            continue

        filtered.append(game)

    filtered.sort(
        key=lambda g: (
            safe_float(g.get("confidence", g.get("guven", 0.0))),
            safe_float(g.get("edge", 0.0)),
        ),
        reverse=True,
    )

    if preset.max_picks and len(filtered) > preset.max_picks:
        filtered = filtered[: preset.max_picks]

    return filtered


def normalize_engine_result(
    mode: str,
    predictions: List[Prediction],
    context: Optional[Dict[str, Any]] = None,
    *,
    status: str = "ok",
    meta: Optional[Dict[str, Any]] = None,
    detail: Optional[str] = None,
) -> EngineResult:
    """
    Tüm modlar için standart çıktı formatı.

    {
        "status": "ok" | "error",
        "mode": "...",
        "result": {
            "predictions": [...],
            "portfolio": [...],
            "meta": {...},
        },
        "context": {...},
        # geri uyum:
        "predictions": [...],
        "portfolio": [...],
    }
    """
    if context is None:
        context = {}
    if meta is None:
        meta = {}

    result_block: Dict[str, Any] = {
        "predictions": predictions,
        "portfolio": predictions,
        "meta": meta,
    }

    out: EngineResult = {
        "status": status,
        "mode": str(mode),
        "result": result_block,
        "context": context,
        "predictions": predictions,
        "portfolio": predictions,
    }

    if detail:
        out["detail"] = detail

    return out


# ======================================================
#  TELEGRAM FORMAT HELPER
# ======================================================

def format_pick_for_telegram(game: Prediction) -> str:
    """
    Telegram için tek maç formatlayıcı.
    """
    label = str(
        game.get("label")
        or game.get("match")
        or f"{game.get('away', '???')}@{game.get('home', '???')}"
    )
    market = str(game.get("market_str") or game.get("market") or "N/A")
    conf = safe_float(game.get("confidence", game.get("guven", 0.0)))
    edge = safe_float(game.get("edge", 0.0))
    stake = safe_float(game.get("stake", 1.0))

    return (
        f"📌 {label}\n"
        f"🎯 {market}\n"
        f"📈 Güven: {conf:.2f} | Edge: {edge:.3f}\n"
        f"💰 Stake: {stake:.3f}"
    ) 
