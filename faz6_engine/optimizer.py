# ================================================================
#                    FAZ-6 OPTIMIZER MODÜLÜ
# ================================================================

from __future__ import annotations
from typing import List, Dict, Any


def _base_stake(confidence: float, risk: bool, aggressive: bool) -> float:
    """
    0.0 - 1.0 arası birim stake önerisi.
    """
    stake = max(0.0, min(1.0, (confidence - 0.5) * 2))  # 0.5 altı => 0'a yakın

    if risk:
        stake *= 0.6   # daha temkinli
    if aggressive:
        stake *= 1.4   # edge modunda biraz gaz

    return max(0.0, min(1.0, stake))


def optimize_predictions(
    predictions: List[Dict[str, Any]],
    ml_meta: Dict[str, Any],
    *,
    mode: str = "auto",
    risk: bool = False,
    aggressive: bool = False,
    realtime: bool = False,
) -> List[Dict[str, Any]]:
    """
    Prediction listesi üzerinde stake, not ve etiket önerisi üretir.
    """
    out: List[Dict[str, Any]] = []
    global_risk = float(ml_meta.get("risk_score", 0.5))

    for p in predictions:
        q = dict(p)

        conf = float(q.get("confidence", 0.6))
        edge = float(q.get("edge", 0.0))

        stake = _base_stake(conf, risk=risk, aggressive=aggressive)

        # Global risk yüksekse tüm stake'leri biraz kıs
        if global_risk > 0.6:
            stake *= 0.7
        elif global_risk < 0.3 and aggressive:
            stake *= 1.2

        # Realtime ise ek fren
        if realtime:
            stake *= 0.8

        q["recommended_stake"] = round(stake, 3)

        label_parts = [mode.upper()]
        if risk:
            label_parts.append("RISK")
        if aggressive:
            label_parts.append("EDGE")
        if realtime:
            label_parts.append("LIVE")

        q["label"] = " | ".join(label_parts)

        note_bits = []
        if edge >= 0.08:
            note_bits.append("Güçlü edge")
        elif edge >= 0.04:
            note_bits.append("İyi edge")
        if conf >= 0.7:
            note_bits.append("Yüksek güven")
        elif conf <= 0.55:
            note_bits.append("Düşük güven")

        if global_risk > 0.6:
            note_bits.append("Global risk yüksek")
        elif global_risk < 0.3:
            note_bits.append("Global risk düşük")

        if realtime:
            note_bits.append("Canlı akış")

        q["notes"] = ", ".join(note_bits) if note_bits else ""

        out.append(q)

    return out 
