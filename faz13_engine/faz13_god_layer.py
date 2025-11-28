import json
from typing import Any, Dict

from faz13_engine.faz13_orchestrator import (
    normalize_manual_text,
    normalize_visual_meta,
    normalize_api_data,
    run_faz13_auto_pipeline,
)

# ================================================================
# 🔢 Basit ama akıllı conf/edge tahmin motoru
# ================================================================
def _estimate_conf_edge(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-13 GOD-LAYER:
    - line + direction varsa → base_conf yukarı
    - oran düşükse → güven artar, edge azalır
    - oran yüksekse → güven azalır, edge artar
    - lig bazlı minik edge tweak
    - çıktılar: conf, edge, bucket, profile, score
    """
    league = (meta.get("league") or "NBA").upper()
    direction = meta.get("direction")
    line = meta.get("line")
    odds = meta.get("odds")

    # Başlangıç değerleri
    base_conf = 0.58
    base_edge = 0.030

    # Seçim netliği (line + U/O tam ise güven artar)
    if direction and line is not None:
        base_conf += 0.04
        base_edge += 0.006

    # Oran etkisi
    if isinstance(odds, (int, float, str)):
        try:
            o = float(str(odds).replace(",", "."))
            # 1.35 - 1.55 arası → “favori”: güven ↑ edge ↓
            if o < 1.40:
                base_conf += 0.02
                base_edge -= 0.004
            elif o < 1.60:
                base_conf += 0.01
                base_edge -= 0.002
            # 1.80+ → underdog / riskli: güven ↓ edge ↑
            elif o > 1.90:
                base_conf -= 0.02
                base_edge += 0.004
            elif o > 1.75:
                base_conf -= 0.01
                base_edge += 0.002
        except Exception:
            pass

    # Lig bazlı minik edge tweak
    if league in ("EUROLEAGUE", "EL"):
        base_edge += 0.002
    elif league in ("BSL", "TBL"):
        base_edge += 0.001

    # Clamp
    conf = max(0.50, min(0.80, base_conf))
    edge = max(0.010, min(0.060, base_edge))

    # Basit score → bucket
    # referans: conf_ref = 0.63, edge_ref = 0.035
    conf_ref = 0.63
    edge_ref = 0.035
    score = 0.6 * (conf / conf_ref) + 0.4 * (edge / edge_ref)

    if score < 0.95:
        bucket = "LOW"
    elif score < 1.10:
        bucket = "MID"
    else:
        bucket = "HIGH"

    # Bucket’tan risk profili
    if bucket == "LOW":
        profile = "SAFE"
    elif bucket == "MID":
        profile = "BAL"
    else:
        profile = "AGG"

    return {
        "conf": round(conf, 3),
        "edge": round(edge, 3),
        "bucket": bucket,
        "profile": profile,
        "score": round(score, 3),
    }


# ================================================================
# 🧱 Metin inşa helper'ları
# ================================================================
def _direction_label(direction: str | None) -> str:
    if not direction:
        return "—"
    d = direction.upper()
    if d == "U":
        return "ALT"
    if d == "O":
        return "ÜST"
    return d


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

    if source_type == "manual":
        header = "📝 <b>FAZ-13 MANUAL GOD-LAYER</b>\n\n"
    elif source_type == "visual":
        header = "📸 <b>FAZ-13 VISUAL GOD-LAYER</b>\n\n"
    elif source_type == "live":
        header = "📡 <b>FAZ-13 LIVE GOD-LAYER</b>\n\n"
    else:
        header = "🤖 <b>FAZ-13 GOD-LAYER</b>\n\n"

    body = (
        f"Lig   : <b>{league}</b>\n"
        f"Maç   : <b>{home} vs {away}</b>\n"
        f"Pazar : <b>{market}</b>\n"
        f"Seçim : <b>{dir_label} {line_part}</b> @ <b>{odds_part}</b>\n\n"
        f"Güven : <b>{pred['conf']:.3f}</b>\n"
        f"Edge  : <b>{pred['edge']:.3f}</b>\n"
        f"Risk  : <b>{pred['profile']}</b> | Bucket: <b>{pred['bucket']}</b>\n"
    )

    # Küçük meta debug (JSON)
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
        body += "\n<code>" + dbg + "</code>"
    except Exception:
        pass

    return header + body


# ================================================================
# 🔥 GOD-LAYER ANA FONKSİYON
# ================================================================
def run_faz13_with_god_layer(source_type: str, fusion_input: Dict[str, Any]) -> str:
    """
    Tüm /mac, /mac_img, /live13 çağrıları buraya bağlanır.
    - source_type: "manual" | "visual" | "live" | ...
    - fusion_input: normalize_* fonksiyonlarından gelen meta dict

    1) FAZ-13 klasik pipeline'ı çalıştırır (ilerde genişler)
    2) GOD-LAYER tahmini üretir (conf/edge/bucket/profile)
    3) Tek parça insan okunur text döner
    """
    meta = dict(fusion_input or {})
    meta.setdefault("league", "NBA")
    meta.setdefault("market", "FT TOTAL")

    # FAZ-13 klasik pipeline (şimdilik sadece passthrough, ileride genişleyebilir)
    _ = run_faz13_auto_pipeline(source_type, meta)

    # GOD-LAYER tahmin
    pred = _estimate_conf_edge(meta)

    # Text inşası
    text = _build_core_text(source_type, meta, pred)
    return text
