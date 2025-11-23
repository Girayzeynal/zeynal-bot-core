import os
import json
import time
import logging
from typing import List, Dict, Any

import numpy as np

from main import FAZ7_DIR  # ileride faz79_core'dan çekebilirsin

log = logging.getLogger(__name__)

FAZ11_LOG_FILE = os.path.join(FAZ7_DIR, "faz11_history.json")


def _append_log(entry: Dict[str, Any]) -> None:
    try:
        if os.path.exists(FAZ11_LOG_FILE):
            with open(FAZ11_LOG_FILE, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        else:
            data = []
        data.append(entry)
        with open(FAZ11_LOG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.warning(f"[FAZ-11] Log yazılamadı: {e}")


def faz11_feedback(real_results: List[bool],
                   predicted: List[Dict[str, Any]],
                   save: bool = True) -> Dict[str, Any]:
    """
    FAZ-11 – FEEDBACK LOOP
      real_results: [True/False] -> tahmin doğru mu?
      predicted: [
         {"conf":0.63, "edge":0.038, "bucket":"MID"},
         ...
      ]
    """
    total = max(len(real_results), 1)
    correct = sum(1 for r in real_results if r)

    accuracy = correct / total

    avg_conf = float(np.mean([p.get("conf", 0.0) for p in predicted])) if predicted else 0.0
    avg_edge = float(np.mean([p.get("edge", 0.0) for p in predicted])) if predicted else 0.0

    model_drift = abs(avg_conf - accuracy)

    bucket_perf: Dict[str, Dict[str, float]] = {}
    for r, p in zip(real_results, predicted):
        b = p.get("bucket", "UNK")
        if b not in bucket_perf:
            bucket_perf[b] = {"correct": 0, "total": 0}
        bucket_perf[b]["total"] += 1
        if r:
            bucket_perf[b]["correct"] += 1

    for b, v in bucket_perf.items():
        v["accuracy"] = v["correct"] / max(v["total"], 1)

    result = {
        "faz": "FAZ-11",
        "ts": int(time.time()),
        "total": total,
        "correct": correct,
        "daily_accuracy": round(accuracy, 3),
        "avg_conf": round(avg_conf, 3),
        "avg_edge": round(avg_edge, 3),
        "model_drift": round(model_drift, 3),
        "bucket_perf": bucket_perf,
    }

    if save:
        _append_log(result)
        log.info(f"[FAZ-11] Feedback: {result}")

    return result


def faz11_last_summary() -> Dict[str, Any]:
    if not os.path.exists(FAZ11_LOG_FILE):
        return {"count": 0, "last": None}

    try:
        with open(FAZ11_LOG_FILE, "r") as f:
            data = json.load(f)
        if not data:
            return {"count": 0, "last": None}
        return {
            "count": len(data),
            "last": data[-1],
        }
    except Exception as e:
        log.warning(f"[FAZ-11] History okunamadı: {e}")
        return {"count": 0, "last": None}
