import os
import json
import time
import logging
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import telebot
import numpy as np
import pandas as pd
from flask import Flask, request
from live_providers.core import get_live_match_global, HoopbrainLiveError

LAST_OCR_TEXT = None
LAST_OCR_META = {}

OCR_CACHE = {}
OCR_CACHE_LOCK = threading.Lock()

OCR_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.getenv("OCR_MAX_WORKERS", "4"))
)

TESSERACT_TIMEOUT = float(os.getenv("OCR_TESSERACT_TIMEOUT", "1.5"))
EASYOCR_TIMEOUT = float(os.getenv("OCR_EASYOCR_TIMEOUT", "2.5"))
VISION_TIMEOUT = float(os.getenv("VISION_TIMEOUT", "5.0"))

GPU_MODE = os.getenv("GPU_MODE", "AUTO").upper()
VISION_MODE = os.getenv("VISION_MODE", "ON").upper() == "ON"

try:
    from PIL import Image
    import pytesseract
except Exception:
    Image = None
    pytesseract = None

try:
    import easyocr
except Exception:
    easyocr = None

try:
    import openai
except Exception:
    openai = None

FAZ7_DIR = os.getenv("FAZ7_DIR", "/data/faz7")
os.makedirs(FAZ7_DIR, exist_ok=True)

MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")
FAZ11_LOG_FILE = os.path.join(FAZ7_DIR, "faz11_history.json")

FAZ13_DIR = os.getenv("FAZ13_DIR", "/data/faz13")
os.makedirs(FAZ13_DIR, exist_ok=True)

ENGINEERING_MODE = os.getenv("ENGINEERING_MODE", "ON").upper() == "ON"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("FAZ-CORE")

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN env değişkeni tanımlı değil!")

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    disable_web_page_preview=True,
)

app = Flask(__name__)

def init_memory():
    if not os.path.exists(MEMORY_FILE):
        base = {"days": [], "safe": 0, "bal": 0, "agg": 0}
        with open(MEMORY_FILE, "w") as f:
            json.dump(base, f, indent=4)
        log.info("[FAZ-7.9] Yeni memory dosyası oluşturuldu.")

def load_memory():
    init_memory()
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        init_memory()
        return load_memory()

def save_memory(data):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        log.error(f"[FAZ-7.9] Kaydetme hatası: {e}")

def register_daily_stats(conf: float, edge: float):
    mem = load_memory()
    mem["days"].append({"ts": int(time.time()), "conf": conf, "edge": edge})
    if len(mem["days"]) > 7:
        mem["days"] = mem["days"][-7:]
    save_memory(mem)
    log.info(f"[FAZ-7.9] Günlük kayıt: conf={conf}, edge={edge}")

def _ema(series: pd.Series, alpha: float = 0.6) -> float:
    if len(series) == 0:
        return 0.0
    v = series.iloc[0]
    for x in series.iloc[1:]:
        v = alpha * x + (1 - alpha) * v
    return float(v)

def _faz92_behavior_curves(df: pd.DataFrame, slope: float, vol: float):
    if df is None or len(df) == 0:
        return {
            "tci": 0.0, "noise_ratio": 0.0,
            "stability": 1.0, "momentum": 0.0,
            "behavior_index": 1.0
        }

    conf = df["conf"].astype(float)
    edge = df["edge"].astype(float)

    last = conf.iloc[-1]
    first = conf.iloc[0]
    change = last - first

    std_conf = float(conf.std() if len(conf) > 1 else 0.0)

    stability = 1 / (1 + std_conf * 25)
    stability = max(0, min(stability, 1))

    momentum = max(-0.1, min(change, 0.1))

    denom = std_conf + 0.02
    tci = max(0, min(abs(slope) / denom, 1))

    noise_ratio = max(0, min(vol / (abs(change) + 0.01), 1.5))

    bi = 1.0
    bi += momentum * 8
    if noise_ratio > 0.6:
        bi -= (noise_ratio - 0.6) * 0.2
    bi -= vol * 0.5
    bi = max(0.8, min(bi, 1.2))

    return {
        "tci": round(tci, 3),
        "noise_ratio": round(noise_ratio, 3),
        "stability": round(stability, 3),
        "momentum": round(momentum, 3),
        "behavior_index": round(bi, 3),
    }

def faz79_brain():
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
            "tci": 0.0,
            "noise_ratio": 0.0,
            "behavior_index": 1.0,
            "stability": 1.0,
            "momentum": 0.0,
            "stake_norm": 1.0,
            "safe": False,
            "bal": False,
            "agg": False,
        }

    df = pd.DataFrame(days)
    df["t"] = range(len(df))

    avg_conf = float(df["conf"].mean())
    avg_edge = float(df["edge"].mean())

    try:
        slope = float(np.polyfit(df["t"], df["conf"], 1)[0])
    except Exception:
        slope = 0.0

    ema_c = _ema(df["conf"])
    trend = (
        "UP" if slope > 0.01 and ema_c >= avg_conf else
        "DOWN" if slope < -0.01 and ema_c <= avg_conf else
        "FLAT"
    )

    base_vol = float(df["conf"].std() if len(df) > 1 else 0.0)
    vol = base_vol * 0.8 + abs(ema_c - avg_conf) * 0.2

    bc = _faz92_behavior_curves(df, slope, vol)

    if avg_conf >= 0.72 and avg_edge >= 0.045:
        mode = "SAFE"
    elif avg_conf >= 0.58 and avg_edge >= 0.030:
        mode = "BAL"
    else:
        mode = "AGG"

    mem["safe"] = int(mode == "SAFE")
    mem["bal"]  = int(mode == "BAL")
    mem["agg"]  = int(mode == "AGG")
    save_memory(mem)

    return {
        "mode": mode,
        "conf": round(avg_conf, 3),
        "edge": round(avg_edge, 3),
        "trend": trend,
        "slope": round(slope, 4),
        "vol": round(vol, 4),
        "tci": bc["tci"],
        "noise_ratio": bc["noise_ratio"],
        "behavior_index": bc["behavior_index"],
        "stability": bc["stability"],
        "momentum": bc["momentum"],
        "stake_norm": 1.0,
        "safe": mode == "SAFE",
        "bal": mode == "BAL",
        "agg": mode == "AGG",
    }

from faz10_engine.faz10_stability import faz10_stability_check

def faz10_hardsync(brain, calib=None):
    try:
        stability = faz10_stability_check(brain) or {}
    except Exception as e:
        log.error(f"[FAZ-10] Stability error: {e}")
        stability = {}
        # ================================================================
# 🏀 FAZ-6 v3 – KUPON & NBA SİMÜLASYON
# (buradaki kupon motoru aynen korunuyor)
# ================================================================
def _faz84_from_raw(profile: str,
                    raw_conf: float,
                    raw_edge: float,
                    base_stake: float) -> dict:
    return faz84_coupon_engine(profile, raw_conf, raw_edge, base_stake)


def _build_fixture_legs():
    legs = []

    # Kupon 1 — SAFE (10 maç)
    k1_games = [
        ("EL:EFES@REAL | REAL MADRID -5.5 (FT spread)", 0.66, 0.045, 0.88),
        ("EL:FENER@OLY | OLYMPIACOS -3.5 (FT spread)", 0.64, 0.041, 0.84),
        ("NBA:BOS@MIA | UNDER 112.5 (1. Yarı total)", 0.65, 0.040, 0.80),
        ("NBA:LAL@DEN | DEN +1.5 (Q1 spread)", 0.64, 0.039, 0.78),
        ("NBA:GSW@PHX | UNDER 58.5 (Q2 total)", 0.63, 0.038, 0.76),
        ("NBA:MIA@MIL | MIA +4.5 (FT spread)", 0.66, 0.044, 0.86),
        ("EL:PARTIZAN@EFES | EFES -2.5 (FT spread)", 0.64, 0.040, 0.82),
        ("EL:BARCA@FENER | UNDER 82.5 (1. Yarı total)", 0.65, 0.039, 0.80),
        ("NBA:NYK@CHI | UNDER 55.5 (Q1 total)", 0.64, 0.038, 0.78),
        ("NBA:DAL@SAC | DAL +2.5 (FT spread)", 0.66, 0.043, 0.88),
    ]
    for g in k1_games:
        legs.append((1, *g))

    # Kupon 2 — BALANCED (10 maç)
    k2_games = [
        ("NBA:BOS@MIA | UNDER 224.5 (FT total)", 0.63, 0.036, 0.80),
        ("NBA:LAL@DEN | DEN -4.5 (FT spread)", 0.61, 0.032, 0.76),
        ("EL:PARTIZAN@EFES | OVER 79.5 (1. Yarı total)", 0.62, 0.034, 0.78),
        ("NBA:NYK@CHI | NYK -1.5 (Q3 spread)", 0.60, 0.031, 0.74),
        ("NBA:DAL@SAC | OVER 56.5 (Q4 total)", 0.60, 0.030, 0.74),
        ("NBA:PHX@GSW | PHX +3.5 (FT spread)", 0.62, 0.035, 0.78),
        ("NBA:MEM@LAC | UNDER 111.5 (2. Yarı total)", 0.61, 0.033, 0.76),
        ("EL:OLY@BARCA | BARCA ML (FT moneyline)", 0.62, 0.034, 0.79),
        ("EL:VALENCIA@FENER | FENER -2.5 (Q3 spread)", 0.60, 0.031, 0.74),
        ("NBA:ATL@MIA | UNDER 57.5 (Q2 total)", 0.61, 0.032, 0.75),
    ]
    for g in k2_games:
        legs.append((2, *g))

    # Kupon 3 — AGGRESSIVE (10 maç)
    k3_games = [
        ("NBA:CHI@NYK | NYK ML (FT moneyline)", 0.60, 0.031, 0.75),
        ("NBA:MIA@MIL | MIA +2.5 (Q1 spread)", 0.59, 0.030, 0.74),
        ("NBA:PHI@BOS | OVER 113.5 (2. Yarı total)", 0.59, 0.029, 0.72),
        ("EL:FENER@REAL | FENERBAHÇE +4.5 (FT spread)", 0.58, 0.029, 0.72),
        ("NBA:LAC@GSW | LAC ML (Q4 moneyline)", 0.58, 0.028, 0.70),
        ("NBA:SAC@DEN | OVER 118.5 (2. Yarı total)", 0.59, 0.029, 0.72),
        ("NBA:OKC@DAL | OKC +3.5 (FT spread)", 0.58, 0.028, 0.70),
        ("EL:EFES@OLY | OVER 82.5 (2. Yarı total)", 0.58, 0.028, 0.70),
        ("EL:PARTIZAN@REAL | PARTIZAN +7.5 (FT spread)", 0.57, 0.027, 0.69),
        ("NBA:BKN@NYK | OVER 56.5 (Q4 total)", 0.57, 0.027, 0.68),
    ]
    for g in k3_games:
        legs.append((3, *g))

    # Kupon 4 — ULTRA (10 maç)
    k4_games = [
        ("NBA:GSW@PHX | OVER 230.5 (FT total)", 0.59, 0.028, 0.73),
        ("NBA:DAL@LAL | DAL -3.5 (FT spread)", 0.58, 0.027, 0.72),
        ("NBA:NYK@BKN | NYK -1.5 (HT spread)", 0.58, 0.027, 0.70),
        ("EL:EFES@BAYERN | OVER 41.5 (Q1 total)", 0.57, 0.026, 0.68),
        ("EL:FENER@OLY | OVER 79.5 (2. Yarı total)", 0.57, 0.026, 0.68),
        ("NBA:MIA@BOS | OVER 60.5 (Q3 total)", 0.58, 0.027, 0.71),
        ("NBA:CHI@ATL | ATL -2.5 (FT spread)", 0.57, 0.026, 0.69),
        ("EL:REAL@BARCA | OVER 165.5 (FT total)", 0.57, 0.026, 0.69),
        ("EL:OLY@PARTIZAN | OLY -3.5 (FT spread)", 0.56, 0.025, 0.67),
        ("NBA:UTA@PHX | PHX -4.5 (FT spread)", 0.56, 0.025, 0.67),
    ]
    for g in k4_games:
        legs.append((4, *g))

    return legs


def build_faz6_coupons_text() -> str:
    legs = _build_fixture_legs()

    def fmt(game: str, calib: dict) -> str:
        return (
            f"{game}\n"
            f"  Güven: {calib['conf']:.2f} | "
            f"Edge: {calib['edge']:.3f} | "
            f"Stake: {calib['stake']:.2f} | "
            f"Risk: {calib['risk']} | Mode: {calib['mode']}\n"
        )

    parts = []
    parts.append(
        "🔥 <b>FAZ-6 v3 KUPONLARI</b> "
        "(40 maç / FAZ-8.4 Kupon Motoru + FAZ-8.5 META hafıza uyumlu)\n\n"
    )

    for coupon_id in (1, 2, 3, 4):
        if coupon_id == 1:
            title = "🔥Kupon 1 — SAFE [SAFE]"
            profile = "SAFE"
        elif coupon_id == 2:
            title = "🔥Kupon 2 — BALANCED [BAL]"
            profile = "BAL"
        elif coupon_id == 3:
            title = "🔥Kupon 3 — AGGRESSIVE [AGG]"
            profile = "AGG"
        else:
            title = "🔥Kupon 4 — ULTRA [ULTRA]"
            profile = "ULTRA"

        parts.append(title + "\n")
        total_stake = 0.0

        for leg in [l for l in legs if l[0] == coupon_id]:
            _, game_desc, conf, edge, stake = leg
            calib = _faz84_from_raw(profile, conf, edge, stake)
            parts.append(fmt(game_desc, calib))
            total_stake += calib["stake"]

        parts.append(f"💰 Toplam Stake: {total_stake:.2f}\n")
        parts.append("— — —\n\n")

    return "".join(parts)


def build_faz6_meta_coupon_text() -> str:
    profile = faz85_meta_profile_selector()

    legs_def = [
        ("NBA:MIA@NYK | MIA -2.5 (FT spread)", 0.64, 0.039, 0.85),
        ("EL:FENER@EFES | OVER 164.5 (FT total)", 0.62, 0.034, 0.80),
        ("NBA:MIA@NYK | OVER 52.5 (Q1 total)", 0.63, 0.036, 0.78),
        ("NBA:MIA@NYK | NYK +1.5 (Q3 spread)", 0.61, 0.032, 0.76),
    ]

    def fmt(game: str, calib: dict) -> str:
        return (
            f"{game}\n"
            f"  Güven: {calib['conf']:.2f} | "
            f"Edge: {calib['edge']:.3f} | "
            f"Stake: {calib['stake']:.2f} | "
            f"Risk: {calib['risk']} | Mode: {calib['mode']}\n"
        )

    legs_text = []
    total_stake = 0.0
    for game, conf, edge, stake in legs_def:
        calib = _faz84_from_raw(profile, conf, edge, stake)
        legs_text.append(fmt(game, calib))
        total_stake += calib["stake"]

    text = (
        "🤖 <b>FAZ-6 META KUPON (FAZ-8.5 Profile Selector v3)</b>\n\n"
        f"Seçilen Profil: <b>{profile}</b>\n\n" +
        "".join(legs_text) +
        f"💰 Toplam Stake: {total_stake:.2f}\n"
    )
    return text


def _send_long_text(message, text: str, max_len: int = 3800):
    chat_id = message.chat.id
    if len(text) <= max_len:
        bot.reply_to(message, text)
        return

    start = 0
    first = True
    while start < len(text):
        chunk = text[start:start + max_len]
        if first:
            bot.reply_to(message, chunk)
            first = False
        else:
            bot.send_message(chat_id, chunk)
        start += max_len


def build_nba_simulation_text():
    """
    NBA simülasyon çıktı örneği
    """
    home = "MIA"
    away = "NYK"
    skor = 104
    tempo = 98.8
    pace = 98.8

    raw_conf = 0.62
    raw_edge = 0.034

    profile = faz85_meta_profile_selector()
    c = faz84_coupon_engine(profile, raw_conf, raw_edge, base_stake=1.0)

    _auto_faz_pipeline(
        pred_conf=c.get("conf", 0.60),
        pred_edge=c.get("edge", 0.03),
        pred_bucket=c.get("bucket", "MID"),
        real_result=None,
    )

    win_team = home
    win_prob = c["conf"]

    risk_label = {
        "SAFE": "🛡 SAFE",
        "BAL": "⚖ BALANCED",
        "AGG": "⚡ AGGRESSIVE",
        "INIT": "⏳ INIT",
    }.get(c["mode"], c["mode"])

    return (
        "🏀 <b>NBA Simülasyon Sonuçları (FAZ-8.4 + FAZ-8.5 META)</b>\n\n"
        f"🏠 {home} vs ✈️ {away}\n"
        f"📈 Tahmini Skor: <b>{skor}</b>\n"
        f"⏱ Tempo: <b>{tempo}</b>\n"
        f"🎯 Kazanan: <b>{win_team}</b> ({int(win_prob * 100)}%)\n"
        f"📊 Risk Profili: {risk_label} | Bucket: <b>{c['bucket']}</b>\n"
        f"🔍 Edge: <b>{c['edge']:.3f}</b>\n"
        f"💰 Stake: <b>{c['stake']:.2f}</b>\n\n"
        f"🔧 Profil (FAZ-8.5): <b>{profile}</b>\n\n"
        "🧠 <b>Ham Analiz</b>:\n"
        "🔥 <b>NBA – Canlı Maçlar</b>\n"
        f"🏀 {home} (54) – {away} (50)\n"
        f"⏱ Pace Tahmini: <b>{pace}</b>"
    )


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
            "📊 <b>FAZ-7.9 v2.0 HAFIZA ÖZETİ</b>\n\n"
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
        "🧠 <b>FAZ-7.9 v2.0 STRATEJİ BEYNİ + FAZ-9.1 + FAZ-9.2</b>\n\n"
        f"Mod: <b>{info['mode']}</b>\n"
        f"Günlük: conf={info['conf']} edge={info['edge']}\n"
        f"Trend: {info['trend']} (slope {info['slope']})\n"
        f"Volatilite: {info['vol']}\n"
        f"Trend Certainty (TCI): {info['tci']}\n"
        f"Noise Ratio: {info['noise_ratio']}\n"
        f"Behavior Index: {info['behavior_index']}\n"
        f"Stake Normalize: {info['stake_norm']}\n\n"
        f"SAFE: {'✅' if info['safe'] else '❌'}\n"
        f"BAL: {'✅' if info['bal'] else '❌'}\n"
        f"AGG: {'✅' if info['agg'] else '❌'}\n"
    )

    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz7_register"])
def faz7_register_cmd(message):
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(
                message,
                "✅ Kullanım: <code>/faz7_register conf edge</code>\n"
                "Örn: <code>/faz7_register 0.62 0.035</code>",
            )
            return

        conf = float(parts[1])
        edge = float(parts[2])

        register_daily_stats(conf, edge)
        info = faz79_brain()

        bot.reply_to(
            message,
            (
                "✅ Günlük FAZ-7.9 v2.0 kaydı alındı.\n\n"
                f"conf={conf:.3f}, edge={edge:.3f}\n"
                f"Yeni Mod: <b>{info['mode']}</b>\n"
                f"Trend: {info['trend']} (slope {info['slope']})"
            ),
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Kayıt hatası: {e}")


@bot.message_handler(commands=["faz8_status"])
def faz8_status(message):
    raw_conf = 0.64
    raw_edge = 0.038
    base_stake = 1.0

    calib = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)

    msg = (
        "🧪 <b>FAZ-8.x STATUS</b>\n\n"
        f"Mode: <b>{calib['mode']}</b>\n"
        f"Trend: {calib['trend']} | Vol: {calib['vol']}\n"
        f"Engine: <b>{calib.get('engine','FAZ-8.3')}</b>\n"
        f"Bucket: <b>{calib['bucket']}</b> | Score: {calib['score']}\n"
        f"Behavior Index: <b>{calib.get('behavior_index', 1.0):.3f}</b>\n\n"
        f"Cal → conf=<b>{calib['conf']:.3f}</b>, "
        f"edge=<b>{calib['edge']:.3f}</b>, "
        f"stake=<b>{calib['stake']:.2f}</b>\n"
    )
    bot.reply_to(message, msg)


@bot.message_handler(commands=["faz8_test"])
def faz8_test(message):
    try:
        parts = message.text.split()
        if len(parts) not in (3, 4):
            bot.reply_to(
                message,
                "✅ Kullanım: <code>/faz8_test conf edge [stake]</code>\n"
                "Örn: <code>/faz8_test 0.63 0.035 0.80</code>",
            )
            return

        raw_conf = float(parts[1])
        raw_edge = float(parts[2])
        base_stake = float(parts[3]) if len(parts) == 4 else 1.0

        calib = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)

        msg = (
            "🧪 <b>FAZ-8.3 FULL TEST</b>\n\n"
            f"Input: conf={raw_conf:.3f}, edge={raw_edge:.3f}, stake={base_stake:.2f}\n\n"
            f"Mode: <b>{calib['mode']}</b> | Trend: {calib['trend']} | Vol: {calib['vol']}\n"
            f"Bucket: <b>{calib['bucket']}</b> | Score: {calib['score']}\n"
            f"Behavior Index: <b>{calib.get('behavior_index', 1.0):.3f}</b>\n\n"
            f"Output → conf=<b>{calib['conf']:.3f}</b>, "
            f"edge=<b>{calib['edge']:.3f}</b>, "
            f"stake=<b>{calib['stake']:.2f}</b>\n"
        )
        bot.reply_to(message, msg)
    except Exception as e:
        bot.reply_to(message, f"❌ FAZ-8 test hatası: {e}")


# ================================================================
# FAZ-6 KOMUTLARI
# ================================================================
@bot.message_handler(commands=["faz6_coupon", "kupon"])
def faz6_coupon(message):
    try:
        text = build_faz6_coupons_text()
        _send_long_text(message, text)
    except Exception as e:
        log.error(f"FAZ-6 kupon oluşturma hatası: {e}", exc_info=True)
        bot.reply_to(message, "❌ Kupon üretiminde hata oluştu.")


@bot.message_handler(commands=["faz6_meta", "kupon_meta"])
def faz6_meta(message):
    try:
        text = build_faz6_meta_coupon_text()
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"FAZ-6 META kupon hatası: {e}", exc_info=True)
        bot.reply_to(message, "❌ META kupon üretiminde hata oluştu.")


@bot.message_handler(commands=["simulate_nba"])
def cmd_simulate_nba(message):
    try:
        bot.reply_to(
            message,
            "🏀 Simülasyon başlatılıyor (FAZ-8.4 + FAZ-8.5 META + FAZ-9.x)...",
        )
        text = build_nba_simulation_text()
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"Simülasyon hatası: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Simülasyon hatası: {e}")


# Basit FAZ-6 placeholder komutları
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
    bot.reply_to(message, "⚖ FAZ-6 Balance modu placeholder.")


# ================================================================
# 🧰 GENEL KOMUTLAR (/start, /help, /status, /faz10, /faz11, /faz12)
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    text = (
        "🔥 <b>Bot aktif!</b>\n"
        "FAZ-4 + FAZ-5 + FAZ-6 v3 + FAZ-7.9 v2.0 + "
        "FAZ-8.2 + FAZ-8.3 + FAZ-8.4 + FAZ-8.5 META + FAZ-9.x + FAZ-10 HardSync + "
        "FAZ-11 + FAZ-12 + Ultra OCR Engine v3 (FAZ-13 C MODE FULL POWER).\n"
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
        "/simulate_nba - NBA canlı simülasyon (FAZ-8.4 + FAZ-8.5 + FAZ-9.x)\n\n"
        "— <b>FAZ-6 v3</b> —\n"
        "/faz6_test - FAZ-6 Test\n"
        "/faz6_auto - FAZ-6 Auto\n"
        "/faz6_risk - FAZ-6 Risk\n"
        "/faz6_edge - FAZ-6 Edge\n"
        "/faz6_real - FAZ-6 Real\n"
        "/faz6_balance - FAZ-6 Balance\n"
        "/faz6_coupon - FAZ-6 v3 Kupon (40 maç / FAZ-8.4 kupon motoru)\n"
        "/faz6_meta - FAZ-6 META kupon (FAZ-8.5 profile selector)\n\n"
        "— <b>FAZ-7.9</b> —\n"
        "/faz7_status - FAZ-7.9 hafıza özeti\n"
        "/faz7_plan - FAZ-7.9 + FAZ-9.x strateji planı\n"
        "/faz7_register - Günlük conf & edge kaydı\n\n"
        "— <b>FAZ-8.x</b> —\n"
        "/faz8_status - FAZ-8.x status\n"
        "/faz8_test - Manuel FAZ-8.x sinyal testi\n\n"
        "— <b>FAZ-10</b> —\n"
        "/faz10 - FAZ-10 Stability + HardSync Report\n\n"
        "— <b>FAZ-11 / FAZ-12</b> —\n"
        "/faz11 - Günlük feedback kayıt\n"
        "/faz12 - Auto profile ayarı\n\n"
        "— <b>FAZ-13 (C MODE)</b> —\n"
        "/mac - Manual maç input\n"
        "/mac_img - Görsel + OCR Extreme Mode\n"
        "/ocr_debug - Son OCR debug bilgisi\n"
        "/live - Hibrit canlı maç modu (ID veya takım adı)\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    info = faz79_brain()
    text = (
        "✅ Bot çalışıyor.\n"
        "Mod: <b>Fly.io + Webhook + Flask</b>\n"
        f"ENGINEERING_MODE: <b>{'ON' if ENGINEERING_MODE else 'OFF'}</b>\n"
        "FAZ-7.9 v2.0 hafıza motoru: <b>AKTİF</b>\n"
        "FAZ-9.1/9.2 behavior motoru: <b>AKTİF</b>\n"
        "FAZ-8.2/8.3/8.4/8.5: <b>AKTİF</b>\n"
        "Ultra OCR Engine v3 (A+B+C Hybrid): <b>AKTİF</b>\n"
        "OCR Cache Layer: <b>AKTİF</b>\n"
        "Fast-Fail Timeout Protection: <b>AKTİF</b>\n"
        f"Strateji Modu: <b>{info['mode']}</b> | "
        f"Trend: {info['trend']} | Vol: {info['vol']}\n"
        f"TCI: {info['tci']} | Noise: {info['noise_ratio']} | "
        f"BehaviorIndex: {info['behavior_index']}\n"
        f"Hafıza dosyası: <code>{MEMORY_FILE}</code>\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["faz11"])
def cmd_faz11(message):
    try:
        parts = message.text.split()[1:]
        if not parts:
            bot.reply_to(message, "⚠️ Kullanım: /faz11 1 0 1 1")
            return

        real_results = []
        for p in parts:
            if p in ["1", "true", "True"]:
                real_results.append(True)
            elif p in ["0", "false", "False"]:
                real_results.append(False)

        predicted = [
            {"conf": 0.60, "edge": 0.03, "bucket": "MID"} for _ in real_results
        ]

        result = _faz11_register_feedback(real_results, predicted)

        text = (
            "🔥 <b>FAZ-11 Günlük Feedback Kaydedildi</b>\n"
            f"Toplam: <b>{result.get('total')}</b>\n"
            f"Doğru: <b>{result.get('correct')}</b>\n"
            f"Accuracy: <b>{result.get('daily_accuracy')}</b>\n"
            f"Avg Conf: <b>{result.get('avg_conf')}</b>\n"
            f"Drift: <b>{result.get('model_drift')}</b>\n"
        )

        bot.reply_to(message, text, parse_mode="HTML")

    except Exception as e:
        log.error(f"[FAZ-11 CMD Error] {e}", exc_info=True)
        bot.reply_to(message, f"❌ FAZ-11 hata: {e}")


@bot.message_handler(commands=["faz12"])
def cmd_faz12(message):
    try:
        brain = faz79_brain()
        f10 = faz10_stability_check(brain)

        f11 = faz11_last_summary()
        if not f11["last"]:
            bot.reply_to(message, "⚠️ FAZ-11 geçmişi bulunamadı.")
            return
        f11_last = f11["last"]

        decision = _faz12_autoadjust(f10, f11_last)

        txt = (
            "🔧 <b>FAZ-12 Auto Profile</b>\n"
            f"Önceki Mod: <b>{decision.get('prev_mode')}</b>\n"
            f"Yeni Mod: <b>{decision.get('new_mode')}</b>\n"
            f"Değişti mi?: <b>{decision.get('changed')}</b>\n"
            f"Neden: <b>{decision.get('reason')}</b>\n"
        )

        bot.reply_to(message, txt, parse_mode="HTML")

    except Exception as e:
        log.error(f"[FAZ-12 CMD Error] {e}", exc_info=True)
        bot.reply_to(message, f"❌ FAZ-12 hata: {e}")


@bot.message_handler(commands=["faz10"])
def cmd_faz10(message):
    try:
        brain = faz79_brain()
        hs = faz10_hardsync(brain)
        result = hs.get("stability", {}) or {}

        reply = (
            "🔥 <b>FAZ-10 Stability Report + HardSync</b>\n\n"
            f"Stability Score: <b>{result.get('stability_score', '-')}</b>\n"
            f"Regime: <b>{result.get('regime', '-')}</b>\n"
            f"Suggested Mode: <b>{result.get('suggested_mode', '-')}</b>\n"
            f"Anomaly Level: <b>{result.get('anomaly_level', '-')}</b>\n"
            f"Trend Slope: <b>{result.get('trend_slope', '-')}</b>\n\n"
            f"HardSync Mode: <b>{hs.get('mode', brain.get('mode', 'INIT'))}</b>\n"
            f"HardSync Bucket: <b>{hs.get('bucket', 'MID')}</b>\n"
            f"HardSync Reason: <b>{hs.get('lock_reason', 'NO_LOCK')}</b>\n"
            f"Engineering Mode: <b>{'ON' if ENGINEERING_MODE else 'OFF'}</b>\n"
        )

        extra = (
            result.get("notes")
            or result.get("explanation")
            or hs.get("stability", {}).get("notes")
        )
        if extra:
            reply += f"\n📝 Notlar: {extra}"

        bot.reply_to(message, reply)
    except Exception as e:
        log.error(f"[FAZ-10] Stability/HardSync hatası: {e}", exc_info=True)
        bot.reply_to(message, f"❌ FAZ-10 stability / HardSync hatası: {e}")


# ================================================================
# 🔥 GLOBAL LIVE (NBA / EL / TR / EU / ID MODE) – NEW PROVIDER
# ================================================================
@bot.message_handler(commands=["live"])
def cmd_live_global(message):
    """
    Hibrit kullanım:

    1) Takım bazlı:
        /live NBA LAL BOS
        /live EL FENER EFES
        /live TR FENER EFES

    2) ID bazlı:
        /live ID 4406870
        /live 4406870
    """
    try:
        parts = message.text.split()

        # /live tek başına
        if len(parts) == 1:
            bot.reply_to(
                message,
                "🔥 Kullanım:\n"
                "<code>/live LIG HOME AWAY</code>  →  /live NBA LAL BOS\n"
                "<code>/live ID 4406870</code>    →  Maç ID ile\n"
                "<code>/live 4406870</code>       →  Kısa ID modu\n",
            )
            return

        league = None
        home = None
        away = None
        match_id = None

        # /live 123456  → direkt ID
        if len(parts) == 2 and parts[1].isdigit():
            match_id = parts[1]

        # /live ID 123456
        elif len(parts) == 3 and parts[1].upper() == "ID":
            match_id = parts[2]

        # /live NBA LAL BOS
        elif len(parts) >= 4:
            league = parts[1].upper()
            home = parts[2].upper()
            away = parts[3].upper()

        else:
            bot.reply_to(
                message,
                "⚠️ Geçersiz /live formatı.\n"
                "Örnekler:\n"
                "<code>/live NBA LAL BOS</code>\n"
                "<code>/live EL FENER EFES</code>\n"
                "<code>/live ID 4406870</code>\n"
                "<code>/live 4406870</code>",
            )
            return

        live = get_live_match_global(
            league=league,
            home=home,
            away=away,
            match_id=match_id,
        )

        text = (
            "🏀 <b>HOOPBRAIN GLOBAL LIVE (ULTRA)</b>\n\n"
            f"Lig : <b>{live.get('league', league or '-')}</b>\n"
            f"Maç : <b>{live.get('home_name', home or '?')}</b> "
            f"vs <b>{live.get('away_name', away or '?')}</b>\n"
            f"Skor : <b>{live.get('home_score', 0)} - {live.get('away_score', 0)}</b>\n"
            f"Periyot : <b>{live.get('period_label', '-')}</b>\n"
            f"Kalan Süre : <b>{live.get('clock', '-')}</b>\n"
            f"Durum : <b>{live.get('status', '-')}</b>\n"
            f"Pace Tahmini : <b>{live.get('pace', 0.0):.1f}</b>\n"
            f"WinProb ({live.get('win_side_label', 'HOME')}): "
            f"<b>{int(float(live.get('win_prob', 0.5)) * 100)}%</b>\n"
            f"Veri Kaynağı : <b>{live.get('provider', 'UNKNOWN')}</b>\n"
        )

        bot.reply_to(message, text)

    except HoopbrainLiveError as e:
        bot.reply_to(
            message,
            f"❌ HoopBrain Live hata (core): {e}",
        )

    except Exception as e:
        logging.getLogger(__name__).error(
            "[LIVE CMD] Genel hata: %s", e, exc_info=True
        )
        bot.reply_to(
            message,
            "❌ Sistem içi bir hata oluştu. Loglara işaretlendi.\n"
            f"Detay: {e}",
        )


# ================================================================
# 🧠 FAZ-13 MANUAL KOMUT
# ================================================================
@bot.message_handler(commands=["mac"])
def cmd_manual_match(message):
    """
    Örnek kullanım:
        /mac BOS ORL 220.5 U 1.46
    """
    try:
        fusion_input = normalize_manual_text(message.text, default_league="NBA")
        text = run_faz13_auto_pipeline(fusion_input)
        bot.reply_to(message, text)
    except Exception as e:
        log.error(f"[FAZ-13 MANUAL] Hata: {e}", exc_info=True)
        bot.reply_to(
            message,
            "❌ FAZ-13 manual input işlenemedi.\n"
            "Format örneği: /mac BOS ORL 220.5 U 1.46",
    )
        # ================================================================
# 🔥 ULTRA OCR ENGINE v3 (A+B+C Hybrid) + CACHE + TIMEOUT
# ================================================================

def _hash_image_bytes(img_bytes: bytes) -> str:
    return hashlib.sha256(img_bytes).hexdigest()


def _ocr_tesseract(image: Image.Image) -> str:
    if pytesseract is None:
        return ""
    try:
        return pytesseract.image_to_string(image, timeout=TESSERACT_TIMEOUT)
    except Exception:
        return ""


def _ocr_easyocr(image_path: str) -> str:
    if easyocr is None:
        return ""
    try:
        reader = easyocr.Reader(["en"], gpu=(GPU_MODE != "OFF"))
        out = reader.readtext(image_path, detail=0)
        return "\n".join(out)
    except Exception:
        return ""


def _ocr_vision_api(img_bytes: bytes) -> str:
    if openai is None or VISION_MODE is False:
        return ""
    try:
        resp = openai.images.parse_image(
            image=img_bytes,
            timeout=VISION_TIMEOUT,
        )
        return resp.get("text", "")
    except Exception:
        return ""


def hybrid_ocr_extract(img_bytes: bytes) -> dict:
    """
    Ultra OCR Engine v3:
      • A = Tesseract
      • B = EasyOCR
      • C = OpenAI Vision (opsiyonel)
      • Timeout + Fail-Fast + Cache
    """
    img_hash = _hash_image_bytes(img_bytes)

    # ---- CACHE CHECK ----
    with OCR_CACHE_LOCK:
        if img_hash in OCR_CACHE:
            return OCR_CACHE[img_hash]

    # Byte → PIL Image
    try:
        image = Image.open(io.BytesIO(img_bytes))
    except Exception:
        return {"text": "", "engine": "decode_failed"}

    text_results = []

    futures = {}

    # OCR A (Tesseract)
    futures["tess"] = OCR_EXECUTOR.submit(_ocr_tesseract, image)

    # OCR B (EasyOCR)
    temp_path = f"/tmp/eocr_{img_hash}.png"
    try:
        image.save(temp_path)
        futures["easy"] = OCR_EXECUTOR.submit(_ocr_easyocr, temp_path)
    except Exception:
        futures["easy"] = None

    # OCR C (Vision)
    if VISION_MODE:
        futures["vision"] = OCR_EXECUTOR.submit(_ocr_vision_api, img_bytes)
    else:
        futures["vision"] = None

    best = ""
    meta = {}

    for key, job in futures.items():
        if job is None:
            continue
        try:
            result = job.result(timeout=VISION_TIMEOUT)
        except Exception:
            result = ""
        if result and len(result.strip()) > len(best.strip()):
            best = result
            meta["best_engine"] = key

    meta["length"] = len(best)
    meta["hash"] = img_hash

    # Cache yaz
    with OCR_CACHE_LOCK:
        OCR_CACHE[img_hash] = {"text": best, "meta": meta}

    global LAST_OCR_TEXT, LAST_OCR_META
    LAST_OCR_TEXT = best
    LAST_OCR_META = meta

    return {"text": best, "meta": meta}


# ================================================================
# 🧩 /mac_img — Çoklu Görsel → OCR → FAZ-13 Pipeline
# ================================================================
@bot.message_handler(commands=["mac_img"])
def cmd_mac_img(message):
    """
    Çoklu görsel yüklenebilir.
    1–20 arası image → OCR → normalize_visual_meta → FAZ-13 pipeline
    """
    if not message.photo:
        bot.reply_to(message, "⚠️ Görsel bulunamadı. Bir maç görseli gönder.")
        return

    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        img_bytes = bot.download_file(file_info.file_path)

        ocr_out = hybrid_ocr_extract(img_bytes)

        text = ocr_out.get("text", "")
        meta = ocr_out.get("meta", {})

        # FAZ-13 visual normalizer
        fusion = normalize_visual_meta(text)

        # Final FAZ-13 output
        result = run_faz13_auto_pipeline(fusion)

        reply = (
            "🧠 <b>FAZ-13 VISUAL MODE — OCR v3</b>\n\n"
            f"📄 OCR Engine: <b>{meta.get('best_engine')}</b>\n"
            f"🔢 Text Length: {meta.get('length')}\n"
            f"🔗 Hash: {meta.get('hash')}\n\n"
            f"📤 <b>Normalizasyon</b>:\n<code>{fusion}</code>\n\n"
            f"🎯 <b>FAZ-13 Sonuç</b>:\n{result}"
        )

        bot.reply_to(message, reply)

    except Exception as e:
        log.error(f"[mac_img OCR] HATA: {e}", exc_info=True)
        bot.reply_to(message, f"❌ OCR/FAZ-13 hatası: {e}")


# ================================================================
# 🧩 /ocr_debug — Son OCR çıktısı
# ================================================================
@bot.message_handler(commands=["ocr_debug"])
def cmd_ocr_debug(message):
    global LAST_OCR_TEXT, LAST_OCR_META

    if not LAST_OCR_TEXT:
        bot.reply_to(message, "⚠️ Henüz OCR çalışmadı.")
        return

    debug = (
        "🧪 <b>OCR DEBUG</b>\n\n"
        f"<b>Engine:</b> {LAST_OCR_META.get('best_engine')}\n"
        f"<b>Length:</b> {LAST_OCR_META.get('length')}\n"
        f"<b>Hash:</b> {LAST_OCR_META.get('hash')}\n\n"
        f"<b>Text:</b>\n<code>{LAST_OCR_TEXT}</code>"
    )
    bot.reply_to(message, debug)


# ================================================================
# 🌐 FLASK ROUTE'LER — HEALTH + TELEGRAM WEBHOOK
# ================================================================
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        json_update = request.get_json(force=False, silent=True)
        if json_update is None:
            raw = request.data.decode("utf-8", errors="ignore")
            log.warning(f"Webhook parse hatası — RAW: {raw[:400]}")
            return "OK", 200

        update = telebot.types.Update.de_json(json_update)
        bot.process_new_updates([update])

    except Exception as e:
        log.error(f"Webhook HATA: {e}", exc_info=True)
    return "OK", 200


def setup_webhook():
    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL tanımlı değil → webhook set edilmedi.")
        return

    try:
        bot.remove_webhook()
        time.sleep(1)
        url = WEBHOOK_URL.rstrip("/") + "/webhook"
        bot.set_webhook(url)
        log.info(f"Telegram webhook set edildi → {url}")
    except Exception as e:
        log.error(f"Webhook SET HATA: {e}", exc_info=True)


setup_webhook()


# ================================================================
# 🔚 FALLBACK HANDLER
# ================================================================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def fallback(message):
    if message.text.startswith("/"):
        bot.reply_to(
            message,
            "❓ Bilinmeyen komut.\nTüm komutlar için: /help",
        )
        return

    bot.reply_to(
        message,
        "💬 Mesaj alındı.\nKomut listesi: /help",
    )


# ================================================================
# 🏁 MAIN GUARD (Fly.io için gunicorn, local için run)
# ================================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    log.info(f"Local dev aktif → Flask port={port}")
    app.run(host="0.0.0.0", port=port)
