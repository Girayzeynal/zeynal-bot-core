# -*- coding: utf-8 -*-
"""
Zeynal Core AI – FAZ-13 + FAZ-23 FULL AUTO main.py

Bu dosya:
- Telegram botunu ayağa kaldırır
- /status, /mac komutlarını işler
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

MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID")
FAZ23_ENV_FLAG = os.getenv("FAZ23_META_MODE", "ON")

# ================================================================
# FAZ IMPORTLARI
# ================================================================
# Eski mimariyi bozmamak için FAZ-10/11/12 importları duruyor;
# kritik olan FAZ-13 Orchestrator (FULL AUTO FETCH).

try:
    from faz10_engine.faz10_stability import faz10_stability_check  # type: ignore
except Exception:  # noqa: BLE001
    faz10_stability_check = None  # type: ignore

try:
    from faz11_engine.faz11_feedback import (  # type: ignore
        faz11_feedback,
        faz11_last_summary,
    )
except Exception:  # noqa: BLE001
    faz11_feedback, faz11_last_summary = None, None  # type: ignore

try:
    from faz12_engine.faz12_autoadjust import (  # type: ignore
        faz12_run_once,
        faz12_auto_profile,
    )
except Exception:  # noqa: BLE001
    faz12_run_once, faz12_auto_profile = None, None  # type: ignore

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
def parse_match_command(text: str):
    """
    Kabul edilen formatlar:
      1) /mac NBA | 2025-12-12 | Milwaukee - Boston
      2) /mac NBA 2025-12-12 Milwaukee - Boston
      3) /mac NBA 2025-12-12 Milwaukee-Boston
    """
    raw = (text or "").strip()

    # Komut prefix
    if raw.lower().startswith("/mac"):
        raw = raw[4:].strip()

    # 1) Pipe'lı format
    if "|" in raw:
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 3:
            raise ValueError(
                "Komut formatı hatalı.\nÖrnek: /mac NBA | 2025-12-11 | Lakers - Bulls"
            )
        league = parts[0]
        date_str = parts[1]
        teams = parts[2]
    else:
        # 2) Pipe'sız format: "<LEAGUE> <YYYY-MM-DD> <HOME - AWAY>"
        tokens = raw.split()
        if len(tokens) < 3:
            raise ValueError(
                "Komut formatı hatalı.\nÖrnek: /mac NBA | 2025-12-11 | Lakers - Bulls"
            )
        league = tokens[0].strip()
        date_str = tokens[1].strip()
        teams = " ".join(tokens[2:]).strip()

    # Tire karakterlerini normalize et
    teams_norm = (
        teams.replace("—", "-")
             .replace("–", "-")
             .replace("−", "-")
    )

    # "Home - Away" ayır
    if "-" not in teams_norm:
        raise ValueError(
            "Komut formatı hatalı.\nÖrnek: /mac NBA | 2025-12-11 | Lakers - Bulls"
        )
    home, away = [x.strip() for x in teams_norm.split("-", 1)]

    if not league or not date_str or not home or not away:
        raise ValueError(
            "Komut formatı hatalı.\nÖrnek: /mac NBA | 2025-12-11 | Lakers - Bulls"
        )

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

    lines = []

    # HEADER
    lines.append(
        f"🏀 FAZ-13 Maç Tahmini (Pro)\n"
        f"Maç: {home} - {away}\n"
        f"Tarih: {date_str} | Lig: {league} | Lig Family: {family}"
    )
    lines.append("—" * 65)

    # TOPLAM
    lines.append(
        "📊 TOPLAM TAHMİNİ\n"
        f"Fusion Total: {total:.1f} | Bant: {band_lo:.1f} – {band_hi:.1f}\n"
        f"Score Vector: ({vec_lo:.1f}, {vec_mid:.1f}, {vec_hi:.1f})"
    )

    # PERİYOT
    lines.append(
        "⏱ PERİYOT PROJEKSİYONLARI\n"
        f"1Ç: {q1:.1f}  2Ç: {q2:.1f}  3Ç: {q3:.1f}  4Ç: {q4:.1f}\n"
        f"İY: {q1 + q2:.1f} | İİY: {q3 + q4:.1f} | Maç: {total:.1f}"
    )

    # TAKIM SKOR
    lines.append(
        "🎯 TAKIM SKOR TAHMİNİ\n"
        f"Ev Sahibi ({home}): {home_pts:.1f}\n"
        f"Deplasman ({away}): {away_pts:.1f}"
    )

    # ANALİZ / NEWS
    lines.append(
        "📝 ANALİZ / NEWS\n"
        f"• Lig baseline (çekirdek): {league_baseline:.1f}\n"
        f"• Tempo stili: {tempo_style}\n"
        f"• Volatilite → Pace:{volatility:.2f} | Def:{def_factor:.2f}\n"
        f"• Maç tipi: {match_type}\n"
        f"• News Range: {news_range}\n"
        f"TOTAL: NEUTRAL, tempo: {tempo_style}, flags: SAFEBaseline"
    )

    lines.append(
        "Sebep / Açıklamalar:\n"
        f"- League baseline ~ {league_baseline:.1f}\n"
        f"- League family ~ {family}\n"
        f"- League detect: match by league keyword: {league.lower()}\n"
        f"- Home advantage boost ~ {home_boost:+.2f} (family={family})"
    )

    # LIVE DURUM
    live_mode_str = _fmt_bool_label(live_is_live, "LIVE", "PREMATCH")
    live_desc_parts = [f"Mod: {live_mode_str}"]
    if live_total is not None:
        live_desc_parts.append(f"Live total line: {live_total:.1f}")
    if live_pace is not None:
        live_desc_parts.append(f"Pace delta: {live_pace:+.1f}")
    if live_provider:
        live_desc_parts.append(f"Provider: {live_provider}")

    lines.append("📡 CANLI DURUM • " + " • ".join(live_desc_parts))

    # FAZ-23 META
    lines.append("—" * 65)
    lines.append("🧠 FAZ-23 META DEĞERLENDİRME")
    lines.append(
        f"🏀 Lig: {league} | Maç: {home} - {away}"
    )
    lines.append(
        "📊 Toplam Sayı Barem Analizi\n"
        f"• Ana total çizgisi: {primary_total:.1f}\n"
        f"• Model over ölçüsü : {m_over:.3f}\n"
        f"• Model under ölçüsü : {m_under:.3f}"
    )

    meta_flags_txt = ", ".join(flags) if flags else "yok"
    lines.append(
        "🧾 Haber / Yorum Özeti:\n"
        f"- TOTAL: NEUTRAL, tempo: MID, flags: {meta_flags_txt}\n"
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
        "🏀 HoopBrain FAZ-13 + FAZ-23 çekirdeği aktif.\n\n"
        "/status  → Sistem durumu\n"
        "/mac ... → Manuel metinden analiz\n"
        "/faz23_on → FAZ-23 meta katman (sadece log için, gerçek kontrol ENV)\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def handle_status(message: telebot.types.Message) -> None:
    lines = []
    lines.append("📡 Sistem Durumu\n")
    lines.append("FAZ-13: AKTİF (Full Auto Orchestrator)")
    lines.append(f"FAZ-23 META: {FAZ23_ENV_FLAG} (ENV: FAZ23_META_MODE)")

    if faz10_stability_check:
        try:
            stab = faz10_stability_check()
            lines.append(f"FAZ-10 Stabilite: {stab}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"FAZ-10 okunurken hata: {e}")

    if faz11_last_summary:
        try:
            last = faz11_last_summary()
            lines.append("\nFAZ-11 Son Özet:")
            lines.append(str(last))
        except Exception as e:  # noqa: BLE001
            lines.append(f"FAZ-11 okunurken hata: {e}")

    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=["faz23_on"])
def handle_faz23_on(message: telebot.types.Message) -> None:
    bot.reply_to(
        message,
        f"FAZ-23 META katman env durumu: {FAZ23_ENV_FLAG}\n"
        "(Gerçek kontrol: ENV → FAZ23_META_MODE)",
    )


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

        # İsteğe bağlı: FAZ-12 auto profile (hata verirse yut)
        if faz12_auto_profile:
            try:
                _profile = faz12_auto_profile(
                    meta=result.get("meta23", {}),
                    pred=result,
                )
                log.info("FAZ-12 profile hesaplandı: %s", _profile)
            except TypeError as e:  # tam senin gördüğün hata burada yakalanacak
                log.warning("FAZ-12 signature uyumsuz: %s", e)
            except Exception as e:  # noqa: BLE001
                log.exception("FAZ-12 çalışırken hata: %s", e)

        text = fmt_faz13_message(cmd, result)
        bot.reply_to(message, text)

        if MAIN_CHANNEL_ID:
            try:
                bot.send_message(MAIN_CHANNEL_ID, text)
            except Exception as e:  # noqa: BLE001
                log.warning("Ana kanala mesaj atılamadı: %s", e)

    except Exception as e:  # noqa: BLE001
        log.exception("handle_mac hata")
        bot.reply_to(
            message,
            f"❌ İçeride bir yerde patladık: {e}\n"
            "Örnek format: /mac NBA | 2025-12-11 | Lakers - Bulls",
        )


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
    log.info("Starting Zeynal Core AI bot (FAZ-13 + FAZ-23 FULL AUTO build)")

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
