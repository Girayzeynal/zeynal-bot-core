import os
import json
import time
import logging
from typing import Optional, Dict, Any

import telebot
from flask import Flask, request

import numpy as np
import pandas as pd

# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ================================================================
# 🔧 CONFIG
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Örn: https://zeynal-bot-core.fly.dev/webhook
FAZ23_ENABLED = os.getenv("FAZ23_ENABLED", "0") == "1"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env değişkeni tanımlı değil. Lütfen Fly.io env'e ekle.")

if not WEBHOOK_URL:
    log.warning("WEBHOOK_URL env değişkeni tanımlı değil. Webhook kurulumu yapılmayacak.")

# ================================================================
# 🔍 FAZ-13 OCR DEBUG STATE
# ================================================================
LAST_OCR_TEXT = None
LAST_OCR_META: Dict[str, Any] = {}

# ================================================================
#  FAZ-10 / FAZ-11 / FAZ-12 / FAZ-13 IMPORTLARI
# ================================================================
from faz10_engine.faz10_stability import faz10_stability_check
from faz11_engine.faz11_feedback import (
    faz11_feedback,
    faz11_last_summary,
)
from faz12_engine.faz12_autoadjust import (
    faz12_run_once,
    faz12_auto_profile,
)
from faz13_engine.faz13_orchestrator import (
    normalize_manual_text,
    normalize_api_data,
    normalize_visual_meta,
    run_faz13_auto_pipeline,
    faz13_daily_coupon,
    run_faz23_meta_engine,
    build_faz23_safe_coupon,
)

# ================================================================
# 🔧 TELEGRAM & FLASK
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ================================================================
# 🔁 CORE YARDIMCI: FAZ-13 (+ opsiyonel FAZ-23) ÇALIŞTIR
# ================================================================
def run_core_prediction(
    *,
    source: str,
    manual_text: Optional[str] = None,
    api_data: Optional[Dict[str, Any]] = None,
    visual_meta: Optional[Dict[str, Any]] = None,
    market_data: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Tek kapı: FAZ-13 ana pipeline + isteğe bağlı FAZ-23 meta katmanı.

    Dönüş yapısı:
    {
        "faz13": {...},
        "faz23": {... veya None},
        "coupon": {...},
        "debug": {...}
    }
    """
    # --- Normalizasyon katmanı ---
    norm_manual = normalize_manual_text(manual_text) if manual_text else None
    norm_api = normalize_api_data(api_data) if api_data else None
    norm_visual = normalize_visual_meta(visual_meta) if visual_meta else None

    # --- FAZ-13 ana pipeline ---
    faz13_result = run_faz13_auto_pipeline(
        source=source,
        manual_text=norm_manual,
        api_data=norm_api,
        visual_meta=norm_visual,
        market_data=market_data,
        profile=profile,
    )

    faz23_result = None
    safe_coupon = None

    # --- Opsiyonel FAZ-23 meta-katman ---
    if FAZ23_ENABLED:
        faz23_result = run_faz23_meta_engine(
            faz13_result=faz13_result,
            market_data=market_data,
            profile=profile,
        )
        safe_coupon = build_faz23_safe_coupon(faz23_result)

    return {
        "faz13": faz13_result,
        "faz23": faz23_result,
        "coupon": safe_coupon if safe_coupon is not None else faz13_daily_coupon(faz13_result),
        "debug": {
            "source": source,
            "has_manual": manual_text is not None,
            "has_api": api_data is not None,
            "has_visual": visual_meta is not None,
            "has_market": market_data is not None,
            "faz23_enabled": FAZ23_ENABLED,
        },
    }


# ================================================================
# 🧠 YARDIMCI: ÇIKTI FORMATLAYICI
# ================================================================
def format_prediction_message(core_result: Dict[str, Any]) -> str:
    faz13 = core_result.get("faz13", {})
    faz23 = core_result.get("faz23")
    coupon = core_result.get("coupon")

    pred = faz13.get("prediction", {})
    risk = faz13.get("risk", {})
    meta = faz13.get("meta", {})

    lines = []
    lines.append("🔮 <b>FAZ-13 Çekirdek Tahmin</b>")
    if "score_band" in pred:
        sb = pred["score_band"]
        lines.append(f"• Skor bandı: <b>{sb.get('min')} - {sb.get('max')}</b>")
    if "total_points" in pred:
        tp = pred["total_points"]
        lines.append(f"• Toplam sayı tahmini: <b>{tp.get('value')}</b> (±{tp.get('delta')})")
    if "side" in pred:
        lines.append(f"• Taraf eğilimi: <b>{pred['side']}</b>")

    if risk:
        lines.append("")
        lines.append("📉 <b>Risk Profili (FAZ-13)</b>")
        lines.append(f"• Global risk skoru: <b>{risk.get('global_score')}</b>")
        lines.append(f"• Varyans seviyesi: <b>{risk.get('variance_level')}</b>")
        lines.append(f"• Güven puanı: <b>{risk.get('confidence')}</b>/100")

    if faz23:
        lines.append("")
        lines.append("🧠 <b>FAZ-23 Meta-Engine</b>")
        lines.append(f"• Market uyum skoru: <b>{faz23.get('market_alignment')}</b>/100")
        lines.append(f"• Sharpened risk: <b>{faz23.get('sharpened_risk')}</b>")
        lines.append(f"• Filter modu: <b>{faz23.get('filter_mode')}</b>")

    if coupon:
        lines.append("")
        lines.append("🎫 <b>Kupon Önerisi</b>")
        for leg in coupon.get("legs", []):
            lines.append(
                f"• {leg.get('market')} → <b>{leg.get('pick')}</b> "
                f"(@{leg.get('line')})  | risk: {leg.get('risk_tag')}"
            )

    if meta:
        lines.append("")
        lines.append("ℹ️ <b>Maç Meta</b>")
        league = meta.get("league")
        tipoff = meta.get("tipoff")
        if league:
            lines.append(f"• Lig: <b>{league}</b>")
        if tipoff:
            lines.append(f"• Maç saati: <b>{tipoff}</b>")

    return "\n".join(lines)


# ================================================================
# 🤖 TELEGRAM KOMUTLARI
# ================================================================
@bot.message_handler(commands=["start", "help"])
def handle_start(message):
    text = (
        "🏀 HoopBrain FAZ-13 + FAZ-23 çekirdeği aktif.\n\n"
        "/status → Sistem durumu\n"
        "/mac ... → Manuel metinden analiz\n"
        "/faz23_on → FAZ-23 meta katman (sadece log için, gerçek kontrol ENV)\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def handle_status(message):
    stability = faz10_stability_check()
    last_fb = faz11_last_summary() or "Henüz özet yok."
    faz23_text = "AÇIK" if FAZ23_ENABLED else "KAPALI"

    text = (
        "✅ Sistem durumu:\n"
        f"• FAZ-10 stabilite: {stability}\n"
        f"• FAZ-23 meta-engine: {faz23_text}\n\n"
        f"📝 Son FAZ-11 özeti:\n{last_fb}"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["faz23_on", "faz23_off"])
def handle_faz23_toggle(message):
    # Gerçek kontrol ENV ile, burada sadece kullanıcıya bilgi veriyoruz
    cmd = message.text.split()[0].lstrip("/")
    desired = "on" in cmd
    text = (
        "⚙️ FAZ-23, ENV ile kontrol edilir.\n"
        f"Şu anki durum: <b>{'AÇIK' if FAZ23_ENABLED else 'KAPALI'}</b>\n\n"
        "Fly.io üzerinde:\n"
        "  FAZ23_ENABLED=1 → AÇIK\n"
        "  FAZ23_ENABLED=0 → KAPALI"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["mac"])
def handle_mac(message):
    """
    Basit versiyon: Kullanıcı /mac komutundan sonra manuel açıklama girer.
    Örnek: /mac IND - CHI 239.5 barem, pace yüksek vs...
    """
    try:
        manual = message.text[len("/mac"):].strip()
        if not manual:
            bot.reply_to(message, "Kardeşim, /mac komutundan sonra maç açıklamasını da yaz :)")
            return

        core_result = run_core_prediction(
            source="manual",
            manual_text=manual,
            api_data=None,
            visual_meta=None,
            market_data=None,  # İstiyorsan buraya barem/oran datasını enjekte edersin
            profile=faz12_auto_profile(),  # FAZ-12 otomatik profil
        )

        # FAZ-11 feedback kaydı
        faz11_feedback(
            raw_input=manual,
            faz13_output=core_result.get("faz13"),
            faz23_output=core_result.get("faz23"),
        )

        bot.reply_to(message, format_prediction_message(core_result))
    except Exception as e:
        log.exception("handle_mac sırasında hata")
        bot.reply_to(message, f"❌ İçeride bir yerde patladık: {e}")


# ================================================================
# 🌐 FLASK + WEBHOOK
# ================================================================
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200


@app.route("/health", methods=["GET"])
def health_check():
    return {"status": "ok", "faz23": FAZ23_ENABLED}, 200


def setup_webhook():
    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL tanımsız, webhook kurulmayacak.")
        return
    full_url = WEBHOOK_URL.rstrip("/") + "/webhook"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=full_url)
    log.info(f"Telegram webhook set edildi: {full_url}")


if __name__ == "__main__":
    # Local run için: webhook kur, Flask'i başlat
    setup_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
