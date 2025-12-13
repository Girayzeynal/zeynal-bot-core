# -*- coding: utf-8 -*-
"""
FAZ-7 Memory Engine (Fly.io friendly)
- main.py `faz7_memory` callable bekler.
- hem faz7_memory() hem faz7_memory(meta) imzasını tolere eder.
- hafif, dosya tabanlı, kilitli (thread-safe) mini hafıza.
"""

from __future__ import annotations

import json
import os
import time
import threading
from typing import Any, Dict, Optional

_LOCK = threading.Lock()

DEFAULT_PATH = os.getenv("FAZ7_MEMORY_PATH", "/data/faz7/faz7_memory.json")
MAX_EVENTS = int(os.getenv("FAZ7_MAX_EVENTS", "400"))  # Fly 256/512MB için küçük tut


def _now_ts() -> int:
    return int(time.time())


def _safe_mkdir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _load(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        # bozuk json vs → resetle ama patlama yok
        return {}


def _save(path: str, data: Dict[str, Any]) -> None:
    _safe_mkdir(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _get_user_key(meta: Optional[Dict[str, Any]]) -> str:
    if not isinstance(meta, dict):
        return "global"
    # Telegram id / user id vs
    uid = meta.get("user_id") or meta.get("chat_id") or meta.get("uid")
    return str(uid) if uid is not None else "global"


def _trim_events(events: list, max_events: int) -> list:
    if len(events) <= max_events:
        return events
    return events[-max_events:]


def _record_event(db: Dict[str, Any], user_key: str, meta: Optional[Dict[str, Any]]) -> None:
    bucket = db.setdefault(user_key, {})
    events = bucket.setdefault("events", [])
    events.append(
        {
            "ts": _now_ts(),
            "source_type": (meta or {}).get("source_type") if isinstance(meta, dict) else None,
            "league": (meta or {}).get("league") if isinstance(meta, dict) else None,
            "home": (meta or {}).get("home") if isinstance(meta, dict) else None,
            "away": (meta or {}).get("away") if isinstance(meta, dict) else None,
        }
    )
    bucket["events"] = _trim_events(events, MAX_EVENTS)
    bucket["last_ts"] = _now_ts()


def get_faz7_summary(path: str = DEFAULT_PATH, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    İstersen /status dışında debug için çağırırsın.
    """
    with _LOCK:
        db = _load(path)
        user_key = _get_user_key(meta)
        bucket = db.get(user_key, {})
        events = bucket.get("events", [])
        return {
            "user_key": user_key,
            "events_count": len(events),
            "last_ts": bucket.get("last_ts"),
        }


def faz7_memory(meta: Optional[Dict[str, Any]] = None, path: str = DEFAULT_PATH) -> Dict[str, Any]:
    """
    main.py burada iki şekilde çağırabilir:
      - faz7_memory(meta)
      - faz7_memory()
    İkisini de destekliyoruz.
    """
    with _LOCK:
        db = _load(path)
        user_key = _get_user_key(meta)
        _record_event(db, user_key, meta if isinstance(meta, dict) else None)
        _save(path, db)

    # küçük bir çıktı (main.py umursamasa bile ok)
    return {"ok": True, "user_key": user_key, "ts": _now_ts()}
