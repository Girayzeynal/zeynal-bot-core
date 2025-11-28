# ================================================================
#  HoopBrain Ultra Core — MAIN.PY  (PART 1 / 5)
#  Versiyon: 2025-11-28
#  Amaç: Fly.io + Telegram + FAZ0–17 için tek çekirdek mimari
# ================================================================

import os
import time
import json
import logging
from typing import Any, Dict

import telebot
from flask import Flask, request, jsonify

# ================================================================
# 🔧 LOGGING — GLOBAL
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hoopbrain-core")

# ================================================================
# 🔧 CONFIG — ENV VARS
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Örn: https://zeynal-bot-core.fly.dev
ENGINEERING_MODE = os.getenv("ENGINEERING_MODE", "ON").upper() == "ON"

# Fly.io genelde PORT veriyor, yoksa 8080'e düş
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env değişkeni tanımlı değil. Fly.io secrets kontrol et.")

if not WEBHOOK_URL:
    log.warning(
        "WEBHOOK_URL tanımlı değil. "
        "Production'da /webhook için tam URL tanımlaman gerekiyor."
    )

# ================================================================
# 🤖 TELEGRAM BOT + FLASK APP
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ================================================================
# 🧠 GLOBAL STATE (FAZ-7/10/11/12/13 vs için placeholder)
# ================================================================
STATE: Dict[str, Any] = {
    "boot_ts": time.time(),
    "last_status_ts": None,
    "faZ_memory_ok": False,
    "faZ_brain_loaded": False,
    "version": "HB-ULTRA-CORE-2025.11.28",
}

# ================================================================
# 🔧 HELPER: BOOL ENV PARSER
# ================================================================
def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ================================================================
# 🔧 HELPER: UZUN MESAJ GÖNDERİCİ
# ================================================================
def _send_long_text(message, text: str, chunk_size: int = 3500) -> None:
    """
    Telegram 4096 char sınırı için güvenli bölücü.
    """
    if not text:
        return

    for i in range(0, len(text), chunk_size):
        part = text[i : i + chunk_size]
        bot.reply_to(message, part)


# ================================================================
# 🌐 FLASK ROUTE'LERİ
# ================================================================

@app.route("/", methods=["GET"])
def home():
    """
    Health check + basit JSON status.
    Fly.io load balancer burayı kullanabilir.
    """
    now = time.time()
    uptime = now - STATE["boot_ts"]
    STATE["last_status_ts"] = now

    return jsonify(
        {
            "service": "hoopbrain-ultra-core",
            "version": STATE["version"],
            "uptime_sec": int(uptime),
            "engineering_mode": ENGINEERING_MODE,
        }
    ), 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """
    Telegram'dan gelen update'leri Flask üzerinden TeleBot'a aktarır.
    Fly.io'da `python main.py` ile çalışacak şekilde tasarlandı.
    """
    try:
        if request.headers.get("content-type") == "application/json":
            json_str = request.get_data().decode("utf-8")
            update = telebot.types.Update.de_json(json_str)
            bot.process_new_updates([update])
        else:
            log.warning("Bilinmeyen content-type alındı: %s", request.headers.get("content-type"))
        return "OK", 200
    except Exception as e:
        log.exception("Webhook işlenirken hata: %s", e)
        return "ERROR", 500


# ================================================================
# 🔧 WEBHOOK REGISTRATION
# ================================================================
def register_webhook():
    """
    Bot açılışında webhook'u temiz şekilde yeniden kurar.
    """
    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL yok, webhook set edilmedi. (Localse polling düşünebilirsin.)")
        return

    full_url = WEBHOOK_URL.rstrip("/") + "/webhook"

    try:
        log.info("Eski webhook siliniyor...")
        bot.remove_webhook()
        time.sleep(0.5)
        log.info("Yeni webhook ayarlanıyor: %s", full_url)
        bot.set_webhook(url=full_url, drop_pending_updates=True)
        log.info("Webhook başarıyla ayarlandı.")
    except Exception as e:
        log.exception("Webhook ayarlanırken hata: %s", e)


# ================================================================
# 🧪 BASİT /status KOMUTU  (çekirdeğin ayakta olduğunu kanıtlar)
# ================================================================
@bot.message_handler(commands=["status", "start"])
def cmd_status(message):
    """
    En temel canlılık testi.
    Buradan sonra diğer FAZ komutları eklenecek.
    """
    now = time.time()
    uptime_min = (now - STATE["boot_ts"]) / 60.0

    text = (
        "✅ <b>HoopBrain Ultra Core Çalışıyor</b>\n\n"
        f"• Versiyon : <code>{STATE['version']}</code>\n"
        f"• Uptime   : <b>{uptime_min:.1f} dk</b>\n"
        f"• ENGINEERING_MODE : <b>{'ON' if ENGINEERING_MODE else 'OFF'}</b>\n"
        "\n"
        "Burası çekirdek oda. /mac, /mac_img, /live13, FAZ-7/10/11/12/13 "
        "ve kupon motorları bir sonraki parçalarda eklenecek. 🔧"
    )
    bot.reply_to(message, text)


# ================================================================
# 🚀 MAIN ENTRYPOINT
# ================================================================
def main():
    log.info("HoopBrain Ultra Core boot ediyor...")
    register_webhook()
    log.info("Flask server %d portundan dinleyecek.", PORT)
    # debug=False üretimde; threaded=True TeleBot için OK
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()


# ================================================================
# 🧠 FAZ-13.2 KOMUTLAR (Manual / Visual / Live / Kupon)
# ================================================================

from faz13_engine.faz13_god_layer import run_faz13_with_god_layer
from faz13_engine.faz13_orchestrator import (
    normalize_manual_text,
    normalize_visual_meta,
    normalize_api_data,
)

import requests

LAST_OCR_TEXT = None
LAST_OCR_META = None


# ================================================================
#  🔹 /mac → Manuel girilen metin
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_manual_match(message):
    try:
        raw = message.text or ""
        fusion = normalize_manual_text(raw)

        result_text = run_faz13_with_god_layer("manual", fusion)

        bot.reply_to(message, result_text, parse_mode="HTML")

    except Exception as e:
        log.error(f"[FAZ-13 MANUAL ERROR] {e}", exc_info=True)
        bot.reply_to(message, "❌ MANUAL işleminde hata oluştu.")


# ================================================================
#  🔹 /mac_img → Görsel OCR + GOD-LAYER
# ================================================================
@bot.message_handler(commands=["mac_img"])
def cmd_visual_request(message):
    bot.reply_to(
        message,
        "📸 <b>FAZ-13 VISUAL MODE aktif.</b>\n"
        "Maç görselini gönder → OCR + GOD-LAYER çalışacak.",
        parse_mode="HTML",
    )


@bot.message_handler(content_types=["photo", "document"])
def cmd_visual_upload(message):
    """
    Her foto veya belge → Ultra OCR Engine → normalize → GOD-LAYER
    """

    global LAST_OCR_TEXT, LAST_OCR_META

    try:
        # 1) Telegram dosyasını al
        if message.content_type == "photo":
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id

        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        bot.reply_to(message, "📥 Görsel alındı → OCR işleniyor...")

        # 2) Görsel indir
        r = requests.get(url, timeout=10)
        r.raise_for_status()

        img_bytes = r.content

        # 3) ULTRA OCR ENGINE v3
        ocr = ultra_ocr_engine_v3(img_bytes)
        text = ocr.get("text", "") or ""
        meta = ocr.get("meta", {}) or {}

        LAST_OCR_TEXT = text
        LAST_OCR_META = meta

        if not text.strip():
            bot.reply_to(message, "❌ OCR başarısız → Daha net bir görsel gönder.")
            return


        # 4) Normalize et → GOD-LAYER
        fusion = normalize_visual_meta(text)
        result = run_faz13_with_god_layer("visual", fusion)

        bot.reply_to(message, result, parse_mode="HTML")

    except Exception as e:
        log.error(f"[FAZ-13 VISUAL ERROR] {e}", exc_info=True)
        bot.reply_to(message, "❌ Görsel işlenirken hata oluştu.")


# ================================================================
# 🔹 /live13 → Hybrid live manual input
# ================================================================
@bot.message_handler(commands=["live13"])
def cmd_live13(message):
    """
    Hibrit: ID + takımlar
        /live13 NBA LAL BOS 223.5 O 1.65
        /live13 4412200
    """

    try:
        raw = message.text or ""
        fusion = normalize_manual_text(raw)  # live manual parse

        result_text = run_faz13_with_god_layer("live", fusion)

        bot.reply_to(message, result_text, parse_mode="HTML")

    except Exception as e:
        log.error(f"[FAZ-13 LIVE13 ERROR] {e}", exc_info=True)
        bot.reply_to(message, "❌ LIVE13 işleminde hata oluştu.")


# ================================================================
# 🔹 /kupon → Günlük + lig bazlı + canlı kupon jeneratörü
# ================================================================
@bot.message_handler(commands=["kupon"])
def cmd_coupon(message):
    """
    /kupon → tüm maçlardan en güvenilirleri seç
    /kupon NBA → sadece NBA
    /kupon live → canlı maçlardan
    """

    try:
        args = message.text.split()
        mode = args[1].lower() if len(args) > 1 else "daily"

        if mode == "daily":
            result = faz13_daily_coupon({})
        elif mode == "live":
            result = faz13_live_coupon({})
        else:
            result = faz13_league_coupon({"league": mode.upper()})

        bot.reply_to(message, result, parse_mode="HTML")

    except Exception as e:
        log.error(f"[FAZ-13 COUPON ERROR] {e}", exc_info=True)
        bot.reply_to(message, "❌ Kupon işleminde hata oluştu.")


# ================================================================
# 🔹 /hb_debug → OCR + fusion debug
# ================================================================
@bot.message_handler(commands=["hb_debug"])
def cmd_debug(message):
    msg = (
        "<b>FAZ-13 Debug</b>\n\n"
        f"<b>OCR:</b>\n{LAST_OCR_TEXT}\n\n"
        f"<b>META:</b>\n{json.dumps(LAST_OCR_META, indent=2)}"
    )
    bot.reply_to(message, msg, parse_mode="HTML")


# ================================================================
# 🧠 FAZ-13 ULTRA OCR ENGINE v3
#    - Tesseract / EasyOCR / Vision API (opsiyonel)
#    - GPU_MODE, VISION_MODE ile kontrol
#    - OCR CACHE (aynı görseli tekrar okuma)
# ================================================================

import os
import io
import hashlib
import time

# OCR CONFIG
GPU_MODE = os.getenv("GPU_MODE", "AUTO").upper()      # AUTO / FORCE / OFF
VISION_MODE = os.getenv("VISION_MODE", "OFF").upper() # OFF / ON (ileride)
TESSERACT_TIMEOUT = int(os.getenv("TESSERACT_TIMEOUT", "8"))
EASYOCR_TIMEOUT = int(os.getenv("EASYOCR_TIMEOUT", "8"))
VISION_TIMEOUT = int(os.getenv("VISION_TIMEOUT", "12"))

OCR_CACHE: dict[str, dict] = {}


def _ocr_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------
# 🔹 Tesseract backend (varsa)
# ---------------------------------------------------------------
def _run_tesseract_ocr(img_bytes: bytes) -> dict | None:
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return None

    try:
        img = Image.open(io.BytesIO(img_bytes))

        start = time.time()
        text = pytesseract.image_to_string(img)
        dt = time.time() - start

        return {
            "engine": "tesseract",
            "text": text,
            "meta": {
                "engine": "tesseract",
                "classifier": "raw",
                "prob_score": 0.72,
                "latency": dt,
            },
        }
    except Exception as e:
        log.error(f"[OCR TESSERACT ERROR] {e}", exc_info=True)
        return None


# ---------------------------------------------------------------
# 🔹 EasyOCR backend (varsa)
# ---------------------------------------------------------------
def _run_easyocr_ocr(img_bytes: bytes) -> dict | None:
    try:
        import easyocr
    except ImportError:
        return None

    try:
        reader = easyocr.Reader(
            ["en"],
            gpu=(GPU_MODE != "OFF"),
            verbose=False,
        )
        start = time.time()
        res = reader.readtext(img_bytes, detail=0)
        dt = time.time() - start
        text = "\n".join(res or [])

        return {
            "engine": "easyocr",
            "text": text,
            "meta": {
                "engine": "easyocr",
                "classifier": "raw",
                "prob_score": 0.75,
                "latency": dt,
            },
        }
    except Exception as e:
        log.error(f"[OCR EASYOCR ERROR] {e}", exc_info=True)
        return None


# ---------------------------------------------------------------
# 🔹 Vision API backend (şimdilik placeholder)
# ---------------------------------------------------------------
def _run_vision_ocr(img_bytes: bytes) -> dict | None:
    # Burayı ileride gerçek Cloud Vision / başka API ile dolduracağız.
    # Şu an için kapalı.
    if VISION_MODE == "OFF":
        return None

    try:
        # TODO: gerçek vision entegrasyonu
        text = ""
        return {
            "engine": "vision_placeholder",
            "text": text,
            "meta": {
                "engine": "vision_placeholder",
                "classifier": "raw",
                "prob_score": 0.70,
                "latency": 0.0,
            },
        }
    except Exception as e:
        log.error(f"[OCR VISION ERROR] {e}", exc_info=True)
        return None


# ---------------------------------------------------------------
# 🔥 ULTRA OCR ENGINE v3 – Ana giriş
# ---------------------------------------------------------------
def ultra_ocr_engine_v3(img_bytes: bytes) -> dict:
    """
    Girdi: raw image bytes
    Çıktı:
        {
          "text": "...",
          "meta": {engine, classifier, prob_score, latency}
        }
    """

    key = _ocr_hash(img_bytes)
    if key in OCR_CACHE:
        cached = OCR_CACHE[key]
        cached_meta = dict(cached.get("meta") or {})
        cached_meta["cache"] = True
        return {"text": cached["text"], "meta": cached_meta}

    # Deneme sırası: Tesseract → EasyOCR → Vision → fallback
    backends = [
        _run_tesseract_ocr,
        _run_easyocr_ocr,
        _run_vision_ocr,
    ]

    for backend in backends:
        res = backend(img_bytes)
        if res and res.get("text"):
            OCR_CACHE[key] = {"text": res["text"], "meta": res["meta"]}
            return {"text": res["text"], "meta": res["meta"]}

    # Hiçbiri çalışmazsa fallback:
    fallback = {
        "text": "",
        "meta": {
            "engine": "fallback",
            "classifier": "none",
            "prob_score": 0.5,
            "latency": 0.0,
        },
    }
    OCR_CACHE[key] = fallback
    return fallback
