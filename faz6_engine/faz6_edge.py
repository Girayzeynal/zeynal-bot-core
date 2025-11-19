from __future__ import annotations

from typing import Any, Dict, List, Optional

from .faz6_core import (
    Prediction,
    EngineResult,
    get_preset,
    filter_and_rank_games,
    normalize_engine_result,
)


def _build_edge_games() -> List[Prediction]:
    """
    EDGE modu: yüksek edge odaklı, biraz daha agresif.
    """
    return [
        {
            "id": "EDGE:NBA:PHX@SAC",
            "league": "NBA",
            "match": "PHX@SAC",
            "market": "spread",
            "selection": "SAC -5.5",
            "confidence": 0.64,
            "edge": 0.075,
            "stake": 1.4,
        },
        {
            "id": "EDGE:NBA:DAL@HOU",
            "league": "NBA",
            "match": "DAL@HOU",
            "market": "total",
            "selection": "OVER 229.5",
            "confidence": 0.63,
            "edge": 0.072,
            "stake": 1.3,
        },
        {
            "id": "EDGE:EL:BARCA@EFES",
            "league": "EuroLeague",
            "match": "BARCA@EFES",
            "market": "moneyline",
            "selection": "BARCELONA",
            "confidence": 0.66,
            "edge": 0.080,
            "stake": 1.5,
        },
    ]


def run_faz6_edge(context: Optional[Dict[str, Any]] = None) -> EngineResult:
    """
    FAZ-6 EDGE modu.
    """
    if context is None:
        context = {}

    games = _build_edge_games()
    preset = get_preset("edge")
    picks = filter_and_rank_games(games, preset)

    meta = {
        "preset": preset.code,
        "preset_detail": preset.title,
        "source": "faz6_edge",
    }

    return normalize_engine_result(
        mode="edge",
        predictions=picks,
        context=context,
        meta=meta,
    )
