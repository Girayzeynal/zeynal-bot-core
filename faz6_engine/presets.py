from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ModePreset:
    code: str
    title: str
    min_confidence: float
    min_edge: float
    max_picks: Optional[int]
    base_stake: float


PRESETS: Dict[str, ModePreset] = {
    "test": ModePreset(
        code="test",
        title="FAZ-6 TEST MODE",
        min_confidence=0.55,
        min_edge=0.01,
        max_picks=5,
        base_stake=1.0,
    ),
    "auto": ModePreset(
        code="auto",
        title="FAZ-6 AUTO MODE",
        min_confidence=0.58,
        min_edge=0.02,
        max_picks=10,
        base_stake=1.2,
    ),
    "risk": ModePreset(
        code="risk",
        title="FAZ-6 RISK MODE",
        min_confidence=0.62,
        min_edge=0.03,
        max_picks=7,
        base_stake=1.0,
    ),
    "edge": ModePreset(
        code="edge",
        title="FAZ-6 EDGE MODE",
        min_confidence=0.60,
        min_edge=0.05,
        max_picks=8,
        base_stake=1.4,
    ),
    "real": ModePreset(
        code="real",
        title="FAZ-6 REAL MODE",
        min_confidence=0.58,
        min_edge=0.025,
        max_picks=6,
        base_stake=1.1,
    ),
    "balance": ModePreset(
        code="balance",
        title="FAZ-6 BALANCE MODE",
        min_confidence=0.60,
        min_edge=0.03,
        max_picks=9,
        base_stake=1.15,
    ),
}


def get_preset(code: str) -> ModePreset:
    """
    Geçersiz / boş kod gelirse 'auto' preset'i döner.
    """
    code = (code or "").lower().strip()
    return PRESETS.get(code, PRESETS["auto"])
