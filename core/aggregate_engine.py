# core/aggregate_engine.py

from typing import List, Dict, Optional


def aggregate_baseline(rows: List[Dict]) -> Optional[Dict]:
    """
    Birden fazla provider'dan gelen baseline verisini
    confidence ağırlıklı şekilde birleştirir.

    Input örneği:
    [
        {
            "pts_for": 109.7,
            "pts_against": 113.9,
            "confidence": 0.60,
            "source": "ESPN"
        }
    ]
    """

    if not rows:
        return None

    total_conf = sum(r.get("confidence", 0) for r in rows)
    if total_conf == 0:
        return None

    pts_for = sum(
        r["pts_for"] * r["confidence"] for r in rows if "pts_for" in r
    ) / total_conf

    pts_against = sum(
        r["pts_against"] * r["confidence"] for r in rows if "pts_against" in r
    ) / total_conf

    return {
        "pts_for": pts_for,
        "pts_against": pts_against,
        "confidence": total_conf / len(rows),
        "sources": [r.get("source") for r in rows],
    } 
