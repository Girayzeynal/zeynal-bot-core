import os
import json
import time
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict

# ================================================================
# 🧩 FAZ-13 ORCHESTRATOR IMPORTLARI
# ================================================================
from faz13_engine.faz13_orchestrator import (
    normalize_manual_text,
    normalize_visual_meta,
    normalize_api_data,
    run_faz13_auto_pipeline,
)

# ================================================================
# ⚙️ FAZ-7.9 HAFIZA AYARLARI
# ================================================================
FAZ7_MEMORY_PATH = os.getenv("FAZ7_MEMORY_PATH", "/data/faz7/faz7_memory.json")
FAZ7_MAX_RECORDS = int(os.getenv("FAZ7_MAX_RECORDS", "1000"))
FAZ7_MAX_DAYS = int(os.getenv("FAZ7_MAX_DAYS", "7"))  # 7 günlük pencere


# ================================================================
# 🔧 INTERNAL HELPERS
# ================================================================
def _safe_float(val: Any):
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except Exception:
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


def _now_ts() -> int:
    return int(time.time())


# ================================================================
# 🔢 CONF / EDGE MOTORU
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
        except Exception:
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
# 🧱 TEXT BUILDER
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
    except Exception:
        pass

    return body


# ================================================================
# 📚 FAZ-7.9 MEMORY ENGINE
# ================================================================
def _faz7_load_raw() -> list[dict]:
    path = Path(FAZ7_MEMORY_PATH)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _faz7_save_raw(items: list[dict]) -> None:
    path = Path(FAZ7_MEMORY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
    except Exception:
        pass


def faz7_register_prediction(source_type: str, meta: Dict[str, Any], pred: Dict[str, Any]) -> None:
    """
    Her tahmin sonrası hafızaya tek kayıt atar.
    Şimdilik maç sonucu bilinmiyor → result=None
    """
    rec = {
        "ts": _now_ts(),
        "source": source_type,
        "league": meta.get("league"),
        "home": meta.get("home"),
        "away": meta.get("away"),
        "market": meta.get("market"),
        "line": meta.get("line"),
        "direction": meta.get("direction"),
        "odds": meta.get("odds"),
        "conf": pred.get("conf"),
        "edge": pred.get("edge"),
        "bucket": pred.get("bucket"),
        "profile": pred.get("profile"),
        "score": pred.get("score"),
        "result": None,
    }

    items = _faz7_load_raw()

    # Eski kayıtları temizle (7 gün)
    cutoff = _now_ts() - FAZ7_MAX_DAYS * 86400
    items = [r for r in items if int(r.get("ts", 0)) >= cutoff]

    items.append(rec)

    # Max kayıt limiti
    if len(items) > FAZ7_MAX_RECORDS:
        items = items[-FAZ7_MAX_RECORDS:]

    _faz7_save_raw(items)


def _faz7_compute_stats(records: list[dict]) -> Dict[str, Any]:
    n = len(records)
    if n == 0:
        return {
            "count": 0,
            "tci": 0.0,
            "noise": 0.0,
            "behavior_index": 0.0,
            "trend": "FLAT",
            "vol": 0.0,
            "strategy_mode": "BAL",
        }

    edges = [float(r.get("edge", 0.03) or 0.03) for r in records]
    confs = [float(r.get("conf", 0.6) or 0.6) for r in records]

    avg_edge = mean(edges)
    avg_conf = mean(confs)
    vol = pstdev(edges) if len(edges) > 1 else 0.0

    # TCI: edge & conf karışımı
    tci = 0.6 * avg_edge + 0.4 * max(0.0, avg_conf - 0.5)

    # Noise: edge oynaklığı
    noise = vol

    # Behavior index: 0–1 arası normalize
    behavior_index = max(0.0, min(1.0, (avg_conf - 0.5) * 5.0))

    # Trend: çok kaba
    if len(edges) >= 5:
        first = mean(edges[: len(edges) // 2])
        last = mean(edges[len(edges) // 2 :])
        if last > first + 0.003:
            trend = "UP"
        elif last < first - 0.003:
            trend = "DOWN"
        else:
            trend = "FLAT"
    else:
        trend = "FLAT"

    # Strategy mode
    if avg_conf >= 0.66 and avg_edge >= 0.035:
        strategy_mode = "AGG"
    elif avg_conf <= 0.58 and avg_edge <= 0.030:
        strategy_mode = "SAFE"
    else:
        strategy_mode = "BAL"

    return {
        "count": n,
        "tci": round(tci, 3),
        "noise": round(noise, 3),
        "behavior_index": round(behavior_index, 3),
        "trend": trend,
        "vol": round(vol, 4),
        "strategy_mode": strategy_mode,
    }


def faz7_get_status_snapshot() -> Dict[str, Any]:
    recs = _faz7_load_raw()
    stats = _faz7_compute_stats(recs)
    stats["memory_path"] = FAZ7_MEMORY_PATH
    return stats


# ================================================================
# ⚠️ FAZ-10 HARDSYNC
# ================================================================
def faz10_hardsync(brain: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    brain: faz7_get_status_snapshot() çıktısı
    """
    if brain is None:
        brain = faz7_get_status_snapshot()

    tci = float(brain.get("tci", 0.0) or 0.0)
    noise = float(brain.get("noise", 0.0) or 0.0)
    behavior_index = float(brain.get("behavior_index", 0.0) or 0.0)

    # Regime
    if tci < 0.01 and noise < 0.05:
        regime = "CALM"
    elif tci < 0.02 and noise < 0.15:
        regime = "NORMAL"
    elif tci > 0.04 or noise > 0.30:
        regime = "UNSTABLE"
    else:
        regime = "VOLATILE"

    # Stability & anomaly 0–1 arası
    stability_score = max(0.0, min(1.0, 1.0 - (0.7 * noise + 8.0 * tci)))
    anomaly_level = max(0.0, min(1.0, 0.6 * noise + 6.0 * tci))

    # Mode
    if stability_score >= 0.75 and anomaly_level < 0.25:
        suggested_mode = "AGG"
    elif stability_score <= 0.45 or anomaly_level > 0.6:
        suggested_mode = "SAFE"
    else:
        suggested_mode = "BAL"

    out = dict(brain)
    out.update(
        {
            "regime": regime,
            "stability_score": round(stability_score, 3),
            "anomaly_level": round(anomaly_level, 3),
            "suggested_mode": suggested_mode,
        }
    )
    return out


def faz10_hardsync_status() -> Dict[str, Any]:
    brain = faz7_get_status_snapshot()
    return faz10_hardsync(brain)


# ================================================================
# 🔥 GOD-LAYER ANA MOTOR
# ================================================================
def run_faz13_with_god_layer(source_type: str, fusion_input: Dict[str, Any]) -> str:
    """
    Tüm /mac, /mac_img, /live13 çağrıları buraya bağlanır.
    fusion_input:
      - normalize_manual_text
      - normalize_visual_meta
      - normalize_api_data
    çıktısıdır.
    """
    meta = dict(fusion_input or {})
    meta.setdefault("league", "NBA")
    meta.setdefault("market", "FT TOTAL")

    # 1) Klasik FAZ-13 pipeline (şimdilik passthrough)
    try:
        _ = run_faz13_auto_pipeline(source_type, meta)
    except Exception:
        pass  # crash engelle

    # 2) GOD-LAYER tahmini
    pred = _estimate_conf_edge(meta)

    # 3) FAZ-7.9 hafızaya kaydet
    try:
        faz7_register_prediction(source_type, meta, pred)
    except Exception:
        # hafıza hiçbir zaman botu düşürmemeli
        pass

    # 4) Metin üret
    text = _build_core_text(source_type, meta, pred)
    return text
