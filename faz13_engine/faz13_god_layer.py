import json
from typing import Any, Dict

# ================================================================
# 🧩 FAZ-13 ORCHESTRATOR IMPORTLARI (KRİTİK)
# ================================================================
# normalize_manual_text / visual / api = fusion_input üretir
# run_faz13_auto_pipeline = main.py tarafından beklenen signature:
#     run_faz13_auto_pipeline(source_type, fusion_input)
# Bu yüzden NEW GOD-LAYER buna göre ayarlanmıştır.
# ================================================================

from faz13_engine.faz13_orchestrator import (
    normalize_manual_text,
    normalize_visual_meta,
    normalize_api_data,
    run_faz13_auto_pipeline,
)

# ================================================================
# 🔧 INTERNAL HELPERS
# ================================================================

def _safe_float(val: Any):
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except:
        return None


def _direction_label(direction: str | None) -> str:
    if not direction:
        return "—"
    d = direction.upper()
    if d == "U":
        return "ALT"
    if d == "O":
        return "ÜST"
    return d


# ================================================================
# 🔢 CONF / EDGE MOTORU (ESKİ DOSYANIN UYARLANMIŞ YENİ HALİ)
# ================================================================
def _estimate_conf_edge(meta: Dict[str, Any]) -> Dict[str, Any]:
    league = (meta.get("league") or "NBA").upper()
    direction = meta.get("direction")
    line = meta.get("line")
    odds = meta.get("odds")

    base_conf = 0.58
    base_edge = 0.030

    # line + U/O varsa güven artar
    if direction and line is not None:
        base_conf += 0.04
        base_edge += 0.006

    # oran etkisi
    if isinstance(odds, (int, float, str)):
        try:
            o = float(str(odds).replace(",", "."))
            if o < 1.40:
                base_conf += 0.02
                base_edge -= 0.004
            elif o < 1.60:
                base_conf += 0.01
                base_edge -= 0.002
            elif o > 1.90:
                base_conf -= 0.02
                base_edge += 0.004
            elif o > 1.75:
                base_conf -= 0.01
                base_edge += 0.002
        except:
            pass

    # Lig bonusu
    if league in ("EUROLEAGUE", "EL"):
        base_edge += 0.002
    elif league in ("BSL", "TBL"):
        base_edge += 0.001

    conf = max(0.50, min(0.80, base_conf))
    edge = max(0.010, min(0.060, base_edge))

    conf_ref = 0.63
    edge_ref = 0.035
    score = 0.6 * (conf / conf_ref) + 0.4 * (edge / edge_ref)

    if score < 0.95:
        bucket = "LOW"
    elif score < 1.10:
        bucket = "MID"
    else:
        bucket = "HIGH"

    profile = "SAFE" if bucket == "LOW" else ("BAL" if bucket == "MID" else "AGG")

    return {
        "conf": round(conf, 3),
        "edge": round(edge, 3),
        "bucket": bucket,
        "profile": profile,
        "score": round(score, 3),
    }


# ================================================================
# 📝 TEXT BUILDER (ESKİ DOSYANIN GÜNCEL HİBRİD METİN MOTORU)
# ================================================================
def _build_core_text(source_type: str, meta: Dict[str, Any], pred: Dict[str, Any]) -> str:

    league = meta.get("league", "NBA")
    home = meta.get("home", "HOME")
    away = meta.get("away", "AWAY")
    market = meta.get("market", "FT TOTAL")
    line = meta.get("line")
    direction = meta.get("direction")
    odds = meta.get("odds")

    dir_label = _direction_label(direction)

    if isinstance(line, (int, float)):
        line_part = f"{float(line):.1f}"
    else:
        line_part = "—"

    if isinstance(odds, (int, float)):
        odds_part = f"{float(odds):.2f}"
    else:
        odds_part = "—"

    headers = {
        "manual": "📝 <b>FAZ-13 MANUAL GOD-LAYER</b>",
        "visual": "📸 <b>FAZ-13 VISUAL GOD-LAYER</b>",
        "live":   "📡 <b>FAZ-13 LIVE GOD-LAYER</b>",
    }

    header = headers.get(source_type, "🤖 <b>FAZ-13 GOD-LAYER</b>")

    body = (
        f"{header}\n\n"
        f"Lig   : <b>{league}</b>\n"
        f"Maç   : <b>{home} vs {away}</b>\n"
        f"Pazar : <b>{market}</b>\n"
        f"Seçim : <b>{dir_label} {line_part}</b> @ <b>{odds_part}</b>\n\n"
        f"Güven : <b>{pred['conf']}</b>\n"
        f"Edge  : <b>{pred['edge']}</b>\n"
        f"Risk  : <b>{pred['profile']}</b> | Bucket: <b>{pred['bucket']}</b>\n\n"
    )

    debug_meta = {
        "league": league,
        "home": home,
        "away": away,
        "market": market,
        "line": line,
        "direction": direction,
        "odds": odds,
        "score": pred["score"],
        "bucket": pred["bucket"],
        "profile": pred["profile"],
    }

    try:
        dbg = json.dumps(debug_meta, ensure_ascii=False, indent=2)
        body += "<code>" + dbg + "</code>"
    except:
        pass

    return body


# ================================================================
# 🔥 GOD-LAYER ANA MOTOR (FINAL VERSION)
# ================================================================
def run_faz13_with_god_layer(source_type: str, fusion_input: Dict[str, Any]) -> str:
    """
    Tüm /mac, /mac_img, /live13 çağrıları buraya bağlanır.
    Fusion_input:
      - normalize_manual_text
      - normalize_visual_meta
      - normalize_api_data
    çıktısıdır.
    """

    meta = dict(fusion_input or {})
    meta.setdefault("league", "NBA")
    meta.setdefault("market", "FT TOTAL")

    # ❗ KLASİK FAZ-13 PIPELINE (main.py bunu bekliyor)
    try:
        _ = run_faz13_auto_pipeline(source_type, meta)
    except:
        pass  # crash engelle

    # ❗ GOD-LAYER tahmini
    pred = _estimate_conf_edge(meta)

    # ❗ Metin üret
    text = _build_core_text(source_type, meta, pred)

    return text
