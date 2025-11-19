from __future__ import annotations

from typing import Any, Dict, List, Optional

from .faz6_core import (
    Prediction,
    EngineResult,
    get_preset,
    filter_and_rank_games,
    normalize_engine_result,
)


def _build_balance_games() -> List[Prediction]:
    """
    BALANCE modu:
      - NBA + EuroLeague karışık
      - risk ve edge ortalama
    Şimdilik kendi içinde dengeli statik havuz.
    """
    return [
        {
            "id": "BAL:NBA:MIA@ATL",
            "league": "NBA",
            "match": "MIA@ATL",
            "market": "spread",
            "selection": "MIA -1.5",
            "confidence": 0.62,
            "edge": 0.043,
            "stake": 1.2,
        },
        {
            "id": "BAL:NBA:BOS@PHI",
            "league": "NBA",
            "match": "BOS@PHI",
            "market": "total",
            "selection": "UNDER 223.5",
            "confidence": 0.61,
            "edge": 0.040,
            "stake": 1.1,
        },
        {
            "id": "BAL:EL:FENER@PART",
            "league": "EuroLeague",
            "match": "FENER@PART",
            "market": "moneyline",
            "selection": "PARTIZAN",
            "confidence": 0.60,
            "edge": 0.041,
            "stake": 1.0,
        },
        {
            "id": "BAL:EL:REAL@EFES",
            "league": "EuroLeague",
            "match": "REAL@EFES",
            "market": "spread",
            "selection": "REAL -6.5",
            "confidence": 0.63,
            "edge": 0.046,
            "stake": 1.3,
        },
    ]


def run_faz6_balance(context: Optional[Dict[str, Any]] = None) -> EngineResult:
    """
    FAZ-6 BALANCE modu.
    Diğer modlara import yapmaz; sadece kendi preset'ini kullanır.
    """
    if context is None:
        context = {}

    games = _build_balance_games()
    preset = get_preset("balance")
    picks = filter_and_rank_games(games, preset)

    meta = {
        "preset": preset.code,
        "preset_detail": preset.title,
        "source": "faz6_balance",
    }

    return normalize_engine_result(
        mode="balance",
        predictions=picks,
        context=context,
        meta=meta,
    )
