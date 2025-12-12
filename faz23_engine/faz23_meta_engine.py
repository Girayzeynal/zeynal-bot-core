# faz23_engine/faz23_meta_engine.py
# ================================================================
# FAZ-23 META ENGINE v2.0
# Fly.io + CI + Prediction Sandbox
# ================================================================
from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("faz23-meta")

# ---------------------------------------------------
# Directory & cache (safe, import-time passive)
# ---------------------------------------------------
DATA_DIR = os.getenv("DATA_DIR", "/data")
FAZ23_DIR = os.path.join(DATA_DIR, "faz23")

try:
    os.makedirs(FAZ23_DIR, exist_ok=True)
except Exception as e:
    log.debug("[FAZ23] cache mkdir skip: %s", e)

NEWS_CACHE_PATH = os.path.join(FAZ23_DIR, "faz23_news_cache.jsonl")

# ---------------------------------------------------
# JSONL safe IO
# ---------------------------------------------------
def _safe_load_jsonl(path: str, limit: int = 256) -> List[Dict[str, Any]]:
    try:
        items: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        items.append(obj)
                except Exception:
                    continue
                if len(items) >= limit:
                    break
        return items
    except FileNotFoundError:
        return []
    except Exception as e:
        log.warning("[FAZ23] JSONL okunamadı: %s", e)
        return []

def _safe_append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug("[FAZ23] JSONL append skip: %s", e)

# ---------------------------------------------------
# Text normalize
# ---------------------------------------------------
def _safe_text(val: Any) -> str:
    try:
        if isinstance(val, (list, tuple)):
            val = " ".join(str(x) for x in val)
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="ignore")
        return str(val).strip()
    except Exception:
        return ""

# ---------------------------------------------------
# Score Vector
# ---------------------------------------------------
def _compute_score_vector(
    total_line: float,
    live_total: float,
) -> Tuple[float, float]:
    """
    Basit over/under bias:
    - live_total == 0 → prematch
    - total_line > 0 → use
    """
    try:
        if total_line <= 0:
            return (0.5, 0.5)
        if live_total <= 0:
            # prematch: total_line varyansı
            # 0.52/0.48 gibi ayar
            return (0.52, 0.48)
        # live: toplam skor > beklenen total
        ratio = live_total / total_line
        if ratio > 1.05:
            return (0.7, 0.3)
        if ratio < 0.95:
            return (0.3, 0.7)
        return (0.5, 0.5)
    except Exception:
        return (0.5, 0.5)

# ---------------------------------------------------
# News helpers (unchanged, safe)
# ---------------------------------------------------
def get_match_news(league: str, date: str, home: str, away: str) -> str:
    try:
        # load news cache
        raw = _safe_load_jsonl(NEWS_CACHE_PATH)
        # find matching
        hits = [
            x for x in raw
            if x.get("league") == league
            and x.get("home") == home
            and x.get("away") == away
        ]
        # choose last
        if hits:
            return _safe_text(hits[-1].get("news_summary"))
        return ""
    except Exception:
        return ""

# ---------------------------------------------------
# Public interface
# ---------------------------------------------------
def faz23_meta_predict(
    league: str,
    date: str,
    home: str,
    away: str,
    total_line: float,
    live_total: float,
) -> Dict[str, Any]:
    """
    return: {
       "total_line": float,
       "over_bias": float,
       "under_bias": float,
       "news": str
    }
    """
    try:
        o, u = _compute_score_vector(total_line, live_total)
        return {
            "total_line": total_line,
            "over_bias": o,
            "under_bias": u,
            "news": get_match_news(league, date, home, away),
        }
    except Exception as e:
        log.warning("[FAZ23 META PREDICT ERROR] %s", e)
        return {"total_line": total_line, "over_bias": 0.5, "under_bias": 0.5, "news": ""}

__all__ = ["faz23_meta_predict", "get_match_news"]
