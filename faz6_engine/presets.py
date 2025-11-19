from __future__ import annotations
from typing import Dict, Any


class ModePreset:
    def __init__(
        self,
        code: str,
        title: str,
        min_confidence: float,
        min_edge: float,
        max_picks: int,
        base_stake: float,
    ):
        self.code = code
        self.title = title
        self.min_confidence = min_confidence
        self.min_edge = min_edge
        self.max_picks = max_picks
        self.base_stake = base_stake


# ============================================================
# PRESET SEÇİCİ
# ============================================================

def get_preset(mode: str) -> ModePreset:
    mode = mode.lower().strip()

    presets: Dict[str, ModePreset] = {
        "test": ModePreset(
            code="TEST",
            title="Test Modu",
            min_confidence=0.50,
            min_edge=0.01,
            max_picks=5,
            base_stake=1.0,
        ),
        "auto": ModePreset(
            code="AUTO",
            title="Otomatik Mod",
            min_confidence=0.55,
            min_edge=0.02,
            max_picks=8,
            base_stake=1.0,
        ),
        "risk": ModePreset(
            code="RISK",
            title="Risk Modu",
            min_confidence=0.50,
            min_edge=0.03,
            max_picks=10,
            base_stake=1.0,
        ),
        "edge": ModePreset(
            code="EDGE",
            title="Edge Odaklı",
            min_confidence=0.60,
            min_edge=0.04,
            max_picks=6,
            base_stake=1.0,
        ),
        "real": ModePreset(
            code="REAL",
            title="Gerçekçi Mod",
            min_confidence=0.58,
            min_edge=0.03,
            max_picks=7,
            base_stake=1.0,
        ),
        "balance": ModePreset(
            code="BAL",
            title="Dengeli Kupon",
            min_confidence=0.57,
            min_edge=0.025,
            max_picks=6,
            base_stake=1.0,
        )
    }

    return presets.get(mode, presets["auto"]) 
