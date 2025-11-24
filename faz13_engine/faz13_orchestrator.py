# ================================================================
# ⭐ FAZ-13 ORCHESTRATOR — v13.1 + v13.2 + v13.3 FUSION EDITION ⭐
# ================================================================

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
import re
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# ================================================================
# 🔌 FAZ-11 / FAZ-12 BAĞLANTISI
# ================================================================
from faz11_engine.faz11_feedback import faz11_last_summary
from faz12_engine.faz12_autoadjust import faz12_run_once

# ================================================================
# 🔹 FUSION INPUT – TEK STANDARD FORMAT
# ================================================================
@dataclass
class FusionInput:
    source: str
    league: str
    home: str
    away: str
    market: str
    line: Optional[float]
    side: str
    odds: Optional[float]
    start_time: Optional[str] = None
    meta: Dict[str, Any] = None

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}

# ================================================================
# 🔧 BASIC HELPERS
# ================================================================
def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        return float(str(x).replace(",", "."))
    except Exception:
        return default

# ================================================================
# 1️⃣ MANUAL NORMALIZATION
# ================================================================
def normalize_manual_text(text: str, default_league="NBA") -> FusionInput:
    raw = text.strip()
    parts = raw.split()
    if not parts:
        raise ValueError("Boş komut")

    if parts[0].startswith("/"):
        parts = parts[1:]

    if len(parts) < 5:
        raise ValueError("Format: /mac HOME AWAY LINE SIDE ORAN")

    home = parts[0].upper()
    away = parts[1].upper()
    line = _safe_float(parts[2])
    side = parts[3].upper()
    odds = _safe_float(parts[4])
    market = "FT TOTAL"

    return FusionInput(
        source="manual",
        league=default_league,
        home=home,
        away=away,
        market=market,
        line=line,
        side=side,
        odds=odds,
        meta={"raw": raw},
    )

# ================================================================
# 2️⃣ API NORMALIZATION
# ================================================================
def normalize_api_data(match: Dict[str, Any]) -> FusionInput:
    return FusionInput(
        source=match.get("source", "api"),
        league=str(match.get("league", "UNKNOWN")),
        home=str(match.get("home", "HOME")).upper(),
        away=str(match.get("away", "AWAY")).upper(),
        market=str(match.get("market", "FT TOTAL")),
        line=_safe_float(match.get("line")),
        side=str(match.get("side", "U")).upper(),
        odds=_safe_float(match.get("odds")),
        start_time=match.get("start_time"),
        meta=match,
    )

# ================================================================
# 3️⃣ OCR / VISUAL NORMALIZATION
# ================================================================
def normalize_visual_meta(text: str, default_league="NBA") -> FusionInput:
    tokens = re.findall(r"[A-Z]{2,4}", text)
    nums = re.findall(r"\d+[\.,]?\d*", text)

    odds_candidates = [n for n in nums if _safe_float(n, 0) >= 1.10]
    line_candidates = [n for n in nums if _safe_float(n, 0) < 1000]

    side = "U"
    if re.search(r"(OVER|ÜST|O)\b", text, re.I): side = "O"
    if re.search(r"(UNDER|ALT|U)\b", text, re.I): side = "U"

    home = tokens[0] if len(tokens) >= 1 else "HOME"
    away = tokens[1] if len(tokens) >= 2 else "AWAY"

    return FusionInput(
        source="visual",
        league=default_league,
        home=home,
        away=away,
        market="FT TOTAL",
        line=_safe_float(line_candidates[0]) if line_candidates else None,
        side=side,
        odds=_safe_float(odds_candidates[-1]) if odds_candidates else None,
        meta={"raw_ocr": text},
    )

# ================================================================
# ⚙️ FAZ-13.1 ESTIMATION (conf / edge / bucket)
# ================================================================
def _estimate_conf_edge_bucket(fi: FusionInput):
    if fi.odds:
        implied = max(0.30, min(1 / fi.odds, 0.80))
    else:
        implied = 0.55

    base = 0.55 + (0.15 * (0.5 - abs(implied - 0.5)) / 0.5)

    if fi.league.upper() in ("NBA", "EUROLEAGUE", "EL"):
        base += 0.02
    if "Q" in fi.market.upper():
        base -= 0.02

    if fi.source == "manual": base += 0.01
    if fi.source == "visual": base -= 0.02

    base = max(0.50, min(base, 0.78))
    edge = base - implied

    if base >= 0.68 and edge >= 0.045:
        bucket = "HIGH"
    elif base >= 0.60 and edge >= 0.02:
        bucket = "MID"
    else:
        bucket = "LOW"

    risk = "HIGH" if bucket == "HIGH" else ("MID" if bucket == "MID" else "LOW")
    score = base * 100 + edge * 80

    return {
        "pred_conf": round(base, 3),
        "pred_edge": round(edge, 3),
        "pred_bucket": bucket,
        "risk": risk,
        "implied_p": round(implied, 3),
        "score": round(score, 1),
    }

# ================================================================
# 🔁 FAZ-10/11/12 PIPELINE
# ================================================================
def _auto_faz_pipeline(pred_conf, pred_edge, pred_bucket, real_result=None):
    try:
        summary = faz11_last_summary()
        f11 = summary.get("last")
    except:
        f11 = None

    decision = None
    if f11:
        f10 = {"stability": float(f11.get("daily_accuracy", 0.7))}
        try:
            decision = faz12_run_once(f10, f11)
        except Exception as e:
            log.warning(f"[FAZ-12] error: {e}")

    return {
        "f11_last": f11,
        "f12_decision": decision,
        "pred_conf": pred_conf,
        "pred_edge": pred_edge,
        "pred_bucket": pred_bucket,
    }

# ================================================================
# 🧠 ANA SİNYAL HESABI
# ================================================================
def compute_faz13_signal(fi: FusionInput):
    est = _estimate_conf_edge_bucket(fi)
    pipe = _auto_faz_pipeline(est["pred_conf"], est["pred_edge"], est["pred_bucket"])
    return {"fusion": asdict(fi), "est": est, "pipeline": pipe}


# ================================================================
# 🎨 TELEGRAM FORMAT
# ================================================================
def format_faz13_signal_html(signal):
    f = signal["fusion"]
    e = signal["est"]
    p = signal["pipeline"]

    mode = "-"
    if p["f12_decision"]:
        mode = p["f12_decision"].get("new_mode", "-")

    lines = []
    lines.append("🔥 <b>FAZ-13 Kupon Sinyali</b>")
    lines.append(f"🏀 {f['home']} - {f['away']} ({f['league']})")
    lines.append(f"{f['market']} | {f['line']} {f['side']} @ {f['odds']}")
    lines.append("")
    lines.append("📊 <b>Model</b>")
    lines.append(f"Conf={e['pred_conf']} Edge={e['pred_edge']} Bucket={e['pred_bucket']} Risk={e['risk']}")
    lines.append(f"Score={e['score']}")
    lines.append("")
    lines.append("🧠 <b>FAZ-11/12</b>")
    if p["f11_last"]:
        lines.append(f"Daily Acc={p['f11_last'].get('daily_accuracy')}")
        lines.append(f"Drift={p['f11_last'].get('model_drift')}")
    if p["f12_decision"]:
        lines.append(f"Mode={mode}")
    return "\n".join(lines)


# ================================================================
# 🚀 TEK MATCH ENTRY
# ================================================================
def run_faz13_auto_pipeline(fi: FusionInput) -> str:
    sig = compute_faz13_signal(fi)
    return format_faz13_signal_html(sig)

# ================================================================
# 13.2 — MULTI VISUAL / MULTI MATCH FUSION
# ================================================================
def faz13_multi_visual(images_text: List[str], default_league="NBA") -> List[str]:
    """Bir maç için birden fazla OCR çıktısını normalize eder."""
    outs = []
    for txt in images_text:
        try:
            fi = normalize_visual_meta(txt, default_league)
            outs.append(run_faz13_auto_pipeline(fi))
        except Exception as e:
            log.error(f"[FAZ-13 MULTI VISUAL] {e}")
    return outs

def faz13_multi_matches(match_list: List[Dict[str, Any]]) -> List[str]:
    """Birden fazla maç → her biri için pipeline."""
    outs = []
    for m in match_list:
        try:
            fi = normalize_api_data(m)
            outs.append(run_faz13_auto_pipeline(fi))
        except Exception:
            pass
    return outs

# ================================================================
# 13.3 — TRIPLE FUSION (manual + api + visual birleşimi)
# ================================================================
def triple_fusion(manual_text=None, api_match=None, ocr_text=None, default_league="NBA") -> str:
    """3 kaynağı tek maçta birleştirir."""
    fi = None

    if manual_text:
        fi = normalize_manual_text(manual_text, default_league)

    if api_match:
        fi_api = normalize_api_data(api_match)
        if fi is None:
            fi = fi_api
        else:
            fi.odds = fi_api.odds or fi.odds
            fi.line = fi_api.line or fi.line
            fi.market = fi_api.market or fi.market

    if ocr_text:
        fi_ocr = normalize_visual_meta(ocr_text, default_league)
        fi.odds = fi_ocr.odds or fi.odds
        fi.line = fi_ocr.line or fi.line

    return run_faz13_auto_pipeline(fi)
