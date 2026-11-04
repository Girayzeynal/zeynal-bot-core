from __future__ import annotations

import time
import math
from typing import Any, Dict, List, Optional


def aggregate_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Production-grade aggregation for team baselines.

    INPUT (rows):
      Each row MUST come from a real provider (ESPN, SportsDataIO, API-Sports fallback)
      and MUST include:
        - pts_for: float
        - pts_against: float
        - confidence: float (0..1)
        - source: str
      Optional:
        - fetched_at: int (unix ts)

    OUTPUT (dict) or None:
      {
        "pts_for": float,
        "pts_against": float,
        "confidence": float,      # normalized 0..1
        "sources": List[str],     # ordered by provider confidence desc
        "fetched_at": int,        # max fetched_at among rows or now()
      }

    RULES:
      - NO fabrication, NO defaults, NO demo values.
      - If no valid rows after validation -> return None.
      - Confidence is normalized from provider confidences.
      - pts_for / pts_against are confidence-weighted means.
    """

    if not rows:
        return None

    clean: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if any(isinstance(r.get(k), bool) for k in ("pts_for", "pts_against", "confidence")):
            continue
        if not isinstance(r.get("source"), str):
            continue
        try:
            pf = float(r.get("pts_for"))
            pa = float(r.get("pts_against"))
            conf = float(r.get("confidence"))
            src = str(r.get("source", "")).strip()
        except Exception:
            continue

        # Reject NaN/inf: ordered comparisons do not reject NaN.
        if not all(math.isfinite(v) for v in (pf, pa, conf)):
            continue
        if pf <= 0 or pa <= 0:
            continue
        if conf <= 0 or conf > 1:
            continue
        if not src:
            continue

        fetched_at = r.get("fetched_at")
        try:
            fetched_at = int(fetched_at) if fetched_at is not None else None
        except Exception:
            fetched_at = None

        pace = r.get("pace")
        try:
            pace = float(pace) if pace is not None and not isinstance(pace, bool) else None
            if pace is not None and (not math.isfinite(pace) or not (40.0 <= pace <= 150.0)):
                pace = None
        except Exception:
            pace = None

        try:
            n_games = max(0, int(r.get("n_games", 0) or 0))
        except Exception:
            n_games = 0

        clean.append(
            {
                "pts_for": pf,
                "pts_against": pa,
                "confidence": conf,
                "source": src,
                "fetched_at": fetched_at,
                "pace": pace,
                "n_games": n_games,
            }
        )

    if not clean:
        return None

    # confidence-weighted aggregation
    total_conf = sum(x["confidence"] for x in clean)
    if total_conf <= 0:
        return None

    pts_for = sum(x["pts_for"] * x["confidence"] for x in clean) / total_conf
    pts_against = sum(x["pts_against"] * x["confidence"] for x in clean) / total_conf

    # normalized confidence: mean provider confidence (bounded)
    confidence_norm = max(0.0, min(1.0, total_conf / len(clean)))

    # sources ordered by provider confidence (desc)
    sources = [x["source"] for x in sorted(clean, key=lambda z: z["confidence"], reverse=True)]

    # fetched_at: latest timestamp if provided, else now()
    fetched_times = [x["fetched_at"] for x in clean if isinstance(x["fetched_at"], int)]
    fetched_at_out = max(fetched_times) if fetched_times else int(time.time())

    pace_rows = [x for x in clean if x["pace"] is not None]
    pace_total_conf = sum(x["confidence"] for x in pace_rows)
    pace_mean = (
        sum(x["pace"] * x["confidence"] for x in pace_rows) / pace_total_conf
        if pace_total_conf > 0 else None
    )
    n_games = max((x["n_games"] for x in clean), default=0)

    return {
        "pts_for": pts_for,
        "pts_against": pts_against,
        "confidence": confidence_norm,
        "sources": sources,
        "fetched_at": fetched_at_out,
        "pace": pace_mean,
        "n_games": n_games,
    } 
