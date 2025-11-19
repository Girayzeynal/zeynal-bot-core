from __future__ import annotations

from typing import Any, Dict, List, Optional

from .faz6_core import (
    Prediction,
    EngineResult,
    get_preset,
    filter_and_rank_games,
    normalize_engine_result,
)


def _build_test_games() -> List[Prediction]:
    """
    Basit sabit test datası.
    Gerçek veri entegrasyonu geldiğinde context üzerinden geçilecektir.
    """
    return [
        {
            "id": "TEST:NBA:LAL@BOS",
            "league": "NBA",
            "match": "LAL@BOS",
            "market": "spread",
            "selection": "BOS -3.5",
            "confidence": 0.65,
            "edge": 0.045,
            "stake": 1.2,
        },
        {
            "id": "TEST:EL:FENER@REAL",
            "league": "EuroLeague",
            "match": "FENER@REAL",
            "market": "total",
            "selection": "OVER 160.5",
            "confidence": 0.62,
            "edge": 0.040,
            "stake": 1.1,
        },
        {
            "id": "TEST:NBA:GSW@MIA",
            "league": "NBA",
            "match": "GSW@MIA",
            "market": "moneyline",
            "selection": "MIA",
            "confidence": 0.60,
            "edge": 0.035,
            "stake": 1.0,
        },
    ]


def run_faz6_test(context: Optional[Dict[str, Any]] = None) -> EngineResult:
    """
    FAZ-6 TEST modu.
    """
    if context is None:
        context = {}

    # İleride: context["games"] varsa onu kullan.
    games = context.get("games") or _build_test_games()

    preset = get_preset("test")
    picks = filter_and_rank_games(games, preset)

    meta = {
        "preset": preset.code,
        "preset_detail": preset.title,
        "source": "faz6_test",
    }

    return normalize_engine_result(
        mode="test",
        predictions=picks,
        context=context,
        meta=meta,
    ) 
