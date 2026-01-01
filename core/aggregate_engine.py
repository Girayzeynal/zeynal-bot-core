# core/aggregate_engine.py

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AggregateResult:
    pts_for: float
    pts_against: float
    confidence_raw: float  # 0..1
    sources: List[str]
    fetched_at: int


def aggregate_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Production-grade aggregation:
      - Strictly uses provided real rows (no fabrication)
      - Confidence-weighted blend
      - Returns normalized confidence_raw in 0..1 and sources list[str]
    """
    if not rows:
        return None

    clean: List[Dict[str, Any]] = []
    for r in rows:
        try:
            pf = float(r["pts_for"])
            pa = float(r["pts_against"])
            conf = float(r.get("confidence", 0.0))
            src = str(r.get("source", "")).strip()
        except Exception:
            continue
        if conf <= 0 or not src:
            continue
        clean.append({"pts_for": pf, "pts_against": pa, "confidence": conf, "source": src})

    if not clean:
        return None

    total_conf = sum(x["confidence"] for x in clean)
    if total_conf <= 0:
        return None

    pts_for = sum(x["pts_for"] * x["confidence"] for x in clean) / total_conf
    pts_against = sum(x["pts_against"] * x["confidence"] for x in clean) / total_conf

    # normalized provider confidence: mean confidence of included sources (bounded)
    conf_out = min(1.0, max(0.0, total_conf / len(clean)))

    # sources ordered by confidence desc
    sources = [x["source"] for x in sorted(clean, key=lambda z: z["confidence"], reverse=True)]

    return {
        "pts_for": pts_for,
        "pts_against": pts_against,
        "confidence": conf_out,
        "sources": sources,
        "fetched_at": int(time.time()),
    } 
