# ================================================================
# 🌌 FAZ-CORE ULTRA STACK — ULTIMATE ARCHITECTURE (Sonsuz Modlu Sistem)
# ENGINEERING MODE: ON + HIGH FOCUS + HATA AVCI MODU
# ================================================================
#
# Tek dosya, Fly.io 512MB uyumlu, eski %100 çalışan mimariyi bozmadan
# FAZ-7.9 / 10 / 11 / 12 / 13 / 17 / 22 / 23 + visual stack komutlarını
# tek yerde toplayan “ana beyin”.
#
# ÖNEMLİ:
# - Eski engine modüllerine dokunmuyoruz; sadece buradan orkestrasyon yapıyoruz.
# - Her yeni faz, ayrı modül; burada try/except ile opsiyonel hale getirildi.
# - Eksik modül varsa sistem çalışmaya devam eder, sadece ilgili faz log’lanır.
# - Flask + TeleBot webhook modeli; Fly.io için main:app kullanılabilir.
# ================================================================

import os
import json
import time
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import telebot
import numpy as np
import pandas as pd
from flask import Flask, request, jsonify

# ================================================================
# 🔧 LOGGING
# ================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("faz_core")

# ================================================================
# 🔧 CONFIG
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Örn: https://zeynal-bot-core.fly.dev/webhook
RUN_MODE = os.getenv("RUN_MODE", "WEBHOOK").upper()  # WEBHOOK | POLLING
FAZ_DATA_DIR = os.getenv("FAZ_DATA_DIR", "/data/faz-core")
VISUAL_STACK_PATH = os.path.join(FAZ_DATA_DIR, "visual_stack.json")
FAZ11_HISTORY_PATH = os.path.join(FAZ_DATA_DIR, "feedback", "faz11_history.jsonl")
FAZ12_PROFILE_PATH = os.path.join(FAZ_DATA_DIR, "profiles", "faz12_auto_profile.json")
FAZ22_MODE_PROFILE_PATH = os.path.join(FAZ_DATA_DIR, "profiles", "faz22_mode_profiles.json")

os.makedirs(FAZ_DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(FAZ11_HISTORY_PATH), exist_ok=True)
os.makedirs(os.path.dirname(FAZ12_PROFILE_PATH), exist_ok=True)
os.makedirs(os.path.dirname(FAZ22_MODE_PROFILE_PATH), exist_ok=True)

if not BOT_TOKEN:
    log.error("BOT_TOKEN env yok. Çıkılıyor.")
    raise SystemExit("BOT_TOKEN is required")

# ================================================================
# 🔍 FAZ-13 OCR DEBUG STATE + GLOBAL VISUAL STACK
# ================================================================
LAST_OCR_TEXT: Optional[str] = None
LAST_OCR_META: Dict[str, Any] = {}

VISUAL_STACK_LOCK = threading.Lock()
VISUAL_STACK: List[Dict[str, Any]] = []  # Bellek içi kopya, disk ile senkron

# ================================================================
#  FAZ-ENGINE IMPORTLARI (opsiyonel, hata avcı modunda)
# ================================================================
# FAZ-7.9: Temel istatistik altyapısı vs. (eski sistemde ne ise)
try:
    from faz79_engine.core import faz79_prepare_match  # type: ignore
    log.info("FAZ-7.9 yüklendi.")
except Exception as e:  # noqa: BLE001
    faz79_prepare_match = None
    log.warning("FAZ-7.9 yüklenemedi: %s", e)

# FAZ-10: Stabilite / health check
try:
    from faz10_engine.faz10_stability import faz10_stability_check  # type: ignore
    log.info("FAZ-10 yüklendi.")
except Exception as e:  # noqa: BLE001
    faz10_stability_check = None
    log.warning("FAZ-10 yüklenemedi: %s", e)

# FAZ-11: Feedback
try:
    from faz11_engine.faz11_feedback import (  # type: ignore
        faz11_feedback,
        faz11_last_summary,
    )
    log.info("FAZ-11 yüklendi.")
except Exception as e:  # noqa: BLE001
    faz11_feedback = None
    faz11_last_summary = None
    log.warning("FAZ-11 yüklenemedi: %s", e)

# FAZ-12: Auto-adjust
try:
    from faz12_engine.faz12_autoadjust import (  # type: ignore
        faz12_run_once,
        faz12_auto_profile,
    )
    log.info("FAZ-12 yüklendi.")
except Exception as e:  # noqa: BLE001
    faz12_run_once = None
    faz12_auto_profile = None
    log.warning("FAZ-12 yüklenemedi: %s", e)

# FAZ-13: Ana tahmin motoru
try:
    from faz13_engine.faz13_orchestrator import (  # type: ignore
        normalize_manual_text,
        normalize_api_data,
        normalize_visual_meta,
        run_faz13_auto_pipeline,
        faz13_daily_coupon,
    )
    log.info("FAZ-13 yüklendi.")
except Exception as e:  # noqa: BLE001
    normalize_manual_text = None
    normalize_api_data = None
    normalize_visual_meta = None
    run_faz13_auto_pipeline = None
    faz13_daily_coupon = None
    log.warning("FAZ-13 yüklenemedi: %s", e)

# FAZ-17: VAR-MAP / risk engine
try:
    from faz17_engine.faz17_varmap import faz17_varmap  # type: ignore
    log.info("FAZ-17 yüklendi.")
except Exception as e:  # noqa: BLE001
    faz17_varmap = None
    log.warning("FAZ-17 yüklenemedi: %s", e)

# FAZ-22: META ENGINE
try:
    from faz22_engine.faz22_meta import faz22_meta_route  # type: ignore
    log.info("FAZ-22 META yüklendi.")
except Exception as e:  # noqa: BLE001
    faz22_meta_route = None
    log.warning("FAZ-22 META yüklenemedi: %s", e)

# FAZ-23: Pre-match model
try:
    from faz23_engine.faz23_model import faz23_prematch_predict  # type: ignore
    log.info("FAZ-23 yüklendi.")
except Exception as e:  # noqa: BLE001
    faz23_prematch_predict = None
    log.warning("FAZ-23 yüklenemedi: %s", e)

# Ultra OCR Engine v3 (C MODE FULL POWER) – varsa
try:
    from ocr_engine.ultra_ocr_v3 import ultra_ocr_process  # type: ignore
    log.info("Ultra OCR Engine v3 yüklendi.")
except Exception as e:  # noqa: BLE001
    ultra_ocr_process = None
    log.warning("Ultra OCR Engine v3 yüklenemedi: %s", e)


# ================================================================
#  GENEL UTIL FONKSİYONLAR (JSONL, profil, visual stack)
# ================================================================
def _safe_read_json(path: str, default: Any) -> Any:
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        log.error("JSON oku hatası (%s): %s", path, e)
        return default


def _safe_write_json(path: str, data: Any) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:  # noqa: BLE001
        log.error("JSON yazma hatası (%s): %s", path, e)


def _append_jsonl(path: str, row: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log.error("JSONL append hatası (%s): %s", path, e)


def _load_visual_stack() -> None:
    global VISUAL_STACK
    with VISUAL_STACK_LOCK:
        VISUAL_STACK = _safe_read_json(VISUAL_STACK_PATH, [])


def _save_visual_stack() -> None:
    with VISUAL_STACK_LOCK:
        _safe_write_json(VISUAL_STACK_PATH, VISUAL_STACK)


def visual_stack_add_item(item: Dict[str, Any]) -> None:
    with VISUAL_STACK_LOCK:
        item["id"] = f"VS-{int(time.time() * 1000)}"
        item["created_at"] = datetime.utcnow().isoformat() + "Z"
        VISUAL_STACK.append(item)
        _safe_write_json(VISUAL_STACK_PATH, VISUAL_STACK)
        log.info("Visual stack item eklendi: %s", item["id"])


def visual_stack_reset() -> None:
    global VISUAL_STACK
    with VISUAL_STACK_LOCK:
        VISUAL_STACK = []
        _safe_write_json(VISUAL_STACK_PATH, VISUAL_STACK)
        log.info("Visual stack resetlendi.")


def visual_stack_status() -> Dict[str, Any]:
    with VISUAL_STACK_LOCK:
        return {
            "count": len(VISUAL_STACK),
            "last_item": VISUAL_STACK[-1] if VISUAL_STACK else None,
        }


# Başlangıçta diskten yükle
_load_visual_stack()

# ================================================================
#  TELEGRAM BOT + FLASK APP
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)


# ================================================================
#  FAZ-CORE ORCHESTRATOR
# ================================================================
def faz_core_predict_from_meta(
    match_meta: Dict[str, Any],
    source: str = "manual",
    mode_profile: str = "DEFAULT",
) -> Dict[str, Any]:
    """
    Tüm fazları sırayla çalıştıran ana beyin.

    Dönen yapı:
    {
        "faz23": {...}  # pre-match
        "faz13": {...}  # ana tahmin
        "faz17": {...}  # risk/var-map
        "meta": {...},  # ek bilgiler
    }
    """
    result: Dict[str, Any] = {
        "faz23": None,
        "faz13": None,
        "faz17": None,
        "meta": {
            "source": source,
            "mode_profile": mode_profile,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    }

    # --- FAZ-10 STABILITY (opsiyonel) ---
    if faz10_stability_check:
        try:
            stability = faz10_stability_check()
            result["meta"]["faz10_stability"] = stability
        except Exception as e:  # noqa: BLE001
            log.error("FAZ-10 hata: %s", e)

    # --- FAZ-23 PRE-MATCH MODEL (opsiyonel) ---
    if faz23_prematch_predict:
        try:
            result["faz23"] = faz23_prematch_predict(match_meta)
        except Exception as e:  # noqa: BLE001
            log.error("FAZ-23 hata: %s", e)

    # --- FAZ-13 ANA PIPELINE ---
    if run_faz13_auto_pipeline:
        try:
            result["faz13"] = run_faz13_auto_pipeline(
                match_meta,
                prematch_hint=result["faz23"],
                mode_profile=mode_profile,
            )
        except TypeError:
            # Eski imza ile uyumluluk
            try:
                result["faz13"] = run_faz13_auto_pipeline(match_meta)
            except Exception as e:  # noqa: BLE001
                log.error("FAZ-13 (fallback) hata: %s", e)
        except Exception as e:  # noqa: BLE001
            log.error("FAZ-13 hata: %s", e)

    # --- FAZ-17 VAR-MAP / RISK ---
    if faz17_varmap and result.get("faz13"):
        try:
            result["faz17"] = faz17_varmap(result["faz13"])
        except Exception as e:  # noqa: BLE001
            log.error("FAZ-17 hata: %s", e)

    # --- FAZ-22 META ENGINE ---
    if faz22_meta_route:
        try:
            meta_out = faz22_meta_route(result)
            result["meta"]["faz22_meta"] = meta_out
        except Exception as e:  # noqa: BLE001
            log.error("FAZ-22 hata: %s", e)

    return result


# ================================================================
#  FLASK ROUTES (PING / HEALTH / WEBHOOK / API)
# ================================================================


@app.route("/ping", methods=["GET"])
def ping() -> Any:
    return jsonify(
        {
            "status": "ok",
            "service": "FAZ-CORE",
            "mode": "Fly.io",
            "time": int(time.time() * 1000),
        }
    )


@app.route("/health", methods=["GET"])
def health() -> Any:
    status = {"status": "ok", "faz10": None}
    if faz10_stability_check:
        try:
            status["faz10"] = faz10_stability_check()
        except Exception as e:  # noqa: BLE001
            status["status"] = "warn"
            status["faz10"] = {"error": str(e)}
    return jsonify(status)


@app.route("/webhook", methods=["POST"])
def telegram_webhook() -> Any:
    if request.method == "POST":
        try:
            update = telebot.types.Update.de_json(request.data.decode("utf-8"))
            bot.process_new_updates([update])
        except Exception as e:  # noqa: BLE001
            log.error("Webhook işlem hatası: %s", e)
    return "OK", 200


@app.route("/api/faz13/predict", methods=["POST"])
def api_faz13_predict() -> Any:
    payload = request.get_json(force=True, silent=True) or {}
    meta = payload.get("match_meta") or payload
    mode_profile = payload.get("mode_profile", "DEFAULT")
    result = faz_core_predict_from_meta(meta, source="api", mode_profile=mode_profile)
    return jsonify(result)


@app.route("/api/ocr/visual", methods=["POST"])
def api_ocr_visual() -> Any:
    """
    Ultra OCR Engine v3 varsa kullanır, yoksa 400 döner.
    Beklenen: JSON içinde { "image_url": "..."} veya base64 vb.
    """
    if not ultra_ocr_process:
        return jsonify({"error": "Ultra OCR Engine v3 not installed"}), 400

    payload = request.get_json(force=True, silent=True) or {}
    try:
        ocr_out = ultra_ocr_process(payload)
        global LAST_OCR_TEXT, LAST_OCR_META
        LAST_OCR_TEXT = ocr_out.get("raw_text")
        LAST_OCR_META = ocr_out.get("meta", {})
        return jsonify({"status": "ok", "ocr": ocr_out})
    except Exception as e:  # noqa: BLE001
        log.error("OCR API hata: %s", e)
        return jsonify({"error": str(e)}), 500


# ================================================================
#  TELEGRAM KOMUTLARI — START / PING / VISUAL STACK
# ================================================================


@bot.message_handler(commands=["start", "help"])
def cmd_start(message: telebot.types.Message) -> None:
    text = (
        "🧠 <b>HoopBrain FAZ-CORE</b>\n"
        "Sonsuz modlu basketbol beyni aktif.\n\n"
        "Temel komutlar:\n"
        "• /ping – sistem durumu\n"
        "• /add_visual_item – gönderdiğin görseli visual stack’e ekler\n"
        "• /visual_stack – şu anki visual kuyruk\n"
        "• /visual_stack_status – özet durum\n"
        "• /reset_visual – visual stack’i sıfırlar\n"
        "• /faz13_test – dummy meta ile test tahmin\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["ping"])
def cmd_ping(message: telebot.types.Message) -> None:
    status = {
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z",
        "run_mode": RUN_MODE,
        "visual_stack_count": len(VISUAL_STACK),
    }
    bot.reply_to(message, f"✅ <b>Ping</b>\n<code>{json.dumps(status, ensure_ascii=False, indent=2)}</code>")


# --------------------- VISUAL STACK KOMUTLARI -------------------


@bot.message_handler(commands=["add_visual_item"])
def cmd_add_visual_item(message: telebot.types.Message) -> None:
    """
    Kullanım:
      1) Görseli gönder, altına /add_visual_item yaz.
      2) Ya da sadece text ile de kullanabilirsin (ör: link + açıklama).
    """
    item: Dict[str, Any] = {
        "chat_id": message.chat.id,
        "user_id": message.from_user.id if message.from_user else None,
        "caption": message.caption or message.text or "",
    }

    # Foto / doküman yakala
    if message.photo:
        file_id = message.photo[-1].file_id
        item["type"] = "photo"
        item["file_id"] = file_id
    elif message.document:
        item["type"] = "document"
        item["file_id"] = message.document.file_id
    else:
        item["type"] = "text"

    visual_stack_add_item(item)
    bot.reply_to(
        message,
        f"🧩 Visual item eklendi.\n"
        f"Tür: <code>{item['type']}</code>\n"
        f"Kuyruk uzunluğu: <b>{len(VISUAL_STACK)}</b>",
    )


@bot.message_handler(commands=["visual_stack"])
def cmd_visual_stack(message: telebot.types.Message) -> None:
    with VISUAL_STACK_LOCK:
        if not VISUAL_STACK:
            bot.reply_to(message, "📭 Visual stack boş.")
            return

        preview_items = VISUAL_STACK[-10:]  # son 10
        lines = []
        for it in preview_items:
            lines.append(
                f"• {it.get('id')} | {it.get('type')} | {it.get('created_at')} | "
                f"{(it.get('caption') or '')[:60]}"
            )

    bot.reply_to(
        message,
        "🧩 <b>Visual Stack (son 10)</b>\n" + "\n".join(lines),
    )


@bot.message_handler(commands=["visual_stack_status"])
def cmd_visual_stack_status(message: telebot.types.Message) -> None:
    status = visual_stack_status()
    bot.reply_to(
        message,
        "📊 <b>Visual Stack Durumu</b>\n"
        f"Toplam öğe: <b>{status['count']}</b>\n"
        f"Son öğe: <code>{json.dumps(status['last_item'], ensure_ascii=False) if status['last_item'] else 'Yok'}</code>",
    )


@bot.message_handler(commands=["reset_visual"])
def cmd_reset_visual(message: telebot.types.Message) -> None:
    visual_stack_reset()
    bot.reply_to(message, "🧹 Visual stack sıfırlandı.")


# ----------------------- FAZ-13 TEST KOMUTU ---------------------


@bot.message_handler(commands=["faz13_test"])
def cmd_faz13_test(message: telebot.types.Message) -> None:
    """
    Küçük bir dummy meta ile FAZ-CORE pipeline test.
    Gerçek kullanımda normalize_manual_text / normalize_api_data vs. üzerinden gidilecek.
    """
    dummy_meta = {
        "league": "TEST",
        "home_team": "Alpha",
        "away_team": "Beta",
        "tipoff_ts": int(time.time()) + 3600,
        "odds": {
            "main_total": 165.5,
            "home_ml": 1.75,
            "away_ml": 2.05,
        },
    }
    result = faz_core_predict_from_meta(dummy_meta, source="telegram_test", mode_profile="DEFAULT")
    text = "🧪 <b>FAZ-13 TEST ÇIKTISI</b>\n\n" + "<code>" + json.dumps(
        result, ensure_ascii=False, indent=2
    ) + "</code>"
    bot.reply_to(message, text)


# ================================================================
#  TELEGRAM MESAJ FALLBACK — BURADA GERÇEK MAÇ KOMUTLARI ENTEGRE EDİLEBİLİR
# ================================================================


@bot.message_handler(content_types=["text"])
def fallback_text_handler(message: telebot.types.Message) -> None:
    """
    Buraya istersen:
      - /mac, /mac_img eski komut mantığını
      - Nesine / Mackolik linklerinden otomatik meta çıkarma
    gibi özellikleri tekrar entegre edebilirsin.
    Şimdilik sadece kullanıcıya yardım mesajı dönüyoruz.
    """
    if message.text.startswith("/"):
        # Bilinmeyen komut
        bot.reply_to(message, "❓ Bu komutu tanımıyorum. /help yazabilirsin.")
        return

    bot.reply_to(
        message,
        "📩 Mesajını aldım.\n"
        "Maç tahmini için yakında burada FAZ-13 ULTRA PREDICT akışı olacak.\n"
        "Şimdilik /help ile mevcut komutlara bakabilirsin.",
    )


# ================================================================
#  BOOTSTRAP: WEBHOOK/POLLING AYARI
# ================================================================


def setup_webhook() -> None:
    if not WEBHOOK_URL:
        log.error("WEBHOOK_URL env tanımsız, webhook kurulamaz.")
        return
    webhook_url = WEBHOOK_URL.rstrip("/") + "/webhook"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=webhook_url, max_connections=40)
    log.info("Telegram webhook kuruldu: %s", webhook_url)


def run_polling() -> None:
    log.info("Polling modunda başlıyor...")
    bot.remove_webhook()
    bot.infinity_polling(timeout=30, long_polling_timeout=20)


# ================================================================
#  MAIN
# ================================================================
if RUN_MODE == "WEBHOOK":
    setup_webhook()
else:
    # Polling'i ayrı thread’de çalıştır, Flask sadece health/ping için de kullanılabilir.
    t = threading.Thread(target=run_polling, daemon=True)
    t.start()
    log.info("Polling thread başlatıldı.")

# Fly.io için: "main:app" entrypoint’i kullanılabilir.
# Lokal çalıştırma için:
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    log.info("Flask app starting on 0.0.0.0:%d (RUN_MODE=%s)", port, RUN_MODE)
    app.run(host="0.0.0.0", port=port)
