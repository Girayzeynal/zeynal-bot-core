# ================================================================
#  🧠 FAZ-13 GOD-LAYER
#  FAZ-13.4 → FAZ-14 → FAZ-15 → FAZ-16 → FAZ-17
#  FULL GOD-MODE PIPELINE
# ================================================================
import time
from typing import Any, Dict, List, Optional

GOD_VERSION = "FAZ-13.4 + FAZ-14 + FAZ-15 + FAZ-16 + FAZ-17"


# ================================================================
#  YARDIMCI FONKSİYONLAR
# ================================================================
def _sf(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except:
        return default


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _get_from_many(d: Dict[str, Any], keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


# ================================================================
#  🔬 FAZ-13.4 – SIGNAL FUSION CORE
# ================================================================
def _faz134_signal_fusion(
    core_output: Dict[str, Any],
    brain: Dict[str, Any],
    f10_state: Dict[str, Any],
    f11_summary: Dict[str, Any],
    f12_decision: Dict[str, Any],
    history_samples: List[Dict[str, Any]],
    market_info: Dict[str, Any],
    meta_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta_context = meta_context or {}

    # core
    core_conf = _sf(_get_from_many(core_output, ["pred_conf", "conf", "confidence"], 0.60))
    core_edge = _sf(_get_from_many(core_output, ["pred_edge", "edge"], 0.03))
    core_bucket = _get_from_many(core_output, ["bucket", "risk_bucket"], "MID") or "MID"

    # brain
    brain_conf = _sf(brain.get("conf"), 0.60)
    brain_edge = _sf(brain.get("edge"), 0.03)
    brain_bi = _sf(brain.get("behavior_index"), 1.0)
    brain_mode = str(brain.get("mode", "INIT")).upper()
    brain_trend = str(brain.get("trend", "INIT")).upper()
    brain_stability = _sf(brain.get("stability"), 1.0)
    brain_noise = _sf(brain.get("noise_ratio"), 0.4)

    # f10 stability
    stab_score = _sf(f10_state.get("stability_score"), 0.9)
    stab_regime = str(f10_state.get("regime", "NORMAL")).upper()
    anomaly = _sf(f10_state.get("anomaly_level"), 0.0)

    # f11 feedback
    daily_acc = _sf(f11_summary.get("daily_accuracy"), 0.70)
    rolling_acc = _sf(f11_summary.get("rolling_accuracy"), daily_acc)
    model_drift = _sf(f11_summary.get("model_drift"), 0.0)

    # f12 mode adjust
    new_mode = str(f12_decision.get("new_mode", brain_mode)).upper()
    changed = bool(f12_decision.get("changed", False))

    # market info
    market_odds = _sf(market_info.get("odds"), 1.90)
    implied_prob = 1.0 / market_odds if market_odds > 1.01 else 0.5
    price_misalign = core_conf - implied_prob

    # Risk factor by auto-profile
    if new_mode == "SAFE":
        risk_factor = 0.85
    elif new_mode == "AGG":
        risk_factor = 1.10
    else:
        risk_factor = 1.0

    # GOD TRSUT (0–1)
    sig_stab = _clamp(stab_score, 0.0, 1.0)
    sig_anom = 1.0 - _clamp(anomaly, 0.0, 1.0)
    sig_drift = 1.0 - _clamp(model_drift, 0.0, 1.0)
    sig_noise = 1.0 - _clamp(brain_noise / 1.5, 0.0, 1.0)

    god_trust = (
        0.35 * sig_stab +
        0.20 * sig_anom +
        0.20 * sig_drift +
        0.15 * sig_noise +
        0.10 * _clamp(rolling_acc, 0.50, 0.95)
    )
    god_trust = _clamp(god_trust, 0.0, 1.0)

    # fused confidence
    fused_conf = (
        0.40 * core_conf +
        0.25 * brain_conf +
        0.15 * _clamp(rolling_acc, 0.50, 0.85) +
        0.20 * _clamp(stab_score, 0.50, 1.0)
    )
    fused_conf = _clamp(fused_conf * risk_factor, 0.50, 0.90)

    # fused edge
    fused_edge = core_edge
    if god_trust > 0.75 and price_misalign > 0.02:
        fused_edge *= 1.15
    if god_trust < 0.55 or price_misalign < -0.02:
        fused_edge *= 0.90
    fused_edge = max(0.0, fused_edge)

    # god bucket
    rel_score = (
        0.55 * fused_conf / max(brain_conf, 0.50) +
        0.45 * fused_edge / max(brain_edge, 0.01)
    )
    if rel_score < 0.95:
        god_bucket = "LOW"
    elif rel_score < 1.10:
        god_bucket = "MID"
    else:
        god_bucket = "HIGH"

    # risk label
    if fused_conf >= 0.78 and fused_edge >= 0.045 and god_bucket == "HIGH":
        risk_label = "PRIME"
    elif fused_conf >= 0.68 and fused_edge >= 0.030:
        risk_label = "STANDARD"
    else:
        risk_label = "SPECULATIVE"

    # kill-switch signals
    kill_soft = god_trust < 0.50 or stab_regime in ("UNSTABLE", "CRITICAL")
    kill_hard = (god_trust < 0.40) or (stab_regime == "CRITICAL" and anomaly > 0.70)

    fused = {
        "core_conf": round(core_conf, 3),
        "core_edge": round(core_edge, 3),
        "core_bucket": core_bucket,
        "brain_conf": round(brain_conf, 3),
        "brain_edge": round(brain_edge, 3),
        "brain_mode": brain_mode,
        "brain_trend": brain_trend,
        "brain_behavior_index": round(brain_bi, 3),
        "stab_score": round(stab_score, 3),
        "stab_regime": stab_regime,
        "anomaly": round(anomaly, 3),
        "daily_accuracy": round(daily_acc, 3),
        "rolling_accuracy": round(rolling_acc, 3),
        "model_drift": round(model_drift, 3),
        "market_odds": round(market_odds, 3),
        "implied_prob": round(implied_prob, 3),
        "price_misalign": round(price_misalign, 3),
        "risk_factor": round(risk_factor, 3),
        "god_trust": round(god_trust, 3),
        "fused_conf": round(fused_conf, 3),
        "fused_edge": round(fused_edge, 3),
        "god_bucket": god_bucket,
        "risk_label": risk_label,
        "new_mode": new_mode,
        "mode_changed": changed,
        "kill_soft": bool(kill_soft),
        "kill_hard": bool(kill_hard),
        "meta_context": meta_context,
    }
    return fused


# ================================================================
#  ⚠️ FAZ-14 – GLOBAL RISK ENGINE
# ================================================================
def _faz14_global_risk(fused: Dict[str, Any]) -> Dict[str, Any]:
    fc = _sf(fused.get("fused_conf"), 0.65)
    fe = _sf(fused.get("fused_edge"), 0.03)
    gt = _sf(fused.get("god_trust"), 0.7)
    drift = _sf(fused.get("model_drift"), 0.0)
    stab_regime = str(fused.get("stab_regime", "NORMAL")).upper()
    bucket = fused.get("god_bucket", "MID").upper()
    kill_soft = bool(fused.get("kill_soft", False))
    kill_hard = bool(fused.get("kill_hard", False))

    base_risk = 0.0
    base_risk += (1.0 - _clamp(fc, 0.50, 0.90)) * 0.30
    base_risk += (1.0 - _clamp(gt, 0.40, 0.95)) * 0.30
    base_risk += _clamp(drift, 0.0, 1.0) * 0.20

    if bucket == "LOW":
        base_risk += 0.12
    elif bucket == "HIGH":
        base_risk -= 0.05

    if stab_regime == "CRITICAL":
        base_risk += 0.25
    elif stab_regime == "UNSTABLE":
        base_risk += 0.15

    base_risk = _clamp(base_risk, 0.0, 1.0)

    if kill_hard or base_risk >= 0.80:
        risk_tier = "NO_BET"
    elif base_risk >= 0.60:
        risk_tier = "HIGH"
    elif base_risk >= 0.35:
        risk_tier = "MEDIUM"
    else:
        risk_tier = "LOW"

    if risk_tier == "LOW":
        stake_mult = 1.05
    elif risk_tier == "MEDIUM":
        stake_mult = 0.98
    elif risk_tier == "HIGH":
        stake_mult = 0.85
    else:
        stake_mult = 0.0

    risk = {
        "risk_tier": risk_tier,
        "base_risk": round(base_risk, 3),
        "stake_mult": round(stake_mult, 3),
        "hard_block": risk_tier == "NO_BET",
        "soft_block": kill_soft or risk_tier == "HIGH",
    }
    return risk


# ================================================================
#  🎲 FAZ-15 – SCENARIOS
# ================================================================
def _faz15_scenarios(fused: Dict[str, Any]) -> Dict[str, Any]:
    fc = _sf(fused.get("fused_conf"), 0.65)
    fe = _sf(fused.get("fused_edge"), 0.03)
    bucket = fused.get("god_bucket", "MID")
    risk_label = fused.get("risk_label", "STANDARD")

    baseline = fc
    optimistic = _clamp(fc + fe * 0.8, 0.50, 0.95)
    pessimistic = _clamp(fc - max(0.01, fe * 0.7), 0.40, 0.90)

    value_score = (optimistic - pessimistic) * 0.5 + fe

    scenario = {
        "baseline": {"win_prob": round(baseline, 3), "label": "Normal Senaryo"},
        "optimistic": {"win_prob": round(optimistic, 3), "label": "Pozitif Senaryo"},
        "pessimistic": {"win_prob": round(pessimistic, 3), "label": "Negatif Senaryo"},
        "value_score": round(value_score, 3),
        "bucket": bucket,
        "risk_label": risk_label,
    }
    return scenario


# ================================================================
#  📝 FAZ-16 – EXPLANATION ENGINE
# ================================================================
def _faz16_explain(
    core_output: Dict[str, Any],
    fused: Dict[str, Any],
    risk: Dict[str, Any],
    scenario: Dict[str, Any],
) -> Dict[str, Any]:

    league = str(_get_from_many(core_output, ["league", "lig"], "NBA")).upper()
    home = _get_from_many(core_output, ["home", "home_team"], "HOME")
    away = _get_from_many(core_output, ["away", "away_team"], "AWAY")
    market = _get_from_many(core_output, ["market_str", "selection_name"], "Seçim")

    fused_conf = _sf(fused.get("fused_conf"))
    fused_edge = _sf(fused.get("fused_edge"))
    god_bucket = fused.get("god_bucket")
    risk_tier = risk.get("risk_tier")
    base_risk = _sf(risk.get("base_risk"))
    risk_label = fused.get("risk_label")
    god_trust = _sf(fused.get("god_trust"))

    b = scenario["baseline"]["win_prob"]
    o = scenario["optimistic"]["win_prob"]
    p = scenario["pessimistic"]["win_prob"]

    header = f"{league} | {home} vs {away}\nSeçim: {market}\n"

    core_line = (
        f"🎯 GOD-MODE Konf: {fused_conf:.2f} | "
        f"Edge: {fused_edge:.3f} | Bucket: {god_bucket} | Risk: {risk_tier}"
    )

    trust_line = (
        f"🧠 Güven Skoru: {god_trust:.2f} | "
        f"Risk Etiketi: {risk_label} | Temel Risk: {base_risk:.2f}"
    )

    scenario_lines = (
        "📊 Senaryolar:\n"
        f"  • Normal:  WinProb ≈ {b:.2f}\n"
        f"  • Pozitif: WinProb ≈ {o:.2f}\n"
        f"  • Negatif: WinProb ≈ {p:.2f}"
    )

    # Tavsiye
    if risk_tier == "NO_BET":
        advice = (
            "🚫 <b>NO-BET</b>\n"
            "Stability / drift / risk gerekçesiyle GOD-LAYER bu maçı blokluyor."
        )
    elif risk_tier == "HIGH":
        advice = (
            "⚠️ <b>YÜKSEK RİSK</b>\n"
            "Stake düşür, kuponda küçük ağırlıkla değerlendir."
        )
    elif risk_tier == "MEDIUM":
        advice = (
            "⚖️ <b>ORTA RİSK</b>\n"
            "Makul sinyal, kupon içinde kullanılabilir."
        )
    else:
        advice = (
            "🛡️ <b>DÜŞÜK RİSK (PRIME)</b>\n"
            "Çok temiz sinyal, kupon çekirdeği olabilir."
        )

    return {
        "header": header,
        "core_line": core_line,
        "trust_line": trust_line,
        "scenario_lines": scenario_lines,
        "advice": advice,
    }


# ================================================================
#  📦 FAZ-17 – GOD-STATE PACKAGING
# ================================================================
def _faz17_build_god_state(
    core_output: Dict[str, Any],
    fused: Dict[str, Any],
    risk: Dict[str, Any],
    scenario: Dict[str, Any],
    explain: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "version": GOD_VERSION,
        "ts": int(time.time()),
        "core_output": core_output,
        "fused": fused,
        "risk": risk,
        "scenario": scenario,
        "explain": explain,
    }


# ================================================================
#  🚀 PUBLIC API
# ================================================================
def faz13_god_pipeline(
    core_output: Dict[str, Any],
    brain: Dict[str, Any],
    f10_state: Dict[str, Any],
    f11_summary: Dict[str, Any],
    f12_decision: Dict[str, Any],
    history_samples: List[Dict[str, Any]],
    market_info: Dict[str, Any],
    meta_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    fused = _faz134_signal_fusion(
        core_output,
        brain,
        f10_state,
        f11_summary,
        f12_decision,
        history_samples,
        market_info,
        meta_context,
    )

    risk = _faz14_global_risk(fused)
    scenario = _faz15_scenarios(fused)
    explain = _faz16_explain(core_output, fused, risk, scenario)
    god_state = _faz17_build_god_state(core_output, fused, risk, scenario, explain)

    return god_state


def faz13_god_text(core_output: Dict[str, Any], god_state: Dict[str, Any]) -> str:
    fused = god_state["fused"]
    explain = god_state["explain"]

    header = explain["header"]
    core_line = explain["core_line"]
    trust_line = explain["trust_line"]
    scenario_lines = explain["scenario_lines"]
    advice = explain["advice"]

    version_line = f"\n\n🔁 GOD-LAYER Version: <b>{GOD_VERSION}</b>"

    return (
        "🧠 <b>FAZ-13 GOD-MODE ÖZETİ</b>\n\n"
        f"{header}\n"
        f"{core_line}\n"
        f"{trust_line}\n\n"
        f"{scenario_lines}\n\n"
        f"{advice}"
        f"{version_line}"
    )
