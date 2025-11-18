"""
FAZ-6 Core Helpers
------------------
Modlar arası paylaşılan çekirdek preset + filtre + sıralama sistemidir.
Network yapmaz, sadece hesaplama yapar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


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


# Varsayılan preset’ler (FAZ-7 uyumlu)
PRESETS: Dict[str, Faz6Preset] = {
    "test": Faz6Preset(
        code="test",
        title="FAZ-6 TEST PRESET",
        min_confidence=0.55,
        min_edge=0.03,
        max_picks=5,
    ),
    "risk": Faz6Preset(
        code="risk",
        title="FAZ-6 RISK PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=7,
    ),
    "auto": Faz6Preset(
        code="auto",
        title="FAZ-6 AUTO PRESET",
        min_confidence=0.58,
        min_edge=0.04,
        max_picks=10,
    ),
    "balance": Faz6Preset(
        code="balance",
        title="FAZ-6 BALANCE PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=12,
    ),
    "real": Faz6Preset(
        code="real",
        title="FAZ-6 REAL PRESET",
        min_confidence=0.57,
        min_edge=0.035,
        max_picks=None,
    ),
    "coupon": Faz6Preset(
        code="coupon",
        title="FAZ-6 COUPON PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=None,
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
#  FİLTRE + SIRALAMA
# ======================================================

def filter_and_rank_games(
    games: Iterable[Dict[str, Any]],
    preset: Faz6Preset,
) -> List[Dict[str, Any]]:
    """
    Ortak FAZ-6 filtreleme:
        - confidence >= preset.min_confidence
        - edge >= preset.min_edge
        - confidence DESC + edge DESC sıralama
        - max_picks uygula
    """
    filtered: List[Dict[str, Any]] = []

    for game in games:
        try:
            conf = float(game.get("confidence", game.get("guven", 0.0)))
        except:
            conf = 0.0

        try:
            edge = float(game.get("edge", 0.0))
        except:
            edge = 0.0

        if conf < preset.min_confidence:
            continue
        if edge < preset.min_edge:
            continue

        filtered.append(game)

    filtered.sort(
        key=lambda g: (
            float(g.get("confidence", g.get("guven", 0.0))),
            float(g.get("edge", 0.0)),
        ),
        reverse=True,
    )

    if preset.max_picks and len(filtered) > preset.max_picks:
        filtered = filtered[: preset.max_picks]

    return filtered


# ======================================================
#  FORMAT HELPERS
# ======================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except:
        return default


def format_pick_for_telegram(game: Dict[str, Any]) -> str:
    """
    Telegram için tek maç formatlayıcı.
    """
    label = str(game.get("label") or game.get("match") or "UNKNOWN")
    market = str(game.get("market_str") or game.get("market") or "None")
    conf = safe_float(game.get("confidence", game.get("guven", 0.0)))
    edge = safe_float(game.get("edge", 0.0))
    stake = safe_float(game.get("stake", 0.0))

    return (
        f"📌 {label}\n"
        f"🎯 {market}\n"
        f"📈 Güven: {conf:.2f} | Edge: {edge:.3f}\n"
        f"💰 Stake: {stake:.3f}"
    ) 
