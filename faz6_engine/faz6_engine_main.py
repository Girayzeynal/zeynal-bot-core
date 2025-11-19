from __future__ import annotations

from typing import Any, Dict, List, Optional

from .presets import get_preset
from .selector import filter_and_rank_predictions

Prediction = Dict[str, Any]
EngineResult = Dict[str, Any]


# ============================================================
#              ÖRNEK / TEMPORARY TAHMİN ÜRETİCİ
# ============================================================

def _base_predictions() -> List[Prediction]:
    """
    Şimdilik FAZ-5 / canlı veri entegrasyonu yok.
    Stabil çalışsın diye sabit birkaç maç döndürüyoruz.
    Sonra burayı FAZ-5 çıkışıyla besleyeceğiz.
    """
    return [
        {
            "id": "NBA:LAL@DEN",
            "league": "NBA",
            "match": "LAL@DEN",
            "pick": "DEN -4.5",
            "market": "spread",
            "confidence": 0.61,
            "edge": 0.032,
        },
        {
            "id": "NBA:BOS@MIA",
            "league": "NBA",
            "match": "BOS@MIA",
            "pick": "UNDER 224.5",
            "market": "total",
            "confidence": 0.63,
            "edge": 0.036,
        },
        {
            "id": "EL:FENER@OLY",
            "league": "EuroLeague",
            "match": "FENER@OLY",
            "pick": "OLYMPiacos -3.5",
            "market": "spread",
            "confidence": 0.64,
            "edge": 0.041,
        },
        {
            "id": "EL:EFES@REAL",
            "league": "EuroLeague",
            "match": "EFES@REAL",
            "pick": "REAL MADRID -5.5",
            "market": "spread",
            "confidence": 0.66,
            "edge": 0.045,
        },
        {
            "id": "NBA:GSW@PHX",
            "league": "NBA",
            "match": "GSW@PHX",
            "pick": "OVER 230.5",
            "market": "total",
            "confidence": 0.59,
            "edge": 0.028,
        },
        {
            "id": "NBA:CHI@NYK",
            "league": "NBA",
            "match": "CHI@NYK",
            "pick": "NYK ML",
            "market": "moneyline",
            "confidence": 0.6,
            "edge": 0.031,
        },
    ]


# ============================================================
#                    ANA FAZ-6 MOTORU
# ============================================================

def run_faz6_engine(mode: str = "auto", context: Optional[Dict[str, Any]] = None) -> EngineResult:
    """
    FAZ-6 ana motoru (minimal, stabil, circular import yok).

    Dönüş formatı main.py + format_faz6_message ile uyumludur:
        {
            "status": "ok" | "error",
            "mode": "...",
            "result": {
                "predictions": [...],
                "portfolio": [...],
                "meta": {...},
            },
            "context": {...},
        }
    """
    if context is None:
        context = {}

    mode_norm = (mode or "auto").lower().strip()
    context["requested_mode"] = mode_norm

    preset = get_preset(mode_norm)

    try:
        raw_preds = _base_predictions()
        final_preds = filter_and_rank_predictions(raw_preds, preset)

        result_block: Dict[str, Any] = {
            "predictions": final_preds,
            "portfolio": final_preds,
            "meta": {
                "preset": {
                    "code": preset.code,
                    "title": preset.title,
                    "min_confidence": preset.min_confidence,
                    "min_edge": preset.min_edge,
                    "max_picks": preset.max_picks,
                    "base_stake": preset.base_stake,
                },
                "total_input": len(raw_preds),
                "total_output": len(final_preds),
            },
        }

        return {
            "status": "ok",
            "mode": mode_norm,
            "result": result_block,
            "context": context,
        }

    except Exception as e:
        # Her türlü hatayı yakalayıp anlaşılır döndür
        return {
            "status": "error",
            "mode": mode_norm,
            "detail": f"FAZ-6 engine exception: {repr(e)}",
            "result": {
                "predictions": [],
                "portfolio": [],
                "meta": {},
            },
            "context": context,
        }
