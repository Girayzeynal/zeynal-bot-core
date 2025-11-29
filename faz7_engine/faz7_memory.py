import os
import json
import time
from typing import Any, Dict, List


class Faz7MemoryEngine:
    """
    FAZ-7.9 v2.0 — Lightweight Memory Engine
    - Son X günü JSON dosyasında tutar
    - Request + Prediction + Feedback saklanır
    - FAZ-10 / 11 / 12 için veri kaynağı
    """

    def __init__(self, base_dir: str | None = None, days_window: int = 7):
        self.days_window = days_window
        self.base_dir = base_dir or os.getenv("FAZ7_DIR", "/data/faz7")
        self.mem_path = os.path.join(self.base_dir, "faz7_memory.json")

        os.makedirs(self.base_dir, exist_ok=True)
        if not os.path.exists(self.mem_path):
            self._write({"events": []})

    # ----------------------------- internal io -----------------------------

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.mem_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"events": []}

    def _write(self, data: Dict[str, Any]):
        try:
            with open(self.mem_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _prune_old(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = time.time()
        window_sec = self.days_window * 86400
        return [e for e in events if now - e.get("ts", now) <= window_sec]

    # ----------------------------- public api ------------------------------

    def log_request(
        self,
        user_id: int | str,
        source_type: str,
        meta: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ):
        data = self._read()
        events = data.get("events", [])

        evt = {
            "ts": time.time(),
            "user_id": str(user_id),
            "type": "request",
            "source": source_type,
            "meta": meta,
            "ctx": context or {},
        }
        events.append(evt)
        events = self._prune_old(events)
        data["events"] = events
        self._write(data)

    def log_feedback(
        self,
        user_id: int | str,
        source_type: str,
        meta: Dict[str, Any],
        result: Dict[str, Any] | None = None,
        outcome: str | None = None,
    ):
        data = self._read()
        events = data.get("events", [])

        evt = {
            "ts": time.time(),
            "user_id": str(user_id),
            "type": "feedback",
            "source": source_type,
            "meta": meta,
            "result": result or {},
            "outcome": outcome,
        }
        events.append(evt)
        events = self._prune_old(events)
        data["events"] = events
        self._write(data)

    def summary_last_n(self, n: int = 20) -> Dict[str, Any]:
        data = self._read()
        events = data.get("events", [])
        tail = events[-n:]
        return {
            "count": len(events),
            "last_n": tail,
        }
