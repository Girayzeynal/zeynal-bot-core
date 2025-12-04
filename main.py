import os
import json
import logging
from typing import Any, Dict, Optional

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

from .faz13_orchestrator import run_faz13_auto_pipeline

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

# Ultra OCR Engine v3 opsiyonel import (FAZ-13 visual için)
_faz13_ocr = _safe_import("faz13_engine.ultra_ocr_v3", ["ultra_ocr_engine_v3"])
_ext_ultra_ocr_engine_v3 = (_faz13_ocr or {}).get("ultra_ocr_engine_v3")

# ================================================================
# 🔧 FAZ-23 NEWS + MULTI-DATA ENGINE IMPORT
# ================================================================
_faz23 = _safe_import(
    "faz23_engine.faz23_meta_engine",
    [
        "faz23_prematch_predict",
        "faz23_live_predict",
        "faz23_news_enrich",
    ],
)
faz23_prematch_predict = (_faz23 or {}).get("faz23_prematch_predict")
faz23_live_predict = (_faz23 or {}).get("faz23_live_predict")
faz23_news_enrich = (_faz23 or {}).get("faz23_news_enrich")

# Multi-data sağlayıcı çekirdeği (örn. maçkolik/flashscore/NBA/Euroleague füzyonu)
_faz_live_core = _safe_import(
    "live_providers.core",
    ["get_live_match_global", "HoopbrainLiveError"],
)
get_live_match_global = (_faz_live_core or {}).get("get_live_match_global")
HoopbrainLiveError = (_faz_live_core or {}).get("HoopbrainLiveError")


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
    lines.append("Mod: Fly.io + Webhook + Flask")
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
    lines.append("")
    lines.append(
        "Ultra OCR Engine v3: {state}".format(
            state="AKTİF (external)" if _ext_ultra_ocr_engine_v3 else "FALLBACK (GPU/OCR modülleri henüz bağlı değil)"
        )
    )
    lines.append(
        "FAZ-23 META ENGINE: {state}".format(
            state="AKTİF (NEWS+MULTI-DATA)" if faz23_prematch_predict and get_live_match_global else "YOK / EKSİK MODÜL"
        )
    )

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
# 📸 /mac_img — VISUAL EXTREME MODE (FAZ-13 + OCR)
# ================================================================
@bot.message_handler(commands=["mac_img"])
def cmd_visual_request(message: types.Message):
    bot.reply_to(
        message,
        "📸 <b>FAZ-13 EXTREME MODE</b> aktif!\n"
        "Maç görselini gönder → OCR + GOD-LAYER pipeline çalışacak.",
    )


@bot.message_handler(content_types=["photo", "document"])
def cmd_visual_upload(message: types.Message):
    """
    Not: Bu handler hem /mac_img sonrası, hem de direkt foto belgesinde devreye girer.
    FAZ-13 GOD-LAYER + Ultra OCR v3 pipeline kullanır.
    """
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
# 📡 /live13 — HYBRID INPUT (FAZ-13)
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
# 🧠 FAZ-23 NEWS + MULTI-DATA ENGINE HELPERS
# ================================================================
def faz23_build_context(match_code: str, mode: str = "prematch") -> Dict[str, Any]:
    """
    Multi-data + news füzyonunu tek yerde toplar.
    - match_code: live_providers.core tarafında anlamlı olan ID / key
    - mode: "prematch" veya "live"

    1) get_live_match_global ile tüm sağlayıcıları fuse eder.
    2) faz23_news_enrich varsa haber / sakatlık / yorum sinyallerini ekler.
    """
    if not get_live_match_global:
        raise RuntimeError("live_providers.core.get_live_match_global modülü yok")

    raw_ctx: Dict[str, Any] = {}
    try:
        # live_providers.core içinde maçkolik / flashscore / nba / euroleague vs füzyonu
        raw_ctx = get_live_match_global(match_code, mode=mode) or {}
    except Exception as e:
        # Eğer modülde özel exception varsa, yakala ve yukarı taşı.
        if HoopbrainLiveError and isinstance(e, HoopbrainLiveError):
            raise
        log.error("[FAZ-23] get_live_match_global hata: %s", e, exc_info=True)
        raise

    if not isinstance(raw_ctx, dict):
        raw_ctx = {}

    # Haber / sakatlık / yorum sinyalleri ile zenginleştir
    if faz23_news_enrich:
        try:
            enriched = faz23_news_enrich(raw_ctx, mode=mode) or raw_ctx
            if isinstance(enriched, dict):
                raw_ctx = enriched
        except Exception as e:
            log.error("[FAZ-23] news_enrich hata: %s", e, exc_info=True)

    # Minimal meta alanı ekle (FAZ-10/11/12 vs için)
    raw_ctx.setdefault("mode", mode.upper())
    raw_ctx.setdefault("engine", "FAZ-23")
    return raw_ctx


# ================================================================
# 🧠 FAZ-23 KOMUTLARI
# ================================================================
@bot.message_handler(commands=["meta23"])
def cmd_meta23(message: types.Message):
    """
    FAZ-23 PREMATCH tahmin motoru.
    Kullanım:
      /meta23 <match_code>

    match_code: live_providers.core için anlamlı ID / lig+takım kodu
    """
    try:
        if not faz23_prematch_predict or not get_live_match_global:
            bot.reply_to(
                message,
                "❌ FAZ-23 META ENGINE henüz tam bağlı değil.\n"
                "Eksik modül: faz23_engine.faz23_meta_engine veya live_providers.core",
            )
            return

        raw = message.text or ""
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            bot.reply_to(
                message,
                "⚙ Kullanım:\n"
                "<code>/meta23 LAL@BOS</code>\n"
                "veya live_providers.core içinde tanımlı maç ID'si.",
            )
            return

        match_code = parts[1].strip()

        try:
            ctx = faz23_build_context(match_code, mode="prematch")
        except Exception as e:
            if HoopbrainLiveError and isinstance(e, HoopbrainLiveError):
                bot.reply_to(message, f"❌ FAZ-23 veri hatası: {str(e)}")
                return
            raise

        # FAZ-10 HardSync'i bilgi amaçlı çalıştırabiliriz (lock uygulatmıyoruz)
        faz10_state = faz10_hardsync(ctx, {"bucket": ctx.get("bucket", "MID")})
        ctx["faz10_state"] = faz10_state

        text = faz23_prematch_predict(ctx)
        if not isinstance(text, str):
            text = str(text)

        # FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)

        _send_long_text(message, text)

    except Exception as e:
        log.error("[FAZ-23 META23 ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ /meta23 çalışırken hata oluştu.\n"
            "Kullanım: <code>/meta23 MATCH_CODE</code>",
        )


@bot.message_handler(commands=["meta23_live"])
def cmd_meta23_live(message: types.Message):
    """
    FAZ-23 LIVE tahmin motoru.
    Kullanım:
      /meta23_live <match_code>
    """
    try:
        if not faz23_live_predict or not get_live_match_global:
            bot.reply_to(
                message,
                "❌ FAZ-23 LIVE ENGINE henüz tam bağlı değil.\n"
                "Eksik modül: faz23_engine.faz23_meta_engine veya live_providers.core",
            )
            return

        raw = message.text or ""
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            bot.reply_to(
                message,
                "⚙ Kullanım:\n"
                "<code>/meta23_live LAL@BOS</code>\n"
                "veya live_providers.core içinde tanımlı canlı maç ID'si.",
            )
            return

        match_code = parts[1].strip()

        try:
            ctx = faz23_build_context(match_code, mode="live")
        except Exception as e:
            if HoopbrainLiveError and isinstance(e, HoopbrainLiveError):
                bot.reply_to(message, f"❌ FAZ-23 LIVE veri hatası: {str(e)}")
                return
            raise

        # FAZ-10 HardSync duruma bakış
        faz10_state = faz10_hardsync(ctx, {"bucket": ctx.get("bucket", "MID")})
        ctx["faz10_state"] = faz10_state

        text = faz23_live_predict(ctx)
        if not isinstance(text, str):
            text = str(text)

        # FAZ-7.9 istatistik
        faz7_touch_stat("total_matches", 1)

        _send_long_text(message, text)

    except Exception as e:
        log.error("[FAZ-23 META23_LIVE ERROR] %s", e, exc_info=True)
        bot.reply_to(
            message,
            "❌ /meta23_live çalışırken hata oluştu.\n"
            "Kullanım: <code>/meta23_live MATCH_CODE</code>",
        )

@bot.message_handler(commands=['mac'])
def match_handler(msg):
    result = run_faz13_auto_pipeline(
        league="Euroleague",
        date="2025-12-04",
        home_team="Anadolu Efes",
        away_team="Real Madrid"
    )
    bot.reply_to(msg, json.dumps(result, ensure_ascii=False, indent=2))


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
    log.info("HoopBrain Ultra Main (FAZ-7.9/10/11/12/13/17 + FAZ-23) başlıyor. Port=%d", PORT)
    setup_webhook()
    app.run(host="0.0.0.0", port=PORT, debug=False)
