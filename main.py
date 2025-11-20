import os
import json
import time
import logging

import telebot
import numpy as np
import pandas as pd
from flask import Flask, request

# ================================================================
# 🔧 LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ================================================================
# 🔧 CONFIG
# ================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Örn: https://zeynal-bot-core.fly.dev/webhook

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env değişkeni tanımlı değil!")

if not WEBHOOK_URL:
    log.warning("WEBHOOK_URL tanımlı değil! Webhook set edilemeyecek.")

# Telegram bot (GLOBAL parse_mode = HTML → Markdown hatası yok)
bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",              # Markdown yok, HTML güvenli
    disable_web_page_preview=True
)

# ================================================================
# 🌐 FLASK APP (Health check + Webhook)
# ================================================================
app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    # Fly.io health check
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """
    Telegram'ın gönderdiği update'leri alıp TeleBot'a paslıyoruz.
    Hata olursa loglayıp 200 dönüyoruz ki Telegram webhook'u düşürmesin.
    """
    try:
        json_update = request.get_json()
        update = telebot.types.Update.de_json(json_update)
        bot.process_new_updates([update])
    except Exception as e:
        log.error(f"Webhook update işlenirken hata: {e}")
    return "OK", 200


# ================================================================
# 📌 FAZ-7.9 MEMORY ENGINE
# ================================================================
MEMORY_FILE = "faz7_memory.json"


def init_memory():
    if not os.path.exists(MEMORY_FILE):
        data = {
            "days": [],  # günlük kayıtlar: {ts, conf, edge}
            "safe": 0,
            "bal": 0,
            "agg": 0
        }
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=4)


def load_memory():
    init_memory()
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)


def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=4)


def register_daily_stats(conf: float, edge: float):
    """
    FAZ-7 REGISTER → günlük confidence & edge kaydı.
    """
    mem = load_memory()
    today = {
        "ts": int(time.time()),
        "conf": float(conf),
        "edge": float(edge)
    }

    mem["days"].append(today)

    # sadece son 7 günü tut
    if len(mem["days"]) > 7:
        mem["days"] = mem["days"][-7:]

    save_memory(mem)


def faz79_brain():
    """
    FAZ-7.9 STRATEJİ BEYNİ
    Memory'den 7 günlük trend, volatilite, mode vs hesaplar.
    """
    mem = load_memory()
    days = mem["days"]

    if len(days) == 0:
        return {
            "mode": "INIT",
            "conf": 0.0,
            "edge": 0.0,
            "trend": "INIT",
            "slope": 0.0,
            "vol": 0.0,
            "stake_norm": 1.00,
            "safe": False,
            "bal": True,
            "agg": False,
        }

    df = pd.DataFrame(days)
    df["t"] = range(len(df))

    avg_conf = float(df["conf"].mean())
    avg_edge = float(df["edge"].mean())

    # linear regression slope (SVD hatasına karşı korumalı)
    try:
        slope = float(np.polyfit(df["t"], df["conf"], 1)[0])
    except Exception as e:
        log.warning(f"FAZ-7.9 slope hesaplanırken hata (SVD fallback): {e}")
        slope = 0.0

    if slope > 0.01:
        trend = "UP"
    elif slope < -0.01:
        trend = "DOWN"
    else:
        trend = "FLAT"

    vol = float(df["conf"].std() if len(df) > 1 else 0.0)

    # Basit mod seçimi
    if avg_conf > 0.7 and avg_edge > 0.05:
        mode = "SAFE"
    elif avg_conf > 0.4:
        mode = "BAL"
    else:
        mode = "AGG"

    mem["safe"] = int(mode == "SAFE")
    mem["bal"] = int(mode == "BAL")
    mem["agg"] = int(mode == "AGG")
    save_memory(mem)

    return {
        "mode": mode,
        "conf": round(avg_conf, 3),
        "edge": round(avg_edge, 3),
        "trend": trend,
        "slope": round(slope, 4),
        "vol": round(vol, 4),
        "stake_norm": 1.00,
        "safe": mode == "SAFE",
        "bal": mode == "BAL",
        "agg": mode == "AGG",
    }


# ================================================================
# 🧠 FAZ-8.1 – CORE CALIBRATION ENGINE
#    (FAZ-7.9 hafızasını kullanarak conf/edge/stake ayarı)
#    Bu çekirdek, FAZ-8.2 LMF SHIELD tarafından refine edilecek.
# ================================================================
def _faz81_core_calibration(raw_conf: float,
                            raw_edge: float,
                            base_stake: float = 1.0) -> dict:
    """
    FAZ-8.1 core:
      - FAZ-7.9 beyninden mode/trend/vol alır
      - conf / edge / stake değerini temel kurallarla ayarlar
    """
    brain = faz79_brain()

    mode = brain["mode"]
    trend = brain["trend"]
    vol = brain["vol"]

    conf = float(raw_conf)
    edge = float(raw_edge)
    stake = float(base_stake)

    # INIT veya bilinmeyen mod → sadece passthrough
    if mode not in ("SAFE", "BAL", "AGG"):
        return {
            "engine": "FAZ-8.1",
            "mode": mode,
            "trend": trend,
            "vol": round(vol, 4),
            "conf": round(conf, 3),
            "edge": round(edge, 3),
            "stake": round(stake, 2),
        }

    # Mode bazlı çarpanlar
    if mode == "SAFE":
        stake_factor = 0.90   # SAFE modda daha yumuşak
        conf_boost = 0.03
    elif mode == "BAL":
        stake_factor = 1.00
        conf_boost = 0.00
    else:  # AGG
        stake_factor = 1.15
        conf_boost = -0.02

    # Trend etkisi
    if trend == "UP":
        conf += 0.02
        edge *= 1.05
    elif trend == "DOWN":
        conf -= 0.02
        edge *= 0.95

    # Volatilite etkisi
    if vol > 0.15:
        # Çok oynak dönem → stake ve conf hafif kırp
        conf -= 0.02
        stake_factor *= 0.92
    elif vol < 0.05 and mode == "SAFE":
        # Çok stabil SAFE dönem → ufak boost
        conf += 0.01
        edge *= 1.03

    # Mode bazlı conf boost
    conf += conf_boost

    # Güvenlik: clamp
    conf = max(0.0, min(conf, 0.99))
    edge = max(0.0, edge)
    stake = max(0.1, stake * stake_factor)

    return {
        "engine": "FAZ-8.1",
        "mode": mode,
        "trend": trend,
        "vol": round(vol, 4),
        "conf": round(conf, 3),
        "edge": round(edge, 3),
        "stake": round(stake, 2),
    }


# ================================================================
# 🧠 FAZ-8.2 – LMF SHIELD (Loss Minimization Filters)
#    8.1 çıktısını alıp daha agresif kayıp koruması uygular.
# ================================================================
def _faz82_lmf_shield(calib: dict) -> dict:
    """
    FAZ-8.2:
      - Edge floor / vol kapıları
      - Trend DOWN / UP için farklı baskılama / boost
      - Mode'a göre farklı LMF profilleri
    """
    mode = calib.get("mode", "INIT")
    trend = calib.get("trend", "INIT")
    vol = float(calib.get("vol", 0.0))
    conf = float(calib.get("conf", 0.0))
    edge = float(calib.get("edge", 0.0))
    stake = float(calib.get("stake", 1.0))

    # Mode bazlı LMF profilleri
    profiles = {
        "SAFE": {
            "edge_floor": 0.030,
            "edge_hard_floor": 0.020,
            "vol_soft": 0.08,
            "vol_hard": 0.18,
            "trend_up_factor": 1.05,
            "trend_down_factor": 0.88,
        },
        "BAL": {
            "edge_floor": 0.028,
            "edge_hard_floor": 0.018,
            "vol_soft": 0.10,
            "vol_hard": 0.22,
            "trend_up_factor": 1.04,
            "trend_down_factor": 0.90,
        },
        "AGG": {
            "edge_floor": 0.025,
            "edge_hard_floor": 0.015,
            "vol_soft": 0.12,
            "vol_hard": 0.26,
            "trend_up_factor": 1.03,
            "trend_down_factor": 0.92,
        },
    }

    prof = profiles.get(mode, profiles["BAL"])

    # 1) Edge tabanı – düşük edge'te risk kırpma
    if edge < prof["edge_hard_floor"]:
        # Çok düşük edge → stake yarıya, conf güçlü kırp
        stake *= 0.45
        conf *= 0.80
    elif edge < prof["edge_floor"]:
        # Normal düşük edge → daha hafif kırpma
        stake *= 0.70
        conf *= 0.90

    # 2) Volatilite kapıları
    if vol > prof["vol_hard"]:
        stake *= 0.65
        conf *= 0.90
    elif vol > prof["vol_soft"]:
        stake *= 0.80
        conf *= 0.95

    # 3) Trend smoothing
    if trend == "DOWN":
        stake *= prof["trend_down_factor"]
        conf *= prof["trend_down_factor"]
    elif trend == "UP":
        stake *= prof["trend_up_factor"]
        conf *= prof["trend_up_factor"]
    # FLAT / INIT → dokunma

    # Clamp ve normalize
    conf = max(0.0, min(conf, 0.99))
    edge = max(0.0, edge)
    stake = max(0.1, stake)

    calib["engine"] = "FAZ-8.2"
    calib["conf"] = round(conf, 3)
    calib["edge"] = round(edge, 3)
    calib["stake"] = round(stake, 2)
    return calib


def faz8_calibrate_signal(raw_conf: float,
                          raw_edge: float,
                          base_stake: float = 1.0) -> dict:
    """
    PUBLIC FAZ-8 API
      1) FAZ-8.1 core hesap
      2) FAZ-8.2 LMF SHIELD ile kayıp korumalı refine
    """
    core = _faz81_core_calibration(raw_conf, raw_edge, base_stake)
    # INIT moddaysa 8.2 pek dokunmasın
    if core.get("mode") not in ("SAFE", "BAL", "AGG"):
        core["engine"] = "FAZ-8.2"
        return core
    return _faz82_lmf_shield(core)


# ================================================================
# 🧠 FAZ-8.3 – DYNAMIC CALIBRATION SUITE
#    8.2 çıktısından risk skoru & bucket üretir.
# ================================================================
def faz83_risk_bucket(calib: dict) -> dict:
    """
    Basit risk skoru:
      - conf (0–1) → %60 ağırlık
      - edge (0–0.1 civarı varsayım) → 10x çarpılıp %30 ağırlık
      - mode (AGG ise ekstra risk) → %10 ağırlık
    """
    conf = float(calib.get("conf", 0.0))
    edge = float(calib.get("edge", 0.0))
    mode = calib.get("mode", "INIT")

    edge_norm = min(edge * 10.0, 1.0)  # 0–0.1 → 0–1
    mode_risk = 1.0 if mode == "AGG" else (0.5 if mode == "BAL" else 0.2)

    score = 0.6 * conf + 0.3 * edge_norm + 0.1 * mode_risk

    if score < 0.020:
        bucket = "LOW"
    elif score < 0.050:
        bucket = "MID"
    else:
        bucket = "HIGH"

    return {
        "bucket": bucket,
        "score": round(score, 4),
    }


def faz83_suite(raw_conf: float,
                raw_edge: float,
                base_stake: float = 1.0) -> dict:
    """
    FULL SUITE:
      - 8.2 kalibrasyon
      - 8.3 risk bucket
    """
    calib = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)
    risk = faz83_risk_bucket(calib)
    calib["suite"] = "FAZ-8.3"
    calib["risk_bucket"] = risk["bucket"]
    calib["risk_score"] = risk["score"]
    return calib


# ================================================================
# 🧠 FAZ-7.9 & FAZ-8 KOMUTLARI
# ================================================================
@bot.message_handler(commands=["faz7_status"])
def faz7_status(message):
    mem = load_memory()

    if len(mem["days"]) == 0:
        msg = "📊 <b>FAZ-7.9 Hafıza:</b> Henüz veri yok."
    else:
        df = pd.DataFrame(mem["days"])
        msg = (
            "📊 <b>FAZ-7.9 HAFIZA ÖZETİ</b>\n\n"
            f"SAFE: {mem['safe']}\n"
            f"BAL : {mem['bal']}\n"
            f"AGG : {mem['agg']}\n\n"
            f"7 Günlük Ortalama Confidence: <b>{df['conf'].mean():.3f}</b>\n"
            f"7 Günlük Ortalama Edge: <b>{df['edge'].mean():.3f}</b>"
        )

    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_plan"])
def faz7_plan(message):
    info = faz79_brain()

    msg = (
        "🧠 <b>FAZ-7.9 STRATEJİ BEYNİ</b>\n\n"
        f"Mod: <b>{info['mode']}</b>\n"
        f"🔍 Günlük: conf={info['conf']} edge={info['edge']}\n"
        f"📅 Trend: {info['trend']} (slope {info['slope']})\n"
        f"🌀 Volatilite: {info['vol']}\n"
        f"🛠 Stake Normalize: {info['stake_norm']}\n\n"
        f"SAFE: {'✅' if info['safe'] else '❌'}\n"
        f"BAL: {'✅' if info['bal'] else '❌'}\n"
        f"AGG: {'✅' if info['agg'] else '❌'}\n"
    )

    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_register"])
def faz7_register_cmd(message):
    """
    Kullanım: /faz7_register 0.65 0.04
    """
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(
                message,
                "✅ Kullanım: <code>/faz7_register conf edge</code>\n"
                "Örn: <code>/faz7_register 0.62 0.035</code>"
            )
            return

        conf = float(parts[1])
        edge = float(parts[2])

        register_daily_stats(conf, edge)
        info = faz79_brain()

        bot.reply_to(
            message,
            (
                "✅ Günlük FAZ-7.9 kaydı alındı.\n\n"
                f"conf={conf:.3f}, edge={edge:.3f}\n"
                f"Yeni Mod: <b>{info['mode']}</b>\n"
                f"Trend: {info['trend']} (slope {info['slope']})"
            )
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Kayıt hatası: {e}")


@bot.message_handler(commands=["faz8_status"])
def faz8_status(message):
    """
    FAZ-8.3 kalibrasyon suite örnek davranışı
    """
    # örnek sinyal
    raw_conf = 0.64
    raw_edge = 0.038
    base_stake = 1.0

    suite = faz83_suite(raw_conf, raw_edge, base_stake)

    msg = (
        "🧪 <b>FAZ-8.3 DYNAMIC CALIBRATION SUITE</b>\n\n"
        f"Mode: <b>{suite['mode']}</b>\n"
        f"Trend: {suite['trend']} | Vol: {suite['vol']}\n"
        f"Engine: <b>{suite.get('engine','FAZ-8.2')}</b>\n"
        f"Suite: <b>{suite.get('suite','FAZ-8.3')}</b>\n"
        f"Risk Bucket: <b>{suite['risk_bucket']}</b> (score={suite['risk_score']})\n\n"
        f"Raw  → conf={raw_conf:.3f}, edge={raw_edge:.3f}, stake={base_stake:.2f}\n"
        f"Cal  → conf={suite['conf']:.3f}, edge={suite['edge']:.3f}, stake={suite['stake']:.2f}\n"
    )
    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz8_test"])
def faz8_test(message):
    """
    Kullanım: /faz8_test 0.60 0.03 1.0
      → conf, edge, (opsiyonel) base_stake
    """
    try:
        parts = message.text.split()
        if len(parts) not in (3, 4):
            bot.reply_to(
                message,
                "✅ Kullanım: <code>/faz8_test conf edge [stake]</code>\n"
                "Örn: <code>/faz8_test 0.63 0.035 0.80</code>"
            )
            return

        raw_conf = float(parts[1])
        raw_edge = float(parts[2])
        base_stake = float(parts[3]) if len(parts) == 4 else 1.0

        suite = faz83_suite(raw_conf, raw_edge, base_stake)

        msg = (
            "🧪 <b>FAZ-8.3 TEST</b>\n\n"
            f"Input: conf={raw_conf:.3f}, edge={raw_edge:.3f}, stake={base_stake:.2f}\n\n"
            f"Mode: <b>{suite['mode']}</b> | Trend: {suite['trend']} | Vol: {suite['vol']}\n"
            f"Engine: <b>{suite.get('engine','FAZ-8.2')}</b> | "
            f"Suite: <b>{suite.get('suite','FAZ-8.3')}</b>\n"
            f"Risk Bucket: <b>{suite['risk_bucket']}</b> (score={suite['risk_score']})\n\n"
            f"Output → conf=<b>{suite['conf']:.3f}</b>, "
            f"edge=<b>{suite['edge']:.3f}</b>, "
            f"stake=<b>{suite['stake']:.2f}</b>\n"
        )
        bot.reply_to(message, msg)
    except Exception as e:
        bot.reply_to(message, f"❌ FAZ-8 test hatası: {e}")


# ================================================================
# 🏀 FAZ-6 – KUPON & SİMÜLASYON (FAZ-8.2 ENTEGRE)
# ================================================================
def build_faz6_coupons_text():
    """
    Eski sabit değerler yerine her satır FAZ-8.2 ile kalibre ediliyor.
    Raw değerler screenshot mantığına yakın tutuldu.
    """

    # Kupon 1 — SAFE
    k1_g1 = faz8_calibrate_signal(0.66, 0.045, 0.88)
    k1_g2 = faz8_calibrate_signal(0.64, 0.041, 0.84)

    # Kupon 2 — BALANCED
    k2_g1 = faz8_calibrate_signal(0.63, 0.036, 0.80)
    k2_g2 = faz8_calibrate_signal(0.61, 0.032, 0.76)

    # Kupon 3 — AGGRESSIVE
    k3_g1 = faz8_calibrate_signal(0.60, 0.031, 0.75)

    # Kupon 4 — ULTRA
    k4_g1 = faz8_calibrate_signal(0.59, 0.028, 0.73)

    def fmt(game, calib):
        return (
            f"{game}\n"
            f"  Güven: {calib['conf']:.2f} | Edge: {calib['edge']:.3f} | Stake: {calib['stake']:.2f}\n"
        )

    text = (
        "🔥 <b>FAZ-6 KUPONLARI (FAZ-8.2 Kalibreli)</b>\n\n"

        "🔥 <b>Kupon 1 — SAFE</b>\n" +
        fmt("- EL:EFES@REAL | REAL MADRID -5.5 (spread)", k1_g1) +
        fmt("- EL:FENER@OLY | OLYMPIACOS -3.5 (spread)", k1_g2) +
        f"💰 Toplam Stake: {k1_g1['stake'] + k1_g2['stake']:.2f}\n"
        "— — —\n\n"

        "🔥 <b>Kupon 2 — BALANCED</b>\n" +
        fmt("- NBA:BOS@MIA | UNDER 224.5 (total)", k2_g1) +
        fmt("- NBA:LAL@DEN | DEN -4.5 (spread)", k2_g2) +
        f"💰 Toplam Stake: {k2_g1['stake'] + k2_g2['stake']:.2f}\n"
        "— — —\n\n"

        "🔥 <b>Kupon 3 — AGGRESSIVE</b>\n" +
        fmt("- NBA:CHI@NYK | NYK ML (moneyline)", k3_g1) +
        f"💰 Toplam Stake: {k3_g1['stake']:.2f}\n"
        "— — —\n\n"

        "🔥 <b>Kupon 4 — ULTRA</b>\n" +
        fmt("- NBA:GSW@PHX | OVER 230.5 (total)", k4_g1) +
        f"💰 Toplam Stake: {k4_g1['stake']:.2f}\n"
    )

    return text


@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon(message):
    bot.reply_to(message, build_faz6_coupons_text())


def build_nba_simulation_text():
    """
    Daha sonra gerçek veriyle beslenecek.
    Şimdilik screenshot'taki stabil örneği HTML formatında dönüyoruz.
    FAZ-8.2 → win_prob ve güvenlik şerhi ekler.
    """
    home = "MIA"
    away = "NYK"
    skor = 104
    tempo = 98.8
    pace = 98.8

    # Raw sinyal → FAZ-8.2
    raw_conf = 0.62
    raw_edge = 0.034
    calib = faz8_calibrate_signal(raw_conf, raw_edge, base_stake=1.0)

    win_team = home
    win_prob = calib["conf"]  # 0.0–0.99 arası kalibre güvenini win_prob gibi kullanıyoruz

    risk_label = {
        "SAFE": "🛡 SAFE",
        "BAL": "⚖ BALANCED",
        "AGG": "⚡ AGGRESSIVE",
        "INIT": "⏳ INIT"
    }.get(calib["mode"], calib["mode"])

    return (
        "🏀 <b>NBA Simülasyon Sonuçları (FAZ-8.2)</b>\n\n"
        f"🏠 {home} vs ✈️ {away}\n"
        f"📈 Tahmini Skor: <b>{skor}</b>\n"
        f"⏱ Tempo: <b>{tempo}</b>\n"
        f"🎯 Kazanan: <b>{win_team}</b> ({int(win_prob * 100)}%)\n"
        f"📊 Risk Profili: {risk_label}\n"
        f"🔍 Edge: <b>{calib['edge']:.3f}</b> | Vol: {calib['vol']}\n\n"
        "🧠 <b>Ham Analiz</b>:\n"
        "🔥 <b>NBA – Canlı Maçlar</b>\n"
        f"🏀 {home} (54) – {away} (50)\n"
        f"⏱ Pace Tahmini: <b>{pace}</b>"
    )


@bot.message_handler(commands=["simulate_nba"])
def cmd_simulate_nba(message):
    try:
        bot.reply_to(message, "🏀 Simülasyon başlatılıyor (FAZ-8.2 kalibreli)...")
        text = build_nba_simulation_text()
        bot.reply_to(message, text)
    except Exception as e:
        bot.reply_to(message, f"❌ Simülasyon hatası: {e}")


# Basit FAZ-6 placeholder komutları (şimdilik)
@bot.message_handler(commands=["faz6_test"])
def faz6_test(message):
    bot.reply_to(message, "🧪 FAZ-6 Test modu placeholder.")


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto(message):
    bot.reply_to(message, "🤖 FAZ-6 Auto modu placeholder.")


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk(message):
    bot.reply_to(message, "⚠️ FAZ-6 Risk modu placeholder.")


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge(message):
    bot.reply_to(message, "📐 FAZ-6 Edge modu placeholder.")


@bot.message_handler(commands=["faz6_real"])
def faz6_real(message):
    bot.reply_to(message, "📊 FAZ-6 Real modu placeholder.")


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance(message):
    bot.reply_to(message, "⚖️ FAZ-6 Balance modu placeholder.")


# ================================================================
# 🧰 GENEL KOMUTLAR (/start, /help, /status)
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    text = (
        "🔥 <b>Bot aktif!</b>\n"
        "FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7.9 + FAZ-8.3 bağlı.\n"
        "Komut listesi için <code>/help</code> yaz."
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    text = (
        "📌 <b>Komutlar</b>:\n\n"
        "/start - Botu başlatır\n"
        "/help - Komut listesi\n"
        "/status - Sistem durumu\n\n"
        "/simulate_nba - NBA canlı simülasyon (FAZ-8.2)\n\n"
        "— <b>FAZ-6</b> —\n"
        "/faz6_test - FAZ-6 Test\n"
        "/faz6_auto - FAZ-6 Auto\n"
        "/faz6_risk - FAZ-6 Risk\n"
        "/faz6_edge - FAZ-6 Edge\n"
        "/faz6_real - FAZ-6 Real\n"
        "/faz6_balance - FAZ-6 Balance\n"
        "/faz6_coupon - FAZ-6 Kupon (FAZ-8.2 kalibreli)\n\n"
        "— <b>FAZ-7.9</b> —\n"
        "/faz7_status - FAZ-7.9 hafıza özeti\n"
        "/faz7_plan - FAZ-7.9 strateji planı\n"
        "/faz7_register - Günlük conf & edge kaydı\n\n"
        "— <b>FAZ-8.x</b> —\n"
        "/faz8_status - Kalibrasyon suite özeti (8.3)\n"
        "/faz8_test - Manuel FAZ-8 sinyal testi\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    info = faz79_brain()
    text = (
        "✅ Bot çalışıyor.\n"
        "Mod: <b>Fly.io + Webhook + Flask</b>\n"
        "FAZ-7.9 hafıza motoru: <b>AKTİF</b>\n"
        "FAZ-8.3 kalibrasyon suite: <b>AKTİF</b>\n"
        f"Strateji Modu: <b>{info['mode']}</b> | Trend: {info['trend']} | Vol: {info['vol']}\n"
    )
    bot.reply_to(message, text)


# ================================================================
# 🚀 STARTUP: WEBHOOK AYARLA & FLASK ÇALIŞTIR
# ================================================================
def setup_webhook():
    try:
        log.info("Eski webhook kaldırılıyor...")
        bot.delete_webhook()
    except Exception as e:
        log.warning(f"Eski webhook silinirken hata (önemli değil): {e}")

    if WEBHOOK_URL:
        for attempt in range(1, 3):
            try:
                log.info(f"[FAZ-8.3] Webhook deneme {attempt}: {WEBHOOK_URL}")
                bot.set_webhook(url=WEBHOOK_URL)
                log.info("[FAZ-8.3] Webhook başarıyla set edildi.")
                break
            except Exception as e:
                log.error(f"[FAZ-8.3] Webhook set hatası (deneme {attempt}): {e}")
                time.sleep(1.5)
    else:
        log.warning("WEBHOOK_URL tanımlı değil, webhook set edilmedi!")


if __name__ == "__main__":
    init_memory()
    setup_webhook()
    port = int(os.getenv("PORT", 8080))
    log.info(f"Flask HTTP server 0.0.0.0:{port} üzerinde çalışıyor.")
    app.run(host="0.0.0.0", port=port)
