import logging
from typing import Dict, Any

# Yine iki senaryonun ilki:
from main import faz79_brain, load_memory, save_memory

log = logging.getLogger(__name__)


def _set_mode(new_mode: str) -> None:
    """
    Mode değişimini FAZ-7.9 hafıza dosyasına yazar.
    """
    new_mode = (new_mode or "BAL").upper()
    mem = load_memory()
    mem["safe"] = int(new_mode == "SAFE")
    mem["bal"] = int(new_mode == "BAL")
    mem["agg"] = int(new_mode == "AGG")
    save_memory(mem)
    log.info(f"[FAZ-12] Mode değiştirildi: {new_mode}")


def faz12_auto_profile(f10_state: Dict[str, Any],
                       f11_state: Dict[str, Any],
                       brain: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-12 – AUTO PROFILE ADJUSTER
      - FAZ-10 stability
      - FAZ-11 accuracy/model_drift
      - FAZ-9.x behavior_index
      - FAZ-7.9 avg conf/edge
    üzerinden yeni bir strateji modu seçer.
    """
    curr_mode = brain["mode"]
    stability = float(f10_state.get("stability", 1.0))
    daily_accuracy = float(f11_state.get("daily_accuracy", 0.0))
    model_drift = float(f11_state.get("model_drift", 0.0))
    behavior_index = float(brain.get("behavior_index", 1.0))
    avg_conf = float(brain.get("conf", 0.0))
    avg_edge = float(brain.get("edge", 0.0))

    # SAFE şartları
    if (
        stability < 0.80
        or daily_accuracy < 0.55
        or behavior_index < 0.90
        or model_drift > 0.12
    ):
        new_mode = "SAFE"
        reason = "risk_conditions"
    # AGG şartları
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
        "prev_mode": curr_mode,
        "new_mode": new_mode,
        "changed": changed,
        "reason": reason,
        "inputs": {
            "stability": stability,
            "daily_accuracy": daily_accuracy,
            "model_drift": model_drift,
            "behavior_index": behavior_index,
            "avg_conf": avg_conf,
            "avg_edge": avg_edge,
            "trend": brain["trend"],
        },
    }

    log.info(f"[FAZ-12] Auto-profile kararı: {decision}")
    return decision


def faz12_run_once(f10_state: Dict[str, Any], f11_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Beyni içerden okuyup bir kere çalıştırmak için helper.
    """
    brain = faz79_brain()
    return faz12_auto_profile(f10_state, f11_state, brain)
