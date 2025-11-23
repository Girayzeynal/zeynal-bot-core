import logging
from typing import Dict, Any

# FAZ-12 log sistemi
log = logging.getLogger(__name__)

# |-----------------------------------------------|
# |  FAZ-12  —  INTERNAL MODE-SWITCH OPERATIONS   |
# |-----------------------------------------------|

def _set_mode(new_mode: str) -> None:
    """
    Mode değişimini FAZ-7.9 hafıza dosyasına yazar.
    """
    mem = faz12_get_memory()
    new_mode = (new_mode or "BAL").upper()

    mem["safe"] = int(new_mode == "SAFE")
    mem["bal"]  = int(new_mode == "BAL")
    mem["agg"]  = int(new_mode == "AGG")

    faz12_save_memory(mem)
    log.info(f"[FAZ-12] Mode değiştirildi: {new_mode}")


# |-----------------------------------------------|
# |  FAZ-12 — AUTO PROFILE ENGINE                 |
# |-----------------------------------------------|

def faz12_auto_profile(f10_state: Dict[str, Any],
                       f11_state: Dict[str, Any],
                       brain: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-12 — AUTO PROFILE ADJUSTER

    - FAZ-10 stability
    - FAZ-11 accuracy / model_drift
    - FAZ-9.x behavior_index
    - FAZ-8 avg conf/edge

    Üzerinden yeni bir strateji modu seçer.
    """

    curr_mode = brain.get("mode", "BAL")

    stability      = float(f10_state.get("stability", 1.0))
    daily_accuracy = float(f11_state.get("daily_accuracy", 0.0))
    model_drift    = float(f11_state.get("model_drift", 0.0))
    behavior_index = float(brain.get("behavior_index", 1.0))
    avg_conf = float(brain.get("conf", 0.0))
    avg_edge = float(brain.get("edge", 0.0))

    # SAFE KOŞULLARI
    if (
        stability < 0.80
        or daily_accuracy < 0.55
        or behavior_index < 0.90
        or model_drift > 0.12
    ):
        new_mode = "SAFE"
        reason = "risk_conditions"

    # AGG KOŞULLARI
    elif (
        daily_accuracy > 0.75
        and avg_edge > 0.040
        and brain["trend"] == "UP"
        and behavior_index >= 1.0
    ):
        new_mode = "AGG"
        reason = "high_performance"

    # Diğer her şey BAL
    else:
        new_mode = "BAL"
        reason = "normal_conditions"

    changed = (new_mode != curr_mode)
    if changed:
        _set_mode(new_mode)

    decision = {
        "faz": "FAZ-12",
        "old_mode": curr_mode,
        "new_mode": new_mode,
        "changed": changed,
        "reason": reason,
        "inputs": {
            "stability":      stability,
            "daily_accuracy": daily_accuracy,
            "model_drift":    model_drift,
            "behavior_index": behavior_index,
            "avg_conf":       avg_conf,
            "avg_edge":       avg_edge,
            "trend":          brain["trend"],
        },
    }

    log.info(f"[FAZ-12] Auto-profile kararı: {decision}")
    return decision


# |-----------------------------------------------|
# |  FAZ-12 — SINGLE RUN HELPER                   |
# |-----------------------------------------------|

def faz12_run_once(f10_state: Dict[str, Any],
                   f11_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Beyni içerden okuyup FAZ-12’yi bir kere çalıştırır.
    """
    brain = faz12_get_brain()          # ❗ artık main’den GELİYOR (circular yok)
    return faz12_auto_profile(f10_state, f11_state, brain) 
