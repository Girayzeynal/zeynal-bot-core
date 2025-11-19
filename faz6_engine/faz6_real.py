from __future__ import annotations

from typing import Any, Dict, List, Optional

from .faz6_core import (
    Prediction,
    EngineResult,
    get_preset,
    filter_and_rank_games,
    normalize_engine_result,
)


def _build_real_games() -> List[Prediction]:
    """
    REAL modu: daha temkinli, gerçek zaman mantığına yakın preset.
    Şimdilik sabit örnek.
    """
    return [
        {
            "id": "REAL:NBA:LAL@GSW",
            "league": "NBA",
            "match": "LAL@GSW",
            "market": "spread",
            "selection": "LAL +4.5",
            "confidence": 0.58,
            "edge": 0.040,
            "stake": 1.0,
        },
        {
            "id": "REAL:NBA:CHI@NYK",
            "league": "NBA",
            "match": "CHI@NYK",
            "market": "total",
            "selection": "UNDER 217.5",
            "confidence": 0.57,
            "edge": 0.035,
            "stake": 0.9,
        },
        {
            "id": "REAL:EL:OLY@REAL",
            "league": "EuroLeague",
            "match": "OLY@REAL",
            "market": "moneyline",
            "selection": "REAL MADRID",
            "confidence": 0.60,
            "edge": 0.040,
            "stake": 1.1,
        },
    ]


def run_faz6_real(context: Optional[Dict[str, Any]] = None) -> EngineResult:
    """
    FAZ-6 REAL modu.
    """
    if context is None:
        context = {}

    games = _build_real_games()
    preset = get_preset("real")
    picks = filter_and_rank_games(games, preset)

    meta = {
        "preset": preset.code,
        "preset_detail": preset.title,
        "source": "faz6_real",
    }

    return normalize_engine_result(
        mode="real",
        predictions=picks,
        context=context,
        meta=meta,
    )
