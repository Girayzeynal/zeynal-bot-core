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

# Ultra OCR Engine v3 opsiyonel
_faz13_ocr = _safe_import("faz13_engine.ultra_ocr_v3", ["ultra_ocr_engine_v3"])
_ext_ultra_ocr_engine_v3 = (_faz13_ocr or {}).get("ultra_ocr_engine_v3")

# ================================================================
# 🔧 FALLBACKS / MEMORY
# ================================================================
def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def _save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("JSON kaydedilemedi: %s (%s)", path, e)

def faz7_load_memory():
    mem = _load_json(FAZ7_MEMORY_FILE, {})
    if not isinstance(mem, dict):
        mem = {}
    if "stats" not in mem:
        mem["stats"] = {}
    return mem

def faz7_save_memory(mem):
    if "stats" not in mem:
        mem["stats"] = {}
    _save_json(FAZ7_MEMORY_FILE, mem)

def faz7_touch_stat(key: str, delta: int = 1):
    try:
        mem = faz7_load_memory()
        stats = mem.get("stats", {})
        cur = int(stats.get(key, 0))
        stats[key] = cur + delta
        mem["stats"] = stats
        faz7_save_memory(mem)
    except Exception as e:
        log.error("faz7_touch_stat hata: %s", e)


# ================================================================
# 🔧 FAZ-10 HardSync Wrapper
# ================================================================
def faz10_hardsync(brain: Dict[str, Any], calib: Optional[Dict[str, Any]] = None):
    if faz10_stability_check is None:
        return {
            "regime": "NORMAL",
            "stability_score": 1.0,
            "anomaly_level": 0.0,
            "suggested_mode": "INIT",
            "bucket": (calib or {}).get("bucket", "MID"),
            "lock": False,
            "lock_reason": "NO_FAZ10_MODULE",
        }

    try:
        st = faz10_stability_check(brain) or {}
    except Exception as e:
        log.error("FAZ-10 hata: %s", e)
        st = {}

    regime = str(st.get("regime", "NORMAL")).upper()
    score = float(st.get("stability_score", 1.0) or 1.0)
    anomaly = float(st.get("anomaly_level", 0.0) or 0.0)
    suggested_mode = str(st.get("suggested_mode", "INIT")).upper()
    bucket = (calib or {}).get("bucket", "MID")

    lock = False
    lock_reason = "NO_LOCK"

    if ENGINEERING_MODE and (regime in ("CRITICAL", "UNSTABLE") or score < 0.6 or anomaly >= 0.7):
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
# 🔧 ULTRA OCR v3 WRAPPER
# ================================================================
def ultra_ocr_engine_v3(img_bytes: bytes):
    if _ext_ultra_ocr_engine_v3:
        try:
            return _ext_ultra_ocr_engine_v3(img_bytes)
        except Exception as e:
            log.error("Ultra OCR external hata: %s", e)

    return {"text": "", "meta": {"engine": "NONE", "classifier": "NONE", "prob_score": 0.0}}


# ================================================================
# 🤖 TELEGRAM BOT
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

def _send_long(message, txt):
    if not txt:
        return
    chunks = [txt[i:i+3500] for i in range(0, len(txt), 3500)]
    for ch in chunks:
        bot.reply_to(message, ch)


# ================================================================
# 📊 /status
# ================================================================
@bot.message_handler(commands=["status"])
def cmd_status(message):
    mem = faz7_load_memory()
    stats = mem.get("stats", {})
    faz10_state = faz10_hardsync(mem, {"bucket": "MID"})

    lines = []
    lines.append("✅ Bot çalışıyor.")
    lines.append("Mod: Fly.io + Webhook + Flask")
    lines.append(f"ENGINEERING_MODE: {'ON' if ENGINEERING_MODE else 'OFF'}")
    lines.append("")
    lines.append(f"FAZ-7.9 hafıza: {FAZ7_MEMORY_FILE}")
    lines.append(f"Toplam maç: {stats.get('total_matches',0)}")
    lines.append(f"Toplam kupon: {stats.get('total_coupons',0)}")
    lines.append("")
    lines.append(f"FAZ-10: {'AKTİF' if faz10_stability_check else 'YOK'}")
    lines.append(
        f"Regime={faz10_state['regime']} | Score={faz10_state['stability_score']:.3f} "
        f"| Anomaly={faz10_state['anomaly_level']:.3f} | Lock={faz10_state['lock']} ({faz10_state['lock_reason']})"
    )
    lines.append("")
    lines.append(f"FAZ-11 feedback: {'AKTİF' if faz11_feedback else 'YOK'}")
    lines.append(f"FAZ-12 autoadjust: {'AKTİF' if faz12_run_once else 'YOK'}")
    lines.append(f"FAZ-13 orchestrator: {'AKTİF' if _faz13_orch else 'YOK'}")
    lines.append(f"FAZ-13 GOD-LAYER: {'AKTİF' if _faz13_god else 'YOK'}")
    lines.append(f"FAZ-17 market: {'AKTİF' if faz17_market_adjust else 'YOK'}")
    lines.append("")
    lines.append(
        f"Ultra OCR Engine v3: {'AKTİF (external)' if _ext_ultra_ocr_engine_v3 else 'FALLBACK'}"
    )

    bot.reply_to(message, "\n".join(lines))


# ================================================================
# 🔌 /proxytest
# ================================================================
@bot.message_handler(commands=["proxytest"])
def cmd_proxy(message):
    import requests
    try:
        r = requests.get("https://hoopbrain-proxy.fly.dev/ping", timeout=5)
        bot.send_message(message.chat.id, f"Proxy Çalışıyor: {r.text}")
    except Exception as e:
        bot.send_message(message.chat.id, f"Proxy Hata: {e}")


# ================================================================
# 📝 /mac
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_mac(message):
    try:
        if not normalize_manual_text or not run_faz13_with_god_layer:
            raise RuntimeError("FAZ-13 modülleri yok")

        fusion = normalize_manual_text(message.text)
        result = run_faz13_with_god_layer("manual", fusion)

        faz7_touch_stat("total_matches")
        _send_long(message, result)

        if faz11_feedback:
            hist = _load_json(FAZ11_HISTORY_FILE, [])
            hist.append(faz11_feedback("manual", fusion, result))
            _save_json(FAZ11_HISTORY_FILE, hist)

    except Exception as e:
        log.error("manual hata: %s", e)
        bot.reply_to(message, "❌ manual işlenemedi.")


# ================================================================
# 📸 /mac_img
# ================================================================
@bot.message_handler(commands=["mac_img"])
def cmd_mac_img(message):
    bot.reply_to(message, "📸 FAZ-13 EXTREME MODE: Görsel gönder.")

@bot.message_handler(content_types=["photo","document"])
def cmd_upload(message):
    try:
        if not normalize_visual_meta or not run_faz13_with_god_layer:
            raise RuntimeError("FAZ-13 modülleri yok")

        file_id = message.photo[-1].file_id if message.content_type=="photo" else message.document.file_id
        file_info = bot.get_file(file_id)

        import requests
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        data = requests.get(url,timeout=10).content

        bot.reply_to(message,"OCR işleniyor...")

        ocr = ultra_ocr_engine_v3(data)
        text = ocr.get("text","")
        meta = ocr.get("meta",{})

        if not text.strip():
            bot.reply_to(message,"❌ OCR başarısız.")
            return

        fusion = normalize_visual_meta(text)
        result = run_faz13_with_god_layer("visual", fusion)

        faz7_touch_stat("total_matches")

        result += (
            "\n\n📊 OCR META\n"
            f"Engine: {meta.get('engine','-')} | "
            f"Cls: {meta.get('classifier','-')} | "
            f"Score: {meta.get('prob_score',0):.3f}"
        )

        _send_long(message, result)

    except Exception as e:
        log.error("visual hata: %s", e)
        bot.reply_to(message,"❌ Görsel işlenemedi.")


# ================================================================
# 📡 /live13
# ================================================================
@bot.message_handler(commands=["live13"])
def cmd_live13(message):
    try:
        fusion = normalize_manual_text(message.text.split(" ",1)[1])
        result = run_faz13_with_god_layer("live", fusion)
        faz7_touch_stat("total_matches")
        _send_long(message,result)
    except:
        bot.reply_to(message,"❌ canlı işlenemedi.")


# ================================================================
# 🧾 KUPOΝ
# ================================================================
@bot.message_handler(commands=["daily13"])
def cmd_daily(message):
    try:
        txt = str(faz13_daily_coupon({})) if faz13_daily_coupon else "motor yok"
        faz7_touch_stat("total_coupons")
        _send_long(message,txt)
    except:
        bot.reply_to(message,"❌ daily13 hata.")

@bot.message_handler(commands=["upcoming13"])
def cmd_upcoming(message):
    try:
        txt = str(faz13_upcoming_coupon({})) if faz13_upcoming_coupon else "motor yok"
        faz7_touch_stat("total_coupons")
        _send_long(message,txt)
    except:
        bot.reply_to(message,"❌ upcoming13 hata.")

@bot.message_handler(commands=["league13"])
def cmd_league(message):
    try:
        txt = str(faz13_league_coupon({})) if faz13_league_coupon else "motor yok"
        faz7_touch_stat("total_coupons")
        _send_long(message,txt)
    except:
        bot.reply_to(message,"❌ league13 hata.")

@bot.message_handler(commands=["livecoupon13"])
def cmd_livecoupon(message):
    try:
        txt = str(faz13_live_coupon({})) if faz13_live_coupon else "motor yok"
        faz7_touch_stat("total_coupons")
        _send_long(message,txt)
    except:
        bot.reply_to(message,"❌ livecoupon hata.")


# ================================================================
# 🌐 FLASK
# ================================================================
@app.route("/",methods=["GET"])
def home():
    return "OK",200

@app.route("/webhook",methods=["POST"])
def telegram_webhook():
    try:
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
        bot.process_new_updates([update])
    except Exception as e:
        log.error("Webhook hata: %s", e)
        return "ERROR",500
    return "OK",200


# ================================================================
# 🚀 ENTRYPOINT
# ================================================================
def setup_webhook():
    if not WEBHOOK_URL:
        log.warning("Webhook yok.")
        return
    try:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
    except Exception as e:
        log.error("Webhook kurulamadı: %s", e)

if __name__=="__main__":
    log.info("HoopBrain Ultra Main başlıyor. Port=%d",PORT)
    setup_webhook()
    app.run(host="0.0.0.0",port=PORT,debug=False) 
