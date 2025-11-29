import os
import json
import time
from typing import Any, Dict


_FAZ11_PATH = os.getenv("FAZ11_HISTORY_PATH", "/data/faz11_history.json")


def _read() -> Dict[str, Any]:
    try:
        with open(_FAZ11_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"events": []}


def _write(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(_FAZ11_PATH), exist_ok=True)
    try:
        with open(_FAZ11_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def faz11_feedback(
    source_type: str,
    meta: Dict[str, Any],
    result_text: str,
    outcome: str | None = None,
):
    """
    FAZ-11 — Feedback Engine
    - Tahmin sonrası metayı + çıktı text'ini kaydeder
    - outcome: 'HIT' / 'MISS' / None
    """
    data = _read()
    events = data.get("events", [])

    evt = {
        "ts": time.time(),
        "source": source_type,
        "meta": meta,
        "result_text": result_text,
        "outcome": outcome,
    }
    events.append(evt)
    data["events"] = events[-500:]  # son 500 event tut
    _write(data)


def faz11_last_summary(n: int = 10) -> str:
    """
    /status gibi yerlerde kullanmak için kısa özet.
    """
    data = _read()
    events = data.get("events", [])
    tail = events[-n:]

    if not tail:
        return "FAZ-11: Henüz kayıtlı feedback yok."

    hits = sum(1 for e in tail if e.get("outcome") == "HIT")
    miss = sum(1 for e in tail if e.get("outcome") == "MISS")
    total = len(tail)

    return f"FAZ-11: Son {total} tahminde HIT={hits}, MISS={miss}."
