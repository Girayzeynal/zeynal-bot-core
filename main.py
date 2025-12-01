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

# ================================================================
# 🔧 FALLBACKS
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


# Memory fallback
def faz7_load_memory() -> Dict[str, Any]:
    mem = _load_json(FAZ7_MEMORY_FILE, {})
    if not isinstance(mem, dict):
        mem = {}
    return mem


def faz7_save_memory(mem: Dict[str, Any]) -> None:
    _save_json(FAZ7_MEMORY_FILE, mem)


# FAZ-10 HardSync wrapper
def faz10_hardsync(brain: Dict[str, Any], calib: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if faz10_stability_check is None:
        return {
            "regime": "NORMAL",
            "stability_score": 1.0,
            "anomaly_level": 0.0,
            "suggested_mode": brain.get("mode", "INIT"),
            "bucket": calib.get("bucket", "MID") if calib else "MID",
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
# 🔍 ULTRA OCR ENGINE v3 (FALLBACK)
# ================================================================
def ultra_ocr_engine_v3(img_bytes: bytes) -> Dict[str, Any]:
    return {"text": "", "meta": {"engine": "NONE", "classifier": "NONE", "prob_score": 0.0}}


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

    lines = []
    lines.append("✅ Bot çalışıyor.")
    lines.append(f"Mod: Fly.io + Webhook + Flask")
    lines.append(f"ENGINEERING_MODE: {'ON' if ENGINEERING_MODE else 'OFF'}")
    lines.append("")
    lines.append(f"FAZ-7.9 hafıza dosyası: {FAZ7_MEMORY_FILE}")
    lines.append(f"Toplam maç: {total_matches} | Toplam kupon: {total_coupons}")
    lines.append("")
    lines.append(f"FAZ-10 stability: {'AKTİF' if faz10_stability_check else 'YOK (FALLBACK)'}")
    lines.append(f"FAZ-11 feedback: {'AKTİF' if faz11_feedback else 'YOK'}")
    lines.append(f"FAZ-12 autoadjust: {'AKTİF' if faz12_run_once else 'YOK'}")
    lines.append(f"FAZ-13 orchestrator: {'AKTİF' if _faz13_orch else 'YOK (FALLBACK)'}")
    lines.append(f"FAZ-13 GOD-LAYER: {'AKTİF' if _faz13_god else 'YOK (FALLBACK)'}")
    lines.append(f"FAZ-17 market: {'AKTİF' if faz17_market_adjust else 'YOK'}")
    lines.append("")
    lines.append("Ultra OCR Engine v3: FALLBACK (GPU/OCR modülleri henüz bağlı değil)")

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
# 📝 /mac — MANUAL INPUT
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_manual_match(message: types.Message):
    try:
        fusion = normalize_manual_text(message.text)
        if not fusion or not isinstance(fusion, dict):
            raise ValueError("normalize_manual_text boş döndü")

        result_text = run_faz13_with_god_layer("manual", fusion)
        _send_long_text(message, result_text)

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
# 📸 /mac_img — VISUAL EXTREME MODE
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
    try:
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
# 📡 /live13 — HYBRID INPUT
# ================================================================
@bot.message_handler(commands=["live13"])
def cmd_live13(message: types.Message):
    try:
        raw = message.text or ""
        parts = raw.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else ""
        fusion = normalize_manual_text(args)

        result = run_faz13_with_god_layer("live", fusion)
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
    log.info("HoopBrain Ultra Main başlıyor. Port=%d", PORT)
    setup_webhook()
    app.run(host="0.0.0.0", port=PORT, debug=False)
