import os
import json
import logging
import time
import re
from typing import Any, Dict, Optional, List

import telebot
from telebot import types
from flask import Flask, request

# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hoopbrain-main")

# ================================================================
# 🔧 CONFIG & GLOBALS
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ENGINEERING_MODE = os.getenv("ENGINEERING_MODE", "ON").upper() == "ON"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

PORT = int(os.getenv("PORT", "8080"))

DATA_DIR = os.getenv("DATA_DIR", "/data")
FAZ7_DIR = os.path.join(DATA_DIR, "faz7")
os.makedirs(FAZ7_DIR, exist_ok=True)

FAZ7_MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")
FAZ11_HISTORY_FILE = os.path.join(FAZ7_DIR, "faz11_history.json")

# ================================================================
# 🔧 SAFE IMPORT HELPERS
# ================================================================
def _safe_import(module_path: str, attrs: Optional[list[str]] = None):
    try:
        module = __import__(module_path, fromlist=attrs or [])
    except Exception as e:
        log.warning("Modül import edilemedi: %s (%s)", module_path, e)
        if not attrs:
            return None
        return {name: None for name in attrs}

    if not attrs:
        return module

    out: Dict[str, Any] = {}
    for name in attrs:
        try:
            out[name] = getattr(module, name)
        except AttributeError:
            log.warning("Attr yok: %s.%s", module_path, name)
            out[name] = None
    return out


# ================================================================
# 🔧 IMPORT FAZ MODULES
# ================================================================
_faz10 = _safe_import("faz10_engine.faz10_stability", ["faz10_stability_check"])
faz10_stability_check = (_faz10 or {}).get("faz10_stability_check")

_faz11 = _safe_import("faz11_engine.faz11_feedback", ["faz11_feedback", "faz11_last_summary"])
faz11_feedback = (_faz11 or {}).get("faz11_feedback")
faz11_last_summary = (_faz11 or {}).get("faz11_last_summary")

_faz12 = _safe_import("faz12_engine.faz12_autoadjust", ["faz12_run_once", "faz12_auto_profile"])
faz12_run_once = (_faz12 or {}).get("faz12_run_once")
faz12_auto_profile = (_faz12 or {}).get("faz12_auto_profile")

_faz13_orch = _safe_import(
    "faz13_engine.faz13_orchestrator",
    [
        "normalize_manual_text",
        "normalize_visual_meta",
        "normalize_api_data",
        "run_faz13_auto_pipeline",
        "faz13_daily_coupon",
        "faz13_upcoming_coupon",
        "faz13_league_coupon",
        "faz13_live_coupon",
    ],
)
normalize_manual_text = (_faz13_orch or {}).get("normalize_manual_text")
normalize_visual_meta = (_faz13_orch or {}).get("normalize_visual_meta")
normalize_api_data = (_faz13_orch or {}).get("normalize_api_data")
run_faz13_auto_pipeline = (_faz13_orch or {}).get("run_faz13_auto_pipeline")
faz13_daily_coupon = (_faz13_orch or {}).get("faz13_daily_coupon")
faz13_upcoming_coupon = (_faz13_orch or {}).get("faz13_upcoming_coupon")
faz13_league_coupon = (_faz13_orch or {}).get("faz13_league_coupon")
faz13_live_coupon = (_faz13_orch or {}).get("faz13_live_coupon")

_faz13_god = _safe_import("faz13_engine.faz13_god_layer", ["run_faz13_with_god_layer"])
run_faz13_with_god_layer = (_faz13_god or {}).get("run_faz13_with_god_layer")

_faz17 = _safe_import("faz17_engine.faz17_market_adjust", ["faz17_market_adjust"])
faz17_market_adjust = (_faz17 or {}).get("faz17_market_adjust")

# Ultra OCR Engine v3 opsiyonel import
_faz13_ocr = _safe_import("faz13_engine.ultra_ocr_v3", ["ultra_ocr_engine_v3"])
_ext_ultra_ocr_engine_v3 = (_faz13_ocr or {}).get("ultra_ocr_engine_v3")

# ================================================================
# 🔧 GLOBAL VISUAL / META STATE (FAZ-22 + STACK)
# ================================================================
# Son OCR sonucu (tek shot)
LAST_OCR_TEXT: str | None = None
LAST_OCR_META: Dict[str, Any] = {}

# Visual Stack: birden fazla maç görseli → FAZ-22 META ENGINE için
VISUAL_STACK: List[Dict[str, Any]] = []


def add_visual_item(text: str, meta: Dict[str, Any]) -> None:
    """
    Her OCR sonrası çalışır: text + meta'yı stack'e yazar.
    Fly.io 512 MB için hafif tutulur (sadece son ~128 kayıt).
    """
    global LAST_OCR_TEXT, LAST_OCR_META, VISUAL_STACK
    text = (text or "").strip()
    if not text:
        return

    item = {
        "text": text,
        "meta": meta or {},
        "ts": int(time.time()),
    }
    VISUAL_STACK.append(item)
    # Stack'i sınırlı tut (hafif bellek)
    if len(VISUAL_STACK) > 128:
        VISUAL_STACK = VISUAL_STACK[-128:]

    LAST_OCR_TEXT = text
    LAST_OCR_META = meta or {}


def reset_visual_stack() -> None:
    global VISUAL_STACK, LAST_OCR_TEXT, LAST_OCR_META
    VISUAL_STACK = []
    LAST_OCR_TEXT = None
    LAST_OCR_META = {}


def visual_stack_status_text() -> str:
    n = len(VISUAL_STACK)
    if n == 0:
        return "📂 Visual stack boş. Henüz işlenmiş görsel yok."

    last = VISUAL_STACK[-1]
    meta = last.get("meta", {}) or {}
    ts = last.get("ts")
    engine = meta.get("engine", "-")
    prob = meta.get("prob_score", 0.0)

    lines: List[str] = []
    lines.append("📂 <b>FAZ-13 Visual Stack Durumu</b>")
    lines.append(f"Toplam item: <b>{n}</b>")
    if ts:
        dt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))
        lines.append(f"Son güncelleme (UTC): <b>{dt_str}</b>")
    lines.append(
        "Son OCR: engine=<b>{engine}</b> | score=<b>{prob:.3f}</b>".format(
            engine=engine,
            prob=float(prob or 0.0),
        )
    )
    if LAST_OCR_TEXT:
        sample = LAST_OCR_TEXT.replace("\n", " ")
        if len(sample) > 120:
            sample = sample[:117] + "..."
        lines.append("")
        lines.append("<b>Son OCR metin örneği:</b>")
        lines.append(sample)

    return "\n".join(lines)


# ================================================================
# 🔧 FALLBACKS & MEMORY HELPERS
# ================================================================
def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return None


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("JSON kaydedilemedi: %s (%s)", path, e)


# FAZ-7.9 Memory
def faz7_load_memory() -> Dict[str, Any]:
    mem = _load_json(FAZ7_MEMORY_FILE, {})
    if not isinstance(mem, dict):
        mem = {}
    if "stats" not in mem or not isinstance(mem.get("stats"), dict):
        mem["stats"] = {}
    return mem


def faz7_save_memory(mem: Dict[str, Any]) -> None:
    if not isinstance(mem, dict):
        return
    if "stats" not in mem or not isinstance(mem.get("stats"), dict):
        mem["stats"] = {}
    _save_json(FAZ7_MEMORY_FILE, mem)


def faz7_touch_stat(key: str, delta: int = 1) -> None:
    """
    FAZ-7.9 hafızada basit metrik sayacı.
    Örn: total_matches, total_coupons vs.
    """
    try:
        mem = faz7_load_memory()
        stats = mem.get("stats", {})
        cur = stats.get(key, 0)
        try:
            cur_int = int(cur)
        except Exception:
            cur_int = 0
        stats[key] = cur_int + delta
        mem["stats"] = stats
        faz7_save_memory(mem)
    except Exception as e:
        log.error("faz7_touch_stat hata: %s", e, exc_info=True)


# FAZ-10 HardSync wrapper
def faz10_hardsync(brain: Dict[str, Any], calib: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if faz10_stability_check is None:
        return {
            "regime": "NORMAL",
            "stability_score": 1.0,
            "anomaly_level": 0.0,
            "suggested_mode": brain.get("mode", "INIT"),
            "bucket": (calib or {}).get("bucket", "MID") if calib else "MID",
            "lock": False,
            "lock_reason": "NO_FAZ10_MODULE",
        }
    try:
        stability = faz10_stability_check(brain) or {}
    except Exception as e:
        log.error("[FAZ-10] Stability check hata: %s", e, exc_info=True)
        stability = {}

    regime = str(stability.get("regime", "NORMAL")).upper()
    score = float(stability.get("stability_score", 1.0) or 1.0)
    anomaly = float(stability.get("anomaly_level", 0.0) or 0.0)
    suggested_mode = str(stability.get("suggested_mode", brain.get("mode", "INIT"))).upper()
    bucket = (calib or {}).get("bucket", "MID")

    lock = False
    lock_reason = "NO_LOCK"

    if ENGINEERING_MODE:
        if regime in ("CRITICAL", "UNSTABLE") or anomaly >= 0.7 or score < 0.6:
            lock = True
            lock_reason = "CRITICAL_LOCK"

    return {
        "regime": regime,
        "stability_score": score,
        "anomaly_level": anomaly,
        "suggested_mode": suggested_mode,
        "bucket": bucket,
        "lock": lock,
        "lock_reason": lock_reason,
    }


# ================================================================
# 🔍 ULTRA OCR ENGINE v3 (IMPORT + FALLBACK)
# ================================================================
def ultra_ocr_engine_v3(img_bytes: bytes) -> Dict[str, Any]:
    """
    Ultra OCR Engine v3:
      - Eğer faz13_engine.ultra_ocr_v3.ultra_ocr_engine_v3 tanımlıysa onu kullan.
      - Yoksa hafif fallback döndür (Fly.io 512 MB uyumlu).
    """
    if _ext_ultra_ocr_engine_v3:
        try:
            return _ext_ultra_ocr_engine_v3(img_bytes)
        except Exception as e:
            log.error("External Ultra OCR Engine v3 hata: %s", e, exc_info=True)

    # Fallback: OCR modülü yoksa sessizce boş dön.
    return {
        "text": "",
        "meta": {
            "engine": "NONE",
            "classifier": "NONE",
            "prob_score": 0.0,
        },
    }


# ================================================================
# 🎛️ FAZ-22 META ENGINE FULL STACK
#   - /meta        → maç önü (pre-match) meta tahmin
#   - /meta_live   → canlı, visual stack + skor analizli meta tahmin
# ================================================================
def _faz22_base_from_faz10(mem: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-10 stabilite + FAZ-7 istatistikten baz meta core üretir.
    """
    stats = mem.get("stats", {})
    total_matches = int(stats.get("total_matches", 0) or 0)
    total_coupons = int(stats.get("total_coupons", 0) or 0)

    faz10_state = faz10_hardsync(mem, {"bucket": "MID"})
    regime = faz10_state.get("regime", "NORMAL")
    score = float(faz10_state.get("stability_score", 1.0) or 1.0)
    anomaly = float(faz10_state.get("anomaly_level", 0.0) or 0.0)

    # Baz total barem: çok kaba bir lig ortalaması gibi davranıyor
    base_total = 160.5

    # Rejim ve skor ile ince ayar
    if regime == "CRITICAL":
        base_total -= 6.0
    elif regime == "UNSTABLE":
        base_total -= 3.0
    elif regime == "BULL":
        base_total += 4.0
    elif regime == "HOT":
        base_total += 2.0

    # Stabilite skoruna göre mikro ayar
    base_total += (score - 1.0) * 8.0  # 0.9 → -0.8, 1.1 → +0.8 gibi

    # FAZ-17 market adjust bağlanmışsa kullan
    market_edge = 0.0
    if faz17_market_adjust:
        try:
            adj = faz17_market_adjust(
                {
                    "base_total": base_total,
                    "total_matches": total_matches,
                    "total_coupons": total_coupons,
                    "regime": regime,
                    "stability_score": score,
                    "anomaly_level": anomaly,
                }
            ) or {}
            base_total = float(adj.get("adj_total", base_total) or base_total)
            market_edge = float(adj.get("edge", 0.0) or 0.0)
        except Exception as e:
            log.error("[FAZ-17] market_adjust hata: %s", e, exc_info=True)

    return {
        "base_total": base_total,
        "regime": regime,
        "stability_score": score,
        "anomaly_level": anomaly,
        "total_matches": total_matches,
        "total_coupons": total_coupons,
        "market_edge": market_edge,
    }


def faz22_meta_prematch_snapshot() -> Dict[str, Any]:
    """
    FAZ-22 PRE-MATCH snapshot.
    /meta komutu bunu kullanır.
    """
    mem = faz7_load_memory()
    core = _faz22_base_from_faz10(mem)

    base_total = float(core["base_total"])
    # Risk bandı: maç sayısı arttıkça daralıyor gibi düşün
    total_matches = core["total_matches"]
    if total_matches < 50:
        spread = 16.0
    elif total_matches < 200:
        spread = 12.0
    else:
        spread = 10.0

    center = base_total
    low = center - spread / 2.0
    high = center + spread / 2.0

    return {
        "mode": "PREMATCH",
        "center": center,
        "low": low,
        "high": high,
        "spread": spread,
        "core": core,
    }


def _parse_live_score_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Görsel OCR metninden 85-79 gibi skor yakalamaya çalışır.
    Çok agresif değil, hafif heuristik.
    """
    if not text:
        return None

    # Örn: 85-79, 102 : 98, 57–54 vs.
    m = re.search(r"(\d{2,3})\s*[-:–]\s*(\d{2,3})", text)
    if not m:
        return None

    try:
        home = int(m.group(1))
        away = int(m.group(2))
    except Exception:
        return None

    total = home + away
    if total < 40:  # saçma skorları ele
        return None

    return {
        "home": home,
        "away": away,
        "total": total,
    }


def faz22_meta_live_snapshot() -> Dict[str, Any]:
    """
    FAZ-22 LIVE snapshot.
    /meta_live komutu bunu kullanır.

    - VISUAL_STACK içindeki son OCR metninden skor yakalamaya çalışır.
    - Skor + FAZ-10 core birleşip canlı tahmin aralığı üretir.
    """
    mem = faz7_load_memory()
    core = _faz22_base_from_faz10(mem)

    last_text = LAST_OCR_TEXT or ""
    last_meta = LAST_OCR_META or {}
    score_info = _parse_live_score_from_text(last_text)

    center: float
    spread: float
    live_notes: List[str] = []

    if score_info:
        live_total = float(score_info["total"])
        # Kabaca kalan skor tahmini: maç temposuna göre 30–55 arası ekle
        # Fazla felsefeye girmeden hafif bir model:
        if live_total < 80:
            extra = 60.0
        elif live_total < 120:
            extra = 50.0
        elif live_total < 150:
            extra = 40.0
        else:
            extra = 30.0

        center = live_total + extra

        # Canlıda belirsizlik biraz daha dar ama hâlâ geniş
        spread = 14.0
        live_notes.append(
            "Canlı skor tespit edildi: <b>{h}-{a}</b> (toplam={tot})".format(
                h=score_info["home"],
                a=score_info["away"],
                tot=score_info["total"],
            )
        )
    else:
        # Skor yakalayamazsak prematch'e yakın davran
        prematch = faz22_meta_prematch_snapshot()
        center = float(prematch["center"])
        spread = float(prematch["spread"])
        live_notes.append("Canlı skor net yakalanamadı → PRE-MATCH çekirdeğine yakın davranıldı.")

    # Rejim/anomali ile çok hafif canlı düzeltme
    regime = core["regime"]
    anomaly = float(core["anomaly_level"] or 0.0)

    if regime in ("CRITICAL", "UNSTABLE"):
        center -= 3.0
        spread += 2.0
        live_notes.append("Rejim: <b>{}</b> → risk yüksek, band genişletildi.".format(regime))
    elif regime in ("BULL", "HOT"):
        center += 2.0
        spread -= 1.0
        live_notes.append("Rejim: <b>{}</b> → tempo yukarı, band hafif daraltıldı.".format(regime))

    if anomaly > 0.5:
        spread += 1.0
        live_notes.append("Anomali seviyesi yüksek (>{}) → belirsizlik arttırıldı.".format(0.5))

    low = center - spread / 2.0
    high = center + spread / 2.0

    return {
        "mode": "LIVE",
        "center": center,
        "low": low,
        "high": high,
        "spread": spread,
        "core": core,
        "score_info": score_info,
        "last_ocr_meta": last_meta,
        "notes": live_notes,
    }


def _format_faz22_core_block(core: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(
        "Regime: <b>{}</b> | stability=<b>{:.3f}</b> | anomaly=<b>{:.3f}</b>".format(
            core.get("regime", "NORMAL"),
            float(core.get("stability_score", 1.0) or 1.0),
            float(core.get("anomaly_level", 0.0) or 0.0),
        )
    )
    lines.append(
        "Toplam maç: <b>{}</b> | toplam kupon: <b>{}</b>".format(
            int(core.get("total_matches", 0) or 0),
            int(core.get("total_coupons", 0) or 0),
        )
    )
    lines.append(
        "Market edge (FAZ-17): <b>{:.3f}</b>".format(float(core.get("market_edge", 0.0) or 0.0))
    )
    return "\n".join(lines)


def format_meta_prematch_text(snap: Dict[str, Any]) -> str:
    low = float(snap["low"])
    high = float(snap["high"])
    center = float(snap["center"])
    spread = float(snap["spread"])
    core = snap["core"]

    lines: List[str] = []
    lines.append("🧠 <b>FAZ-22 META ENGINE FULL STACK</b>  — <i>PRE-MATCH</i>")
    lines.append("")
    lines.append(
        "Önerilen toplam barem aralığı:\n"
        "<b>{:.1f}  ↔  {:.1f}</b>  (merkez ≈ <b>{:.1f}</b>, spread ≈ <b>{:.1f}</b>)".format(
            low, high, center, spread
        )
    )
    lines.append("")
    lines.append(_format_faz22_core_block(core))
    lines.append("")
    lines.append("Not: Bu çıkış FAZ-7.9 + FAZ-10 + FAZ-17 çekirdeği ile üretilen saf META tahmindir.")
    return "\n".join(lines)


def format_meta_live_text(snap: Dict[str, Any]) -> str:
    low = float(snap["low"])
    high = float(snap["high"])
    center = float(snap["center"])
    spread = float(snap["spread"])
    core = snap["core"]
    notes = snap.get("notes", []) or []
    score_info = snap.get("score_info")

    lines: List[str] = []
    lines.append("🔥 <b>FAZ-22 META ENGINE FULL STACK</b>  — <i>LIVE</i>")
    lines.append("")
    lines.append(
        "Canlı önerilen toplam barem aralığı:\n"
        "<b>{:.1f}  ↔  {:.1f}</b>  (merkez ≈ <b>{:.1f}</b>, spread ≈ <b>{:.1f}</b>)".format(
            low, high, center, spread
        )
    )
    lines.append("")

    if score_info:
        lines.append(
            "Skor: <b>{h}-{a}</b> (toplam=<b>{tot}</b>)".format(
                h=score_info["home"],
                a=score_info["away"],
                tot=score_info["total"],
            )
        )
        lines.append("")

    if notes:
        lines.append("<b>Canlı meta notları:</b>")
        for n in notes:
            lines.append("• " + n)
        lines.append("")

    lines.append(_format_faz22_core_block(core))
    lines.append("")
    lines.append(
        "Not: Bu çıkış, FAZ-7.9 + FAZ-10 + FAZ-17 çekirdeğine ek olarak "
        "visual stack / OCR içeriği ile canlıda şekillenmiş META tahmindir."
    )
    return "\n".join(lines)


# ================================================================
# 🤖 TELEGRAM BOT
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)


def _send_long_text(message: types.Message, text: str):
    if not text:
        return
    max_len = 3500
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    for ch in chunks:
        bot.reply_to(message, ch)


# ================================================================
# 📊 /status
# ================================================================
@bot.message_handler(commands=["status"])
def cmd_status(message: types.Message):
    mem = faz7_load_memory()
    stats = mem.get("stats", {})
    total_matches = stats.get("total_matches", 0)
    total_coupons = stats.get("total_coupons", 0)

    # FAZ-10 HardSync, sadece durum raporu (lock uygulatmıyoruz)
    faz10_state = faz10_hardsync(mem, {"bucket": "MID"})

    lines: list[str] = []
    lines.append("✅ Bot çalışıyor.")
    lines.append(f"Mod: Fly.io + Webhook + Flask")
    lines.append(f"ENGINEERING_MODE: {'ON' if ENGINEERING_MODE else 'OFF'}")
    lines.append("")
    lines.append(f"FAZ-7.9 hafıza dosyası: {FAZ7_MEMORY_FILE}")
    lines.append(f"Toplam maç: {total_matches} | Toplam kupon: {total_coupons}")
    lines.append("")
    lines.append(f"FAZ-10 modul: {'AKTİF' if faz10_stability_check else 'YOK (FALLBACK)'}")
    lines.append(
        "FAZ-10 regime: {reg} | score={score:.3f} | anomaly={anom:.3f} | "
        "lock={lock} ({reason})".format(
            reg=faz10_state.get("regime", "NORMAL"),
            score=float(faz10_state.get("stability_score", 1.0) or 1.0),
            anom=float(faz10_state.get("anomaly_level", 0.0) or 0.0),
            lock=bool(faz10_state.get("lock", False)),
            reason=faz10_state.get("lock_reason", "NO_LOCK"),
        )
    )
    lines.append(f"FAZ-11 feedback: {'AKTİF' if faz11_feedback else 'YOK'}")
    lines.append(f"FAZ-12 autoadjust: {'AKTİF' if faz12_run_once else 'YOK'}")
    lines.append(f"FAZ-13 orchestrator: {'AKTİF' if _faz13_orch else 'YOK (FALLBACK)'}")
    lines.append(f"FAZ-13 GOD-LAYER: {'AKTİF' if _faz13_god else 'YOK (FALLBACK)'}")
    lines.append(f"FAZ-17 market: {'AKTİF' if faz17_market_adjust else 'YOK'}")
    lines.append("FAZ-22 META: AKTİF (INLINE ENGINE)")
    lines.append("")
    lines.append(
        "Ultra OCR Engine v3: {state}".format(
            state="AKTİF (external)" if _ext_ultra_ocr_engine_v3 else "FALLBACK (GPU/OCR modülleri henüz bağlı değil)"
        )
    )
    lines.append("")
    lines.append("Visual stack size: {}".format(len(VISUAL_STACK)))

    text = "\n".join(lines)
    bot.reply_to(message, text)


# ================================================================
# 🔌 /proxytest — Proxy Test
# ================================================================
@bot.message_handler(commands=["proxytest"])
def proxytest(message: types.Message):
    import requests
    try:
        r = requests.get("https://hoopbrain-proxy.fly.dev/ping", timeout=5)
        bot.send_message(message.chat.id, f"Proxy Çalışıyor: {r.text}")
    except Exception as e:
        bot.send_message(message.chat.id, f"Proxy Hatası: {str(e)}")


# ================================================================
# 📝 /mac — MANUAL INPUT (FAZ-13 + GOD-LAYER)
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_manual_match(message: types.Message):
    try:
        if not normalize_manual_text or not run_faz13_with_god_layer:
            raise RuntimeError("FAZ-13 GOD-LAYER modülleri bağlı değil")

        fusion = normalize_manual_text(message.text)
        if not fusion or not isinstance(fusion, dict):
            raise ValueError("normalize_manual_text boş veya dict değil")

        # FAZ-13 + GOD-LAYER
        result_text = run_faz13_with_god_layer("manual", fusion)

        # FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)

        _send_long_text(message, result_text)

        # FAZ-11 feedback + tarihçe
        if faz11_feedback:
            try:
                hist = _load_json(FAZ11_HISTORY_FILE, [])
                fb = faz11_feedback("manual", fusion, result_text)
                hist.append(fb)
                _save_json(FAZ11_HISTORY_FILE, hist)
            except Exception as e:
                log.error("[FAZ-11] feedback hata: %s", e, exc_info=True)

    except Exception as e:
        log.error("[FAZ-13 MANUAL ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ FAZ-13 manual input işlenemedi.\n"
            "Örnek: <code>/mac BOS ORL 220.5 U 1.46</code>",
        )


# ================================================================
# 📸 /mac_img — VISUAL EXTREME MODE (FAZ-13 + OCR + FAZ-22 STACK FEED)
# ================================================================
@bot.message_handler(commands=["mac_img"])
def cmd_visual_request(message: types.Message):
    bot.reply_to(
        message,
        "📸 <b>FAZ-13 EXTREME MODE</b> aktif!\n"
        "Maç görselini gönder → OCR + GOD-LAYER + FAZ-22 META stack pipeline çalışacak.",
    )


@bot.message_handler(content_types=["photo", "document"])
def cmd_visual_upload(message: types.Message):
    try:
        if not normalize_visual_meta or not run_faz13_with_god_layer:
            raise RuntimeError("FAZ-13 GOD-LAYER modülleri bağlı değil")

        if message.content_type == "photo":
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id

        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        import requests

        bot.reply_to(message, "📩 Görsel alındı → OCR işleniyor...")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        img_bytes = r.content

        ocr = ultra_ocr_engine_v3(img_bytes)
        text = (ocr or {}).get("text") or ""
        meta = (ocr or {}).get("meta") or {}

        if not text.strip():
            bot.reply_to(
                message,
                "❌ OCR başarısız → Daha net bir görsel gönder.",
            )
            return

        # FAZ-22 visual stack feed
        add_visual_item(text, meta)

        fusion = normalize_visual_meta(text)
        result = run_faz13_with_god_layer("visual", fusion)

        # FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)

        result += (
            "\n\n📊 <b>FAZ-13 OCR META</b>\n"
            f"Engine: <b>{meta.get('engine','-')}</b> | "
            f"Cls: <b>{meta.get('classifier','-')}</b> | "
            f"Score: <b>{meta.get('prob_score',0):.3f}</b>"
        )

        _send_long_text(message, result)

    except Exception as e:
        log.error("[FAZ-13 VISUAL ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ Görsel işleme sırasında hata oluştu.",
        )


# ================================================================
# 📡 /live13 — HYBRID INPUT (FAZ-13 GOD-LAYER)
# ================================================================
@bot.message_handler(commands=["live13"])
def cmd_live13(message: types.Message):
    try:
        if not normalize_manual_text or not run_faz13_with_god_layer:
            raise RuntimeError("FAZ-13 GOD-LAYER modülleri bağlı değil")

        raw = message.text or ""
        parts = raw.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else ""
        fusion = normalize_manual_text(args)

        result = run_faz13_with_god_layer("live", fusion)

        # FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)

        _send_long_text(message, result)
    except Exception as e:
        log.error("[FAZ-13 LIVE13 ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ /live13 komutunda hata.\n"
            "Örnek: <code>/live13 LAL BOS 220.5 U 1.90</code>",
        )


# ================================================================
# 🧾 FAZ-13 Kupon Komutları
# ================================================================
@bot.message_handler(commands=["daily13"])
def cmd_daily13(message: types.Message):
    try:
        if faz13_daily_coupon:
            text = str(faz13_daily_coupon({}))
            # FAZ-7.9 istatistik
            faz7_touch_stat("total_coupons", 1)
        else:
            text = "FAZ-13 DAILY coupon motoru henüz bağlı değil."
        _send_long_text(message, text)
    except Exception as e:
        log.error("[FAZ-13 DAILY ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /daily13 çalışırken hata oluştu.")


@bot.message_handler(commands=["upcoming13"])
def cmd_upcoming13(message: types.Message):
    try:
        if faz13_upcoming_coupon:
            text = str(faz13_upcoming_coupon({}))
            faz7_touch_stat("total_coupons", 1)
        else:
            text = "FAZ-13 UPCOMING coupon motoru henüz bağlı değil."
        _send_long_text(message, text)
    except Exception as e:
        log.error("[FAZ-13 UPCOMING ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /upcoming13 çalışırken hata oluştu.")


@bot.message_handler(commands=["league13"])
def cmd_league13(message: types.Message):
    try:
        if faz13_league_coupon:
            text = str(faz13_league_coupon({}))
            faz7_touch_stat("total_coupons", 1)
        else:
            text = "FAZ-13 LEAGUE coupon motoru henüz bağlı değil."
        _send_long_text(message, text)
    except Exception as e:
        log.error("[FAZ-13 LEAGUE ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /league13 çalışırken hata oluştu.")


@bot.message_handler(commands=["livecoupon13"])
def cmd_livecoupon13(message: types.Message):
    try:
        if faz13_live_coupon:
            text = str(faz13_live_coupon({}))
            faz7_touch_stat("total_coupons", 1)
        else:
            text = "FAZ-13 LIVE coupon motoru henüz bağlı değil."
        _send_long_text(message, text)
    except Exception as e:
        log.error("[FAZ-13 LIVE COUPON ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /livecoupon13 çalışırken hata oluştu.")


# ================================================================
# 🔍 FAZ-22 META KOMUTLARI
#   /meta       → maç önü meta
#   /meta_live  → canlı meta (visual stack + skor)
# ================================================================
@bot.message_handler(commands=["meta"])
def cmd_meta(message: types.Message):
    try:
        snap = faz22_meta_prematch_snapshot()
        text = format_meta_prematch_text(snap)
        _send_long_text(message, text)
    except Exception as e:
        log.error("[FAZ-22 META ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /meta sırasında FAZ-22 hata verdi.")


@bot.message_handler(commands=["meta_live"])
def cmd_meta_live(message: types.Message):
    try:
        snap = faz22_meta_live_snapshot()
        text = format_meta_live_text(snap)
        _send_long_text(message, text)
    except Exception as e:
        log.error("[FAZ-22 META_LIVE ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /meta_live sırasında FAZ-22 hata verdi.")


# ================================================================
# 📂 VISUAL STACK KOMUTLARI
#   /visual_stack_status
#   /visual_stack
#   /reset_visual
# ================================================================
@bot.message_handler(commands=["visual_stack_status"])
def cmd_visual_stack_status(message: types.Message):
    try:
        text = visual_stack_status_text()
        _send_long_text(message, text)
    except Exception as e:
        log.error("[VISUAL_STACK_STATUS ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /visual_stack_status sırasında hata.")


@bot.message_handler(commands=["visual_stack"])
def cmd_visual_stack(message: types.Message):
    try:
        if not VISUAL_STACK:
            bot.reply_to(message, "📂 Visual stack boş.")
            return

        lines: List[str] = []
        lines.append("📂 <b>FAZ-13 Visual Stack Son 10 Item</b>")
        lines.append("Toplam: <b>{}</b>".format(len(VISUAL_STACK)))
        lines.append("")

        # sadece son 10 item
        for idx, item in enumerate(VISUAL_STACK[-10:], start=max(len(VISUAL_STACK) - 10, 0) + 1):
            meta = item.get("meta", {}) or {}
            ts = item.get("ts")
            engine = meta.get("engine", "-")
            prob = float(meta.get("prob_score", 0.0) or 0.0)
            line = "#{idx}: engine={eng}, score={prob:.3f}".format(
                idx=idx,
                eng=engine,
                prob=prob,
            )
            if ts:
                dt_str = time.strftime("%m-%d %H:%M", time.gmtime(ts))
                line += f" | ts={dt_str} UTC"
            lines.append(line)

        _send_long_text(message, "\n".join(lines))
    except Exception as e:
        log.error("[VISUAL_STACK ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /visual_stack sırasında hata.")


@bot.message_handler(commands=["reset_visual"])
def cmd_reset_visual(message: types.Message):
    try:
        reset_visual_stack()
        bot.reply_to(message, "🧹 Visual stack + son OCR hafızası sıfırlandı.")
    except Exception as e:
        log.error("[RESET_VISUAL ERROR] %s", e, exc_info=True)
        bot.reply_to(message, "❌ /reset_visual sırasında hata.")


# ================================================================
# 🌐 FLASK ROUTES
# ================================================================
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        log.error("Webhook hatası: %s", e, exc_info=True)
        return "ERROR", 500
    return "OK", 200


# ================================================================
# 🔗 WEBHOOK SETUP
# ================================================================
def setup_webhook():
    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL tanımlı değil → webhook kurulmadı.")
        return
    try:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        log.info("Webhook set edildi: %s", WEBHOOK_URL)
    except Exception as e:
        log.error("Webhook set edilemedi: %s", e, exc_info=True)


# ================================================================
# 🚀 ENTRYPOINT
# ================================================================
if __name__ == "__main__":
    log.info("HoopBrain Ultra Main başlıyor. Port=%d", PORT)
    setup_webhook()
    app.run(host="0.0.0.0", port=PORT, debug=False)
