# -*- coding: utf-8 -*-
"""
Zeynal Core AI – FAZ-13 FULL AUTO FETCH main.py

Bu dosya:
- Telegram botunu ayağa kaldırır
- /mac komutunu işler
- faz13_engine.faz13_orchestrator.run_faz13_auto_pipeline ile
  HYBRID BASELINE + LIVE PROVIDERS + FAZ-23 META sonuçlarını alır
- Çıktıyı senin alıştığın FAZ-13 + FAZ-23 metin formatında üretir
"""

import os
import logging
from typing import Dict, Tuple, Optional

import telebot
from flask import Flask, request

# ================================================================
# LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("zeynal-core-main")

# ================================================================
# ENV
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # örn: https://zeynal-bot-core.fly.dev/webhook
FLASK_HOST = "0.0.0.0"
FLASK_PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

# Opsiyonel: ana kanal / log kanalı vs.
MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID")

# ================================================================
# FAZ IMPORTLARI
# ================================================================
# Eski mimariyi bozmamak için FAZ-10/11/12 importları duruyor;
# kritik olan FAZ-13 Orchestrator (FULL AUTO FETCH).
try:
    from faz10_engine.faz10_stability import faz10_stability_check  # type: ignore
except Exception:  # noqa: BLE001
    faz10_stability_check = None

try:
    from faz11_engine.faz11_feedback import (  # type: ignore
        faz11_feedback,
        faz11_last_summary,
    )
except Exception:  # noqa: BLE001
    faz11_feedback, faz11_last_summary = None, None

try:
    from faz12_engine.faz12_autoadjust import (  # type: ignore
        faz12_run_once,
        faz12_auto_profile,
    )
except Exception:  # noqa: BLE001
    faz12_run_once, faz12_auto_profile = None, None

from faz13_engine.faz13_orchestrator import (  # type: ignore
    run_faz13_auto_pipeline,
    normalize_manual_text,
    normalize_api_data,
    normalize_visual_meta,
)

# ================================================================
# TELEGRAM + FLASK
# ================================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ================================================================
# YARDIMCI FONKSİYONLAR
# ================================================================


def parse_match_command(text: str) -> Tuple[str, str, str, str]:
    """
    /mac NBA | 2025-12-11 | Lakers - Bulls
    /mac Türkiye BSL | 2025-12-12 | Efes - Fenerbahçe
    formatını çözer.

    Dönen tuple: (league, date_str, home, away)
    """
    # /mac kısmını at
    raw = text.split(" ", 1)[1].strip() if " " in text else ""
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        raise ValueError("Komut formatı hatalı. Örnek: /mac NBA | 2025-12-11 | Lakers - Bulls")

    league = parts[0]
    date_str = parts[1]
    teams_part = parts[2]

    if "-" not in teams_part:
        raise ValueError("Takımlar 'Ev - Deplasman' formatında olmalı")

    home, away = [t.strip() for t in teams_part.split("-", 1)]
    return league, date_str, home, away


def _fmt_bool_label(flag: bool, t_true: str, t_false: str) -> str:
    return t_true if flag else t_false


def fmt_faz13_message(cmd: Dict, result: Dict) -> str:
    """
    FAZ-13 / FAZ-23 çıktısını tek metne çevirir.
    cmd: {"league", "date", "home", "away"}
    result: run_faz13_auto_pipeline sözlüğü
    """
    league = cmd["league"]
    date_str = cmd["date"]
    home = cmd["home"]
    away = cmd["away"]

    family = result.get("family", "GENERICMID")
    total = float(result["total"])
    band_lo, band_hi = result["band"]
    vec_lo, vec_mid, vec_hi = result["vector"]
    q1, q2, q3, q4 = result["periods"]
    home_pts, away_pts = result["team_scores"]

    analysis = result.get("analysis", {})
    meta23 = result.get("meta23", {})
    live_ctx = result.get("live_ctx", {})

    league_baseline = analysis.get("league_baseline", total)
    tempo_style = analysis.get("tempo_style", "MID")
    volatility = analysis.get("volatility", 0.0)
    def_factor = analysis.get("def", 0.0)
    match_type = analysis.get("match_type", "CLUB")
    news_range = analysis.get("news_range", "TOTAL: NEUTRAL")
    home_boost = analysis.get("home_boost", 0.0)

    live_is_live = bool(live_ctx.get("is_live"))
    live_total = live_ctx.get("live_total")
    live_pace = live_ctx.get("pace_delta")
    live_provider = live_ctx.get("provider")

    m_over = float(meta23.get("model_over", 0.5))
    m_under = float(meta23.get("model_under", 0.5))
    primary_total = float(meta23.get("primary_total", total))
    flags = meta23.get("flags", [])

    # -------- HEADER --------
    lines = []

    lines.append(
        f"🏀 FAZ-13 Maç Tahmini (Pro) Maç: {home} - {away} "
        f"Tarih: {date_str} Lig: {league} | Lig Family: {family}"
    )
    lines.append("—" * 65)

    # -------- TOPLAM --------
    lines.append(
        "🐌 TOPLAM TAHMİNİ Fusion Total: "
        f"{league} | {home} - {away} | TOTAL {total:.1f} band "
        f"({band_lo:.1f}-{band_hi:.1f}) (NEUTRAL) "
        f"Bant: {band_lo:.1f} – {band_hi:.1f} "
        f"Score Vector: ({vec_lo:.1f}, {vec_mid:.1f}, {vec_hi:.1f})"
    )

    # -------- PERİYOT --------
    lines.append("📊 PERİYOT PROJEKSİYONLARI "
                 f"1Ç: {q1:.1f} 2Ç: {q2:.1f} 3Ç: {q3:.1f} 4Ç: {q4:.1f} "
                 f"İY: {q1 + q2:.1f} | İİY: {q3 + q4:.1f} | Maç: {total:.1f}")

    # -------- TAKIM SKOR --------
    lines.append(
        "🎯 TAKIM SKOR TAHMİNİ Ev Sahibi "
        f"({home}): {home_pts:.1f} Deplasman ({away}): {away_pts:.1f}"
    )

    # -------- ANALİZ / NEWS --------
    lines.append("🧠 HABER / ANALİZ "
                 f"• Lig baseline (iç çekirdek): {league_baseline:.1f} "
                 f"• Tempo stili: {tempo_style} "
                 f"• Volatilite → Pace:{volatility:.2f} | Def:{def_factor:.2f} "
                 f"• Maç tipi: {match_type} • News Range: {news_range} "
                 f"TOTAL: NEUTRAL, tempo: {tempo_style}, flags: SAFEBaseline")

    # Lig family ve home boost detayı
    lines.append(
        "Sebep / Açıklamalar: "
        f"- League baseline ~ {league_baseline:.1f} "
        f"- League family ~ {family} "
        f"- League detect: match by league keyword: {league.lower()} "
        f"- Home advantage boost ~ {home_boost:+.2f} (family={family})"
    )

    # -------- LIVE DURUMU --------
    live_mode_str = _fmt_bool_label(live_is_live, "LIVE", "PREMATCH")
    live_desc_parts = [f"Mod: {live_mode_str}"]

    if live_total is not None:
        live_desc_parts.append(f"Live total line: {live_total:.1f}")
    if live_pace is not None:
        live_desc_parts.append(f"Pace delta: {live_pace:+.1f}")
    if live_provider:
        live_desc_parts.append(f"Provider: {live_provider}")

    lines.append("📡 CANLI DURUM • " + " • ".join(live_desc_parts))

    # -------- FAZ-23 META --------
    lines.append("—" * 65)
    lines.append("🧠 FAZ-23 META DEĞERLENDİRME")
    lines.append(
        f"🏆 FAZ-23 PREMATCH / LIVE Meta Tahmin "
        f"🏀 Lig: {league} Maç: {home} - {away}"
    )

    lines.append(
        "📊 Toplam Sayı Barem Analizi • Ana total çizgisi: "
        f"{primary_total:.1f} • Model over ölçüsü : {m_over:.3f} "
        f"• Model under ölçüsü : {m_under:.3f}"
    )

    # Meta özet
    meta_flags_txt = ", ".join(flags) if flags else "yok"
    lines.append(
        "🧾 Haber / Yorum Özeti: - TOTAL: NEUTRAL, tempo: MID, "
        f"flags: {meta_flags_txt} "
        "📌 FAZ-23 Eğilim: OVER / UNDER tarafları model skoruna göre "
        "dengeye yakın değerlendiriliyor."
    )

    return "\n".join(lines)


# ================================================================
# TELEGRAM HANDLERLAR
# ================================================================


@bot.message_handler(commands=["start", "help"])
def handle_start(message: telebot.types.Message) -> None:
    text = (
        "Selam, ben Zeynal Core AI 🧠\n\n"
        "Komutlar:\n"
        "• /mac LIG | YYYY-MM-DD | Ev - Deplasman\n"
        "   Ör: /mac NBA | 2025-12-11 | Lakers - Bulls\n\n"
        "FAZ-13 FULL AUTO FETCH + HYBRID BASELINE + LIVE PROVIDERS "
        "ve FAZ-23 META değerlendirmesini tek çıktı olarak veririm."
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["mac"])
def handle_mac(message: telebot.types.Message) -> None:
    try:
        league, date_str, home, away = parse_match_command(message.text or "")

        cmd = {
            "league": league,
            "date": date_str,
            "home": home,
            "away": away,
        }

        # Şu an prematch_total_hint ve recent_points_avg yok,
        # ileride kitapçı / istatistik entegrasyonuna bağlanabilir.
        result = run_faz13_auto_pipeline(
            league=league,
            date_str=date_str,
            home=home,
            away=away,
            prematch_total_hint=None,
            recent_points_avg=None,
        )

        text = fmt_faz13_message(cmd, result)
        bot.reply_to(message, text)

        # İstersen ana kanala da logla
        if MAIN_CHANNEL_ID:
            try:
                bot.send_message(MAIN_CHANNEL_ID, text)
            except Exception as e:  # noqa: BLE001
                log.warning("Ana kanala mesaj atılamadı: %s", e)

    except Exception as e:  # noqa: BLE001
        log.exception("handle_mac hata")
        bot.reply_to(
            message,
            f"Komut veya analiz hatası: {e}\n"
            "Örnek format: /mac NBA | 2025-12-11 | Lakers - Bulls",
        )


@bot.message_handler(commands=["faz11_last"])
def handle_faz11_last(message: telebot.types.Message) -> None:
    """Opsiyonel: FAZ-11 son özet (varsa)."""
    if not faz11_last_summary:
        bot.reply_to(message, "FAZ-11 modülü bu build'de aktif değil.")
        return

    try:
        summary = faz11_last_summary()
        bot.reply_to(message, f"FAZ-11 Son Özet:\n{summary}")
    except Exception as e:  # noqa: BLE001
        log.exception("faz11_last hata")
        bot.reply_to(message, f"FAZ-11 okunurken hata: {e}")


# ================================================================
# WEBHOOK / FLASK
# ================================================================


@app.route("/webhook", methods=["POST"])
def telegram_webhook() -> str:
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK"


@app.route("/", methods=["GET"])
def healthcheck() -> str:
    return "OK"


def main() -> None:
    log.info("Starting Zeynal Core AI bot (FAZ-13 FULL AUTO FETCH build)")
    # Webhook ayarı – Fly.io üzerinde dışarıdan çağrılıyor
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        log.info("Webhook set: %s", WEBHOOK_URL)
    else:
        log.warning("WEBHOOK_URL tanımlı değil, sadece polling ile çalışabilir.")

    app.run(host=FLASK_HOST, port=FLASK_PORT)


if __name__ == "__main__":
    main()
