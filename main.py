import os
import json
import time
import math
import logging
import traceback

import numpy as np
import pandas as pd
import requests
from flask import Flask, request

# =======================
# LOGGING
# =======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("ZeynalCoreAI")

# =======================
# BASE CONFIG
# =======================
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # örn: https://zeynal-bot-core.fly.dev

FAZ7_DIR = "/data/faz7"
FAZ6_DIR = "/data/faz6"

FAZ7_MEMORY_FILE = os.path.join(FAZ7_DIR, "faz7_memory.json")
FAZ6_MEMORY_FILE = os.path.join(FAZ6_DIR, "faz6_memory.json")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN env değişkeni tanımlı değil!")

# =======================
# TELEGRAM HELPERS
# =======================
TG_API = f"https://api.telegram.org/bot{TOKEN}"


def tg_send(chat_id: int, text: str):
    try:
        url = f"{TG_API}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        if resp.status_code != 200:
            log.warning(f"Telegram sendMessage status={resp.status_code}, resp={resp.text}")
    except Exception:
        log.error("Telegram gönderim hatası:\n" + traceback.format_exc())


def tg_send_long(chat_id: int, text: str, chunk_size: int = 3500):
    lines = text.split("\n")
    buf = ""
    for line in lines:
        if len(buf) + len(line) + 1 > chunk_size:
            if buf.strip():
                tg_send(chat_id, buf)
            buf = line + "\n"
        else:
            buf += line + "\n"
    if buf.strip():
        tg_send(chat_id, buf)


# =======================
# FLASK SERVER
# =======================
app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return "Zeynal Core AI — RUNNING", 200


@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if data is None:
            log.warning("Boş / geçersiz JSON update alındı.")
            return "OK", 200
        handle_update(data)
    except Exception:
        log.error("Webhook parse hatası:\n" + traceback.format_exc())
    return "OK", 200


# ================================================================
#  FAZ-7.9 v2.0 MEMORY ENGINE
# ================================================================
def ensure_dir(path: str):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        log.error("Klasör oluşturma hatası:\n" + traceback.format_exc())


def init_faz7_memory():
    ensure_dir(FAZ7_DIR)
    if not os.path.exists(FAZ7_MEMORY_FILE):
        data = {
            "days": [],  # {ts, conf, edge}
            "safe": 0,
            "bal": 0,
            "agg": 0,
        }
        try:
            with open(FAZ7_MEMORY_FILE, "w") as f:
                json.dump(data, f, indent=4)
            log.info(f"[FAZ-7.9] Yeni hafıza dosyası oluşturuldu: {FAZ7_MEMORY_FILE}")
        except Exception:
            log.error("FAZ-7.9 memory init hatası:\n" + traceback.format_exc())


def load_faz7_memory():
    init_faz7_memory()
    try:
        with open(FAZ7_MEMORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        log.error("FAZ-7.9 memory yükleme hatası, resetleniyor:\n" + traceback.format_exc())
        data = {
            "days": [],
            "safe": 0,
            "bal": 0,
            "agg": 0,
        }
        with open(FAZ7_MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=4)
        return data


def save_faz7_memory(data: dict):
    try:
        with open(FAZ7_MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        log.error("FAZ-7.9 memory kaydetme hatası:\n" + traceback.format_exc())


def register_daily_stats(conf: float, edge: float):
    mem = load_faz7_memory()
    today = {
        "ts": int(time.time()),
        "conf": float(conf),
        "edge": float(edge),
    }
    mem["days"].append(today)
    if len(mem["days"]) > 7:
        mem["days"] = mem["days"][-7:]
    save_faz7_memory(mem)
    log.info(f"[FAZ-7.9] Günlük kayıt eklendi: conf={conf:.3f}, edge={edge:.3f}")


def _ema(series: pd.Series, alpha: float = 0.6) -> float:
    if len(series) == 0:
        return 0.0
    ema_val = series.iloc[0]
    for x in series.iloc[1:]:
        ema_val = alpha * x + (1 - alpha) * ema_val
    return float(ema_val)


def faz79_brain():
    mem = load_faz7_memory()
    days = mem.get("days", [])

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

    try:
        slope = float(np.polyfit(df["t"], df["conf"], 1)[0])
    except Exception as e:
        log.warning(f"FAZ-7.9 v2.0 slope hesaplanırken hata (SVD fallback): {e}")
        slope = 0.0

    ema_conf = _ema(df["conf"])
    if slope > 0.01 and ema_conf >= avg_conf:
        trend = "UP"
    elif slope < -0.01 and ema_conf <= avg_conf:
        trend = "DOWN"
    else:
        trend = "FLAT"

    base_vol = float(df["conf"].std() if len(df) > 1 else 0.0)
    ema_diff = abs(ema_conf - avg_conf)
    vol = float(base_vol * 0.8 + ema_diff * 0.2)

    if avg_conf >= 0.72 and avg_edge >= 0.045:
        mode = "SAFE"
    elif avg_conf >= 0.58 and avg_edge >= 0.030:
        mode = "BAL"
    else:
        mode = "AGG"

    mem["safe"] = int(mode == "SAFE")
    mem["bal"] = int(mode == "BAL")
    mem["agg"] = int(mode == "AGG")
    save_faz7_memory(mem)

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
#  FAZ-8.1 / 8.2 / 8.3 / 8.4 / 8.5
# ================================================================
def _faz81_core_calibration(raw_conf: float,
                            raw_edge: float,
                            base_stake: float = 1.0) -> dict:
    brain = faz79_brain()

    mode = brain["mode"]
    trend = brain["trend"]
    vol = brain["vol"]

    conf = float(raw_conf)
    edge = float(raw_edge)
    stake = float(base_stake)

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

    if mode == "SAFE":
        stake_factor = 0.88
        conf_boost = 0.035
    elif mode == "BAL":
        stake_factor = 1.00
        conf_boost = 0.00
    else:
        stake_factor = 1.18
        conf_boost = -0.025

    if trend == "UP":
        conf += 0.02
        edge *= 1.06
    elif trend == "DOWN":
        conf -= 0.02
        edge *= 0.94

    if vol > 0.18:
        conf -= 0.02
        stake_factor *= 0.90
    elif vol < 0.05 and mode == "SAFE":
        conf += 0.01
        edge *= 1.03

    conf += conf_boost

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


def _faz82_lmf_shield(calib: dict) -> dict:
    mode = calib.get("mode", "INIT")
    trend = calib.get("trend", "INIT")
    vol = float(calib.get("vol", 0.0))
    conf = float(calib.get("conf", 0.0))
    edge = float(calib.get("edge", 0.0))
    stake = float(calib.get("stake", 1.0))

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

    if edge < prof["edge_hard_floor"]:
        stake *= 0.45
        conf *= 0.80
    elif edge < prof["edge_floor"]:
        stake *= 0.70
        conf *= 0.90

    if vol > prof["vol_hard"]:
        stake *= 0.65
        conf *= 0.90
    elif vol > prof["vol_soft"]:
        stake *= 0.80
        conf *= 0.95

    if trend == "DOWN":
        stake *= prof["trend_down_factor"]
        conf *= prof["trend_down_factor"]
    elif trend == "UP":
        stake *= prof["trend_up_factor"]
        conf *= prof["trend_up_factor"]

    conf = max(0.0, min(conf, 0.99))
    edge = max(0.0, edge)
    stake = max(0.1, stake)

    calib["engine"] = "FAZ-8.2"
    calib["conf"] = round(conf, 3)
    calib["edge"] = round(edge, 3)
    calib["stake"] = round(stake, 2)
    return calib


def faz83_compute_risk_bucket(conf: float,
                              edge: float,
                              conf_avg: float,
                              edge_avg: float):
    conf_avg = max(conf_avg, 1e-6)
    edge_avg = max(edge_avg, 1e-6)

    rel_conf = conf / conf_avg
    rel_edge = edge / edge_avg

    score = 0.6 * rel_conf + 0.4 * rel_edge

    if score < 0.95:
        bucket = "LOW"
    elif score < 1.10:
        bucket = "MID"
    else:
        bucket = "HIGH"

    return bucket, round(score, 4)


def faz83_dynamic_calibration(conf: float,
                              edge: float,
                              stake: float,
                              mode: str,
                              trend_slope: float,
                              vol: float,
                              conf_avg: float,
                              edge_avg: float) -> dict:
    bucket, score = faz83_compute_risk_bucket(conf, edge, conf_avg, edge_avg)

    base_mult_map = {
        "LOW": 0.70,
        "MID": 0.90,
        "HIGH": 1.10,
    }
    base_mult = base_mult_map[bucket]

    slope_clamped = max(min(trend_slope, 0.05), -0.05)
    trend_mult = 1.0 + (slope_clamped * 1.5)

    vol_clamped = max(min(vol, 0.08), 0.0)
    vol_mult = 1.0 - (vol_clamped * 1.5)

    mode = (mode or "BAL").upper()
    if mode == "SAFE":
        mode_mult = 0.85
    elif mode == "AGG":
        mode_mult = 1.10
    else:
        mode_mult = 1.0

    total_mult = base_mult * trend_mult * vol_mult * mode_mult
    total_mult = max(0.40, min(total_mult, 1.40))

    cal_stake = round(stake * total_mult, 2)

    if bucket == "LOW":
        conf_mult = 0.92
        edge_mult = 0.92
    elif bucket == "MID":
        conf_mult = 0.97
        edge_mult = 0.97
    else:
        conf_mult = 1.02
        edge_mult = 1.00

    cal_conf = max(0.0, min(0.99, conf * conf_mult))
    cal_edge = max(0.0, edge * edge_mult)

    return {
        "engine": "FAZ-8.3",
        "bucket": bucket,
        "score": score,
        "raw_conf": round(conf, 3),
        "raw_edge": round(edge, 3),
        "raw_stake": round(stake, 2),
        "cal_conf": round(cal_conf, 3),
        "cal_edge": round(cal_edge, 3),
        "cal_stake": cal_stake,
    }


def faz84_coupon_engine(profile: str,
                        raw_conf: float,
                        raw_edge: float,
                        base_stake: float = 1.0) -> dict:
    core = _faz81_core_calibration(raw_conf, raw_edge, base_stake)
    core82 = _faz82_lmf_shield(core)

    brain = faz79_brain()
    conf_avg = brain["conf"] if brain["conf"] > 0 else max(raw_conf, 0.01)
    edge_avg = brain["edge"] if brain["edge"] > 0 else max(raw_edge, 0.01)

    c83 = faz83_dynamic_calibration(
        conf=core82["conf"],
        edge=core82["edge"],
        stake=core82["stake"],
        mode=brain["mode"],
        trend_slope=brain["slope"],
        vol=brain["vol"],
        conf_avg=conf_avg,
        edge_avg=edge_avg,
    )

    conf = c83["cal_conf"]
    edge = c83["cal_edge"]
    stake = c83["cal_stake"]
    bucket = c83["bucket"]

    profile = (profile or "BAL").upper()
    if profile == "SAFE":
        stake *= 0.85
        conf = min(0.99, conf + 0.02)
    elif profile == "BAL":
        stake *= 1.00
    elif profile == "AGG":
        stake *= 1.12
        conf = max(0.0, conf - 0.01)
    elif profile == "ULTRA":
        stake *= 1.20
        conf = max(0.0, conf - 0.02)

    if bucket == "HIGH" and conf >= 0.67:
        risk_label = "HIGH"
    elif bucket == "LOW" or conf < 0.58:
        risk_label = "LOW"
    else:
        risk_label = "MID"

    stake = round(max(0.1, stake), 2)
    conf = round(max(0.0, min(conf, 0.99)), 2)
    edge = round(max(0.0, edge), 3)

    return {
        "mode": brain["mode"],
        "trend": brain["trend"],
        "bucket": bucket,
        "risk": risk_label,
        "conf": conf,
        "edge": edge,
        "stake": stake,
    }


def faz85_meta_profile_selector() -> str:
    brain = faz79_brain()
    mode = brain["mode"]

    try:
        bucket_info = faz83_dynamic_calibration(
            conf=brain["conf"] if brain["conf"] > 0 else 0.62,
            edge=brain["edge"] if brain["edge"] > 0 else 0.035,
            stake=1.0,
            mode=mode,
            trend_slope=brain["slope"],
            vol=brain["vol"],
            conf_avg=brain["conf"] if brain["conf"] > 0 else 0.62,
            edge_avg=brain["edge"] if brain["edge"] > 0 else 0.035,
        )
        bucket = bucket_info["bucket"]
    except Exception as e:
        log.warning(f"[FAZ-8.5] Bucket hesaplanırken hata: {e}")
        bucket = "MID"

    if mode == "SAFE" and bucket == "HIGH":
        profile = "SAFE"
    elif mode == "BAL":
        profile = "BAL"
    elif mode == "AGG" and bucket == "HIGH":
        profile = "AGG"
    else:
        profile = "BAL"

    log.info(f"[FAZ-8.5] META profile seçildi: mode={mode}, bucket={bucket}, profile={profile}")
    return profile


def faz8_calibrate_signal(raw_conf: float,
                          raw_edge: float,
                          base_stake: float = 1.0) -> dict:
    core = _faz81_core_calibration(raw_conf, raw_edge, base_stake)
    brain = faz79_brain()

    conf_avg = brain["conf"] if brain["conf"] > 0 else max(raw_conf, 0.01)
    edge_avg = brain["edge"] if brain["edge"] > 0 else max(raw_edge, 0.01)

    core82 = _faz82_lmf_shield(core)
    c83 = faz83_dynamic_calibration(
        conf=core82["conf"],
        edge=core82["edge"],
        stake=core82["stake"],
        mode=brain["mode"],
        trend_slope=brain["slope"],
        vol=brain["vol"],
        conf_avg=conf_avg,
        edge_avg=edge_avg,
    )

    return {
        "engine": "FAZ-8.3",
        "mode": brain["mode"],
        "trend": brain["trend"],
        "vol": brain["vol"],
        "bucket": c83["bucket"],
        "score": c83["score"],
        "conf": c83["cal_conf"],
        "edge": c83["cal_edge"],
        "stake": c83["cal_stake"],
    }


# ================================================================
#  FAZ-6 v3 — KUPON MOTORU
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
        "(40 maç / FAZ-8.4 Kupon Motoru + FAZ-8.5 META uyumlu)\n\n"
    )

    for coupon_id in (1, 2, 3, 4):
        if coupon_id == 1:
            title = "🔥 Kupon 1 — SAFE [SAFE]"
            profile = "SAFE"
        elif coupon_id == 2:
            title = "🔥 Kupon 2 — BALANCED [BAL]"
            profile = "BAL"
        elif coupon_id == 3:
            title = "🔥 Kupon 3 — AGGRESSIVE [AGG]"
            profile = "AGG"
        else:
            title = "🔥 Kupon 4 — ULTRA [ULTRA]"
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


# ================================================================
#  NBA SİMÜLASYON (FAZ-8.4 + FAZ-8.5 META)
# ================================================================
def build_nba_simulation_text() -> str:
    home = "MIA"
    away = "NYK"
    skor = 104
    tempo = 98.8
    pace = 98.8

    raw_conf = 0.62
    raw_edge = 0.034

    profile = faz85_meta_profile_selector()
    c = faz84_coupon_engine(profile, raw_conf, raw_edge, base_stake=1.0)

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
#  KOMUT HANDLER’LARI
# ================================================================
def handle_cmd_start(chat_id: int):
    text = (
        "🔥 <b>Bot aktif!</b>\n"
        "FAZ-4 + FAZ-5 + FAZ-6 v3 + FAZ-7.9 v2.0 + "
        "FAZ-8.2 + FAZ-8.3 + FAZ-8.4 + FAZ-8.5 META bağlı.\n"
        "Komut listesi için <code>/help</code> yaz."
    )
    tg_send(chat_id, text)


def handle_cmd_help(chat_id: int):
    text = (
        "📌 <b>Komutlar</b>:\n\n"
        "/start - Botu başlatır\n"
        "/help - Komut listesi\n"
        "/status - Sistem durumu\n\n"
        "/simulate_nba - NBA canlı simülasyon (FAZ-8.4 + FAZ-8.5)\n\n"
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
        "/faz7_plan - FAZ-7.9 strateji planı\n"
        "/faz7_register - Günlük conf & edge kaydı\n\n"
        "— <b>FAZ-8.x</b> —\n"
        "/faz8_status - FAZ-8.x status\n"
        "/faz8_test - Manuel FAZ-8.x sinyal testi\n"
        "/faz83_test - FAZ-8.3 full pipeline testi\n"
    )
    tg_send_long(chat_id, text)


def handle_cmd_status(chat_id: int):
    info = faz79_brain()
    text = (
        "✅ Bot çalışıyor.\n"
        "Mod: <b>Fly.io + Webhook + Flask</b>\n"
        "FAZ-7.9 v2.0 hafıza motoru: <b>AKTİF</b>\n"
        "FAZ-8.2 kalibrasyon: <b>AKTİF</b>\n"
        "FAZ-8.3 full pipeline: <b>AKTİF</b>\n"
        "FAZ-8.4 kupon motoru: <b>AKTİF</b>\n"
        "FAZ-8.5 META profile: <b>AKTİF</b>\n"
        f"Strateji Modu: <b>{info['mode']}</b> | "
        f"Trend: {info['trend']} | Vol: {info['vol']}\n"
        f"Hafıza dosyası: <code>{FAZ7_MEMORY_FILE}</code>\n"
    )
    tg_send(chat_id, text)


def handle_cmd_faz7_status(chat_id: int):
    mem = load_faz7_memory()

    if len(mem.get("days", [])) == 0:
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
    tg_send(chat_id, msg)


def handle_cmd_faz7_plan(chat_id: int):
    info = faz79_brain()
    msg = (
        "🧠 <b>FAZ-7.9 v2.0 STRATEJİ BEYNİ</b>\n\n"
        f"Mod: <b>{info['mode']}</b>\n"
        f"Günlük: conf={info['conf']} edge={info['edge']}\n"
        f"Trend: {info['trend']} (slope {info['slope']})\n"
        f"Volatilite: {info['vol']}\n"
        f"Stake Normalize: {info['stake_norm']}\n\n"
        f"SAFE: {'✅' if info['safe'] else '❌'}\n"
        f"BAL: {'✅' if info['bal'] else '❌'}\n"
        f"AGG: {'✅' if info['agg'] else '❌'}\n"
    )
    tg_send(chat_id, msg)


def handle_cmd_faz7_register(chat_id: int, parts):
    try:
        if len(parts) != 3:
            tg_send(
                chat_id,
                "✅ Kullanım: <code>/faz7_register conf edge</code>\n"
                "Örn: <code>/faz7_register 0.62 0.035</code>",
            )
            return
        conf = float(parts[1])
        edge = float(parts[2])
        register_daily_stats(conf, edge)
        info = faz79_brain()
        tg_send(
            chat_id,
            (
                "✅ Günlük FAZ-7.9 v2.0 kaydı alındı.\n\n"
                f"conf={conf:.3f}, edge={edge:.3f}\n"
                f"Yeni Mod: <b>{info['mode']}</b>\n"
                f"Trend: {info['trend']} (slope {info['slope']})"
            ),
        )
    except Exception as e:
        tg_send(chat_id, f"❌ Kayıt hatası: {e}")


def handle_cmd_faz8_status(chat_id: int):
    raw_conf = 0.64
    raw_edge = 0.038
    base_stake = 1.0

    calib = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)

    msg = (
        "🧪 <b>FAZ-8.x STATUS</b>\n\n"
        f"Mode: <b>{calib['mode']}</b>\n"
        f"Trend: {calib['trend']} | Vol: {calib['vol']}\n"
        f"Engine: <b>{calib.get('engine','FAZ-8.3')}</b>\n"
        f"Bucket: <b>{calib['bucket']}</b> | Score: {calib['score']}\n\n"
        f"Cal → conf=<b>{calib['conf']:.3f}</b>, "
        f"edge=<b>{calib['edge']:.3f}</b>, "
        f"stake=<b>{calib['stake']:.2f}</b>\n"
    )
    tg_send(chat_id, msg)


def handle_cmd_faz8_test(chat_id: int, parts):
    try:
        if len(parts) not in (3, 4):
            tg_send(
                chat_id,
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
            f"Bucket: <b>{calib['bucket']}</b> | Score: {calib['score']}\n\n"
            f"Output → conf=<b>{calib['conf']:.3f}</b>, "
            f"edge=<b>{calib['edge']:.3f}</b>, "
            f"stake=<b>{calib['stake']:.2f}</b>\n"
        )
        tg_send(chat_id, msg)
    except Exception as e:
        tg_send(chat_id, f"❌ FAZ-8 test hatası: {e}")


def handle_cmd_faz83_test(chat_id: int, parts):
    try:
        if len(parts) not in (3, 4):
            tg_send(
                chat_id,
                "✅ Kullanım: <code>/faz83_test conf edge [stake]</code>\n"
                "Örn: <code>/faz83_test 0.63 0.035 0.80</code>",
            )
            return

        raw_conf = float(parts[1])
        raw_edge = float(parts[2])
        base_stake = float(parts[3]) if len(parts) == 4 else 1.0

        c = faz8_calibrate_signal(raw_conf, raw_edge, base_stake)
        brain = faz79_brain()

        msg = (
            "🧪 <b>FAZ-8.3 FULL PIPELINE</b>\n\n"
            f"Input RAW → conf={raw_conf:.3f}, edge={raw_edge:.3f}, stake={base_stake:.2f}\n\n"
            f"FAZ-7.9 v2.0 Brain → mode=<b>{brain['mode']}</b>, "
            f"trend={brain['trend']} (slope {brain['slope']}), vol={brain['vol']}\n"
            f"7g avg → conf={brain['conf']}, edge={brain['edge']}\n\n"
            f"FAZ-8.3 → bucket=<b>{c['bucket']}</b>, score={c['score']}\n"
            f"Calibrated → conf=<b>{c['conf']:.3f}</b>, "
            f"edge=<b>{c['edge']:.3f}</b>, "
            f"stake=<b>{c['stake']:.2f}</b>\n"
        )
        tg_send(chat_id, msg)
    except Exception as e:
        tg_send(chat_id, f"❌ FAZ-8.3 test hatası: {e}")


def handle_cmd_faz6_coupon(chat_id: int):
    try:
        text = build_faz6_coupons_text()
        tg_send_long(chat_id, text)
    except Exception:
        log.error("FAZ-6 kupon oluşturma hatası:\n" + traceback.format_exc())
        tg_send(chat_id, "❌ Kupon üretiminde hata oluştu.")


def handle_cmd_faz6_meta(chat_id: int):
    try:
        text = build_faz6_meta_coupon_text()
        tg_send_long(chat_id, text)
    except Exception:
        log.error("FAZ-6 META kupon hatası:\n" + traceback.format_exc())
        tg_send(chat_id, "❌ META kupon üretiminde hata oluştu.")


def handle_cmd_simulate_nba(chat_id: int):
    try:
        tg_send(chat_id, "🏀 Simülasyon başlatılıyor (FAZ-8.4 + FAZ-8.5 META)...")
        text = build_nba_simulation_text()
        tg_send(chat_id, text)
    except Exception:
        log.error("Simülasyon hatası:\n" + traceback.format_exc())
        tg_send(chat_id, "❌ Simülasyon hatası oluştu.")


def handle_cmd_faz6_placeholders(chat_id: int, cmd: str):
    mapping = {
        "/faz6_test": "🧪 FAZ-6 Test modu placeholder.",
        "/faz6_auto": "🤖 FAZ-6 Auto modu placeholder.",
        "/faz6_risk": "⚠️ FAZ-6 Risk modu placeholder.",
        "/faz6_edge": "📐 FAZ-6 Edge modu placeholder.",
        "/faz6_real": "📊 FAZ-6 Real modu placeholder.",
        "/faz6_balance": "⚖ FAZ-6 Balance modu placeholder.",
    }
    tg_send(chat_id, mapping.get(cmd, "FAZ-6 placeholder."))


# ================================================================
#  UPDATE ROUTER
# ================================================================
def handle_update(update: dict):
    try:
        if "message" not in update:
            return
        msg = update["message"]
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        if chat_id is None:
            return

        text = msg.get("text") or ""
        if not text.startswith("/"):
            return

        parts = text.split()
        cmd = parts[0]
        if "@" in cmd:
            cmd = cmd.split("@")[0]

        if cmd == "/start":
            handle_cmd_start(chat_id)
        elif cmd == "/help":
            handle_cmd_help(chat_id)
        elif cmd == "/status":
            handle_cmd_status(chat_id)
        elif cmd == "/faz7_status":
            handle_cmd_faz7_status(chat_id)
        elif cmd == "/faz7_plan":
            handle_cmd_faz7_plan(chat_id)
        elif cmd == "/faz7_register":
            handle_cmd_faz7_register(chat_id, parts)
        elif cmd == "/faz8_status":
            handle_cmd_faz8_status(chat_id)
        elif cmd == "/faz8_test":
            handle_cmd_faz8_test(chat_id, parts)
        elif cmd == "/faz83_test":
            handle_cmd_faz83_test(chat_id, parts)
        elif cmd == "/faz6_coupon":
            handle_cmd_faz6_coupon(chat_id)
        elif cmd == "/faz6_meta":
            handle_cmd_faz6_meta(chat_id)
        elif cmd == "/simulate_nba":
            handle_cmd_simulate_nba(chat_id)
        elif cmd in (
            "/faz6_test",
            "/faz6_auto",
            "/faz6_risk",
            "/faz6_edge",
            "/faz6_real",
            "/faz6_balance",
        ):
            handle_cmd_faz6_placeholders(chat_id, cmd)
        else:
            tg_send(chat_id, "Komut tanınmadı. Liste için /help")
    except Exception:
        log.error("handle_update içinde hata:\n" + traceback.format_exc())


# ================================================================
#  WEBHOOK SETUP & MAIN
# ================================================================
def setup_webhook():
    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL tanımlı değil, setWebhook atlanıyor.")
        return
    try:
        url = f"{TG_API}/setWebhook"
        full_url = f"{WEBHOOK_URL}/{TOKEN}"
        resp = requests.get(url, params={"url": full_url}, timeout=10)
        log.info(f"setWebhook → status={resp.status_code}, resp={resp.text}")
    except Exception:
        log.error("setWebhook hatası:\n" + traceback.format_exc())


if __name__ == "__main__":
    log.info("🔥 FAZ-7.9 + FAZ-8.x + FAZ-6 v3 core sistemi boot ediliyor...")
    ensure_dir(FAZ7_DIR)
    ensure_dir(FAZ6_DIR)
    init_faz7_memory()
    setup_webhook()
    port = int(os.getenv("PORT", "8080"))
    log.info(f"Flask HTTP server 0.0.0.0:{port} üzerinde çalışıyor.")
    app.run(host="0.0.0.0", port=port)
