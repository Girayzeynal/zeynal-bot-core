import sys
import os
import time
import json
import statistics
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date, datetime

import requests
from telebot import TeleBot

# ============================================================
#                     BOT AYARLARI
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN ortam değişkeni tanımlı değil.")
    sys.exit(1)

bot = TeleBot(BOT_TOKEN)

DATA_DIR = os.getenv("DATA_DIR", ".")
FAZ7_MEMORY_FILE = os.path.join(DATA_DIR, "faz7_memory.json")


# ============================================================
#            FAZ-4 NBA SİMÜLASYON MOTORU
# ============================================================

from nba_fetcher import fetch_nba_live_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState


def _simple_sim_from_game(game: NBAGameState) -> dict:
    hs = game.home_stats
    aw = game.away_stats

    if not hs or not aw:
        return {
            "home": game.home_team,
            "away": game.away_team,
            "score_est": None,
            "pace_est": None,
            "pick": "YOK",
            "confidence": 0.0,
        }

    score_est = hs.pts + aw.pts

    home_pace = hs.pace_est if hs.pace_est is not None else 0
    away_pace = aw.pace_est if aw.pace_est is not None else 0
    pace_est = round((home_pace + away_pace) / 2, 1)

    diff = hs.pts - aw.pts
    if diff > 0:
        pick = game.home_team
    elif diff < 0:
        pick = game.away_team
    else:
        pick = "DENGELİ"

    from math import fabs
    confidence = max(0.5, min(0.99, fabs(diff) / 20.0))

    return {
        "home": game.home_team,
        "away": game.away_team,
        "score_est": round(score_est, 1),
        "pace_est": pace_est,
        "pick": pick,
        "confidence": round(confidence, 2),
    }


# ============================================================
#             FAZ-6 TELEGRAM ÇIKTI FORMATLAYICI
# ============================================================

def format_faz6_message(result: dict) -> str:
    """
    run_faz6_engine çıktısını Telegram mesajına çevirir.
    """
    if not isinstance(result, dict):
        return f"❌ *FAZ-6 HATA*\nGeçersiz sonuç tipi: {type(result).__name__}"

    status = result.get("status", "ok")
    if status != "ok":
        detail = result.get("detail")
        if not detail:
            detail = f"Detay yok. Ham sonuç: {repr(result)}"
        return f"❌ *FAZ-6 HATA*\n{detail}"

    mode = result.get("mode", "").upper()
    output = result.get("result", {})
    preds = output.get("predictions") or output.get("portfolio") or []

    text = f"🧠 *FAZ-6 {mode} SONUCU*\n\n"

    for p in preds:
        text += (
            f"📌 {p.get('id')}\n"
            f"🎯 {p.get('pick')} ({p.get('market')})\n"
            f"📈 Güven: {p.get('confidence')} | Edge: {p.get('edge')}\n"
            f"💰 Stake: {p.get('recommended_stake')}\n"
            f"— — —\n"
        )

    if len(text) > 3800:
        text = text[:3800] + "\n… (çıktı kısaltıldı)"

    return text


# ============================================================
#                 FAZ-6 HAM KUPON MOTORU (BASİT)
#   (FAZ-7.8 ile birleşik kuponlar için altta yeni motor var)
# ============================================================

def basic_build_coupon_message(result: dict, max_coupons: int = 3) -> str:
    if not isinstance(result, dict):
        return "❌ Kupon üretilemedi (geçersiz sonuç)."

    status = result.get("status", "ok")
    if status != "ok":
        detail = result.get("detail", "Kupon için geçerli sonuç yok.")
        return f"❌ Kupon üretilemedi:\n{detail}"

    body = result.get("result", result)
    preds = body.get("portfolio") or body.get("predictions") or []

    if not preds:
        return "❌ Kupon üretilemedi: uygun tahmin bulunamadı."

    per_coupon = max(1, len(preds) // max_coupons or 1)

    coupons = []
    for i in range(0, len(preds), per_coupon):
        coupons.append(preds[i:i + per_coupon])
        if len(coupons) >= max_coupons:
            break

    text = "💵 *FAZ-6 Kupon Önerileri*\n\n"
    for idx, coupon in enumerate(coupons, start=1):
        text += f"🎟 Kupon {idx}\n"
        for p in coupon:
            sel = p.get("pick") or p.get("selection") or "N/A"
            market = p.get("market", "")
            conf = p.get("confidence", p.get("conf", 0))
            edge = p.get("edge", 0)
            match_id = p.get("id", p.get("match", "?"))
            text += (
                f"• {match_id} → {sel} ({market})\n"
                f"  Güven: {conf} | Edge: {edge}\n"
            )
        text += "— — —\n"

    return text


# ============================================================
#                    FAZ-3 TELEGRAM KOMUTLARI
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif!\nFAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7.8 bağlı.\nKomut listesi için /help yaz."
    )


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        """
📌 Komutlar:

/start - Botu başlatır
/status - Sistemi gösterir

/simulate_nba - NBA canlı simülasyon

/heavy - FAZ-5 Standart
/heavy_risk - FAZ-5 Risk
/heavy_edge - FAZ-5 Edge
/heavy_auto - FAZ-5 Otomatik
/heavy_full - FAZ-5 Full

/faz6_test - FAZ-6 Test
/faz6_auto - FAZ-6 Auto
/faz6_risk - FAZ-6 Risk
/faz6_edge - FAZ-6 Edge
/faz6_real - FAZ-6 Real
/faz6_balance - FAZ-6 Balance
/faz6_coupon - FAZ-7 + FAZ-6 birleşik kupon

/faz7_plan - FAZ-7.8 Günlük strateji
/faz7_status - FAZ-7.8 Hafıza özeti (7 gün)
"""
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\n"
        "FAZ-4 aktif.\nFAZ-5 bağlı.\nFAZ-6 tam online.\n"
        "FAZ-7.8 strateji beyni ve hafıza sistemi çalışıyor."
    )


# ============================================================
#                       FAZ-4 NBA KOMUTU
# ============================================================

@bot.message_handler(commands=["simulate_nba"])
def simulate_nba_cmd(message):
    bot.send_message(message.chat.id, "🏀 Simülasyon başlatılıyor...")

    games: List[NBAGameState] = fetch_nba_live_games()
    if not games:
        bot.send_message(message.chat.id, "Canlı NBA verisi bulunamadı.")
        return

    results = [_simple_sim_from_game(g) for g in games]
    analysis = analyze_live_games(games)

    reply = "📊 *NBA Simülasyon Sonuçları*\n\n"
    for r in results:
        reply += (
            f"🏠 {r['home']} vs ✈️ {r['away']}\n"
            f"📈 Tahmini Skor: {r['score_est']}\n"
            f"⏱ Tempo: {r['pace_est']}\n"
            f"🎯 Kazanan: {r['pick']} ({int(r['confidence'] * 100)}%)\n\n"
        )

    reply += "🧠 Ham Analiz:\n" + analysis

    bot.send_message(message.chat.id, reply, parse_mode="Markdown")


# ============================================================
#                       FAZ-5 ENGINE
# ============================================================

from faz5_engine.heavy_engine_main import run_heavy_engine


@bot.message_handler(commands=["heavy"])
def heavy_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="standard"))


@bot.message_handler(commands=["heavy_risk"])
def heavy_risk_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="risk"))


@bot.message_handler(commands=["heavy_edge"])
def heavy_edge_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="edge"))


@bot.message_handler(commands=["heavy_auto"])
def heavy_auto_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="auto"))


@bot.message_handler(commands=["heavy_full"])
def heavy_full_cmd(message):
    bot.reply_to(message, run_heavy_engine(mode="full"))


# ============================================================
#                       FAZ-6 ENGINE WRAPPER
# ============================================================

from faz6_engine import run_faz6_engine as _raw_run_faz6_engine


def safe_run_faz6_engine(mode: str) -> dict:
    try:
        result = _raw_run_faz6_engine(mode=mode)
        if not isinstance(result, dict):
            return {
                "status": "error",
                "detail": f"Motor beklenmeyen tip döndürdü: {type(result).__name__}",
                "raw": result,
            }

        if "status" not in result:
            result = {"status": "ok", **result}

        return result

    except Exception as e:
        return {
            "status": "error",
            "detail": f"FAZ-6 motor exception: {repr(e)}",
        }


def _run_faz6_and_reply(message, mode: str):
    result = safe_run_faz6_engine(mode=mode)
    msg = format_faz6_message(result)
    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=["faz6_test"])
def faz6_test_cmd(message):
    _run_faz6_and_reply(message, "test")


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto_cmd(message):
    _run_faz6_and_reply(message, "auto")


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk_cmd(message):
    _run_faz6_and_reply(message, "risk")


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge_cmd(message):
    _run_faz6_and_reply(message, "edge")


@bot.message_handler(commands=["faz6_real"])
def faz6_real_cmd(message):
    _run_faz6_and_reply(message, "real")


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance_cmd(message):
    _run_faz6_and_reply(message, "balance")


# ============================================================
#              FAZ-7.8 JSON HAFIZA + VOLATİLİTE BEYNİ
# ============================================================

@dataclass
class Faz7DayStat:
    date: str
    runs: int
    avg_conf: float
    avg_edge: float
    mode: str


def _load_faz7_memory() -> Dict[str, Any]:
    try:
        with open(FAZ7_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "days" not in data or not isinstance(data["days"], list):
            data["days"] = []
        return data
    except FileNotFoundError:
        return {"days": []}
    except Exception as e:
        print(f"WARNING: FAZ-7 memory load failed: {e!r}")
        return {"days": []}


def _save_faz7_memory(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(FAZ7_MEMORY_FILE), exist_ok=True)
    except Exception:
        pass
    try:
        with open(FAZ7_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"WARNING: FAZ-7 memory save failed: {e!r}")


def _register_faz7_today(runs: int, avg_conf: float, avg_edge: float, mode: str) -> Dict[str, Any]:
    mem = _load_faz7_memory()
    days: List[Dict[str, Any]] = mem.get("days", [])
    today_str = date.today().isoformat()

    # Aynı güne ait eski kaydı sil
    days = [d for d in days if d.get("date") != today_str]

    days.append(
        {
            "date": today_str,
            "runs": int(runs),
            "avg_conf": float(avg_conf),
            "avg_edge": float(avg_edge),
            "mode": str(mode).upper(),
        }
    )

    # Tarihe göre sırala ve 30 günü geçme
    days.sort(key=lambda d: d.get("date", ""))
    if len(days) > 30:
        days = days[-30:]

    mem["days"] = days
    _save_faz7_memory(mem)
    return mem


def _compute_volatility(last_days: List[Dict[str, Any]]) -> Dict[str, Any]:
    """FAZ-7.8 Volatilite beyni: son günlerin güven/edge oynaklığını ölçer."""
    conf_values = [float(d.get("avg_conf", 0.0)) for d in last_days if d.get("runs", 0) > 0]
    edge_values = [float(d.get("avg_edge", 0.0)) for d in last_days if d.get("runs", 0) > 0]

    if len(conf_values) < 2 or len(edge_values) < 2:
        return {
            "score": 0.0,
            "regime": "INIT",
            "conf_std": 0.0,
            "edge_std": 0.0,
        }

    conf_std = statistics.pstdev(conf_values)
    edge_std = statistics.pstdev(edge_values)

    # Normalizasyon: yaklaşık eşik değerlerine göre
    conf_norm = min(conf_std / 0.03, 2.0)   # 0.03 civarı = orta seviye
    edge_norm = min(edge_std / 0.015, 2.0)  # 0.015 civarı = orta seviye

    score = (conf_norm + edge_norm) / 2.0   # 0 ~ 2 arası

    if score < 0.6:
        regime = "LOW"       # Piyasa sakin, risk alınabilir
    elif score < 1.2:
        regime = "MEDIUM"    # Normal oynaklık
    else:
        regime = "HIGH"      # Sert dalgalanma, frene bas

    return {
        "score": round(score, 3),
        "regime": regime,
        "conf_std": round(conf_std, 4),
        "edge_std": round(edge_std, 4),
    }


def _compute_faz7_brain(mem: Dict[str, Any],
                        today: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    days: List[Dict[str, Any]] = mem.get("days", [])
    last7 = days[-7:]

    if not last7:
        # Hiç veri yoksa en sade mod
        return {
            "avg_conf_7d": 0.0,
            "avg_edge_7d": 0.0,
            "daily_limit": 4.0,
            "stake_normalize": 0.85,
            "volatility": {"score": 0.0, "regime": "INIT", "conf_std": 0.0, "edge_std": 0.0},
            "active_mode": "SAFE",
            "levels": {"SAFE": True, "BAL": False, "AGG": False, "ULTRA": False},
            "stake_mult": {"SAFE": 1.0, "BAL": 1.0, "AGG": 0.9},
            "summary_rows": [
                {"mode": "SAFE", "run": 0, "avg_conf": 0.0, "avg_edge": 0.0, "stake": 1.0},
                {"mode": "BAL", "run": 0, "avg_conf": 0.0, "avg_edge": 0.0, "stake": 1.0},
                {"mode": "AGG", "run": 0, "avg_conf": 0.0, "avg_edge": 0.0, "stake": 0.9},
            ],
            "today": today,
            "raw_days": last7,
        }

    conf_values = [float(d.get("avg_conf", 0.0)) for d in last7 if d.get("runs", 0) > 0]
    edge_values = [float(d.get("avg_edge", 0.0)) for d in last7 if d.get("runs", 0) > 0]

    if conf_values:
        avg_conf_7d = sum(conf_values) / len(conf_values)
    else:
        avg_conf_7d = 0.0

    if edge_values:
        avg_edge_7d = sum(edge_values) / len(edge_values)
    else:
        avg_edge_7d = 0.0

    vol = _compute_volatility(last7)

    # FAZ-7.8 karar mantığı
    regime = vol["regime"]
    l7 = len(last7)

    # Başlangıç stake normalize faktörü (çok agresif olmasın)
    stake_norm = 0.8
    if avg_conf_7d > 0.60:
        stake_norm += 0.05
    if avg_edge_7d > 0.03:
        stake_norm += 0.05
    # hafif fren: 0.85 civarına sabitlenir
    stake_norm = max(0.75, min(stake_norm, 0.9))

    # Varsayılanlar
    safe_on = True
    bal_on = True
    agg_on = False
    active_mode = "SAFE"
    safe_mult = 1.0
    bal_mult = 1.0
    agg_mult = 0.9

    if l7 < 3 or regime == "INIT":
        # Veri az, temkinli BAL
        active_mode = "BAL"
        safe_mult = 1.0
        bal_mult = 1.0
        agg_mult = 0.9
        agg_on = False
    else:
        if regime == "LOW":
            # Piyasa sakin, agresif açılabilir
            safe_mult = 0.9
            bal_mult = 1.0
            agg_mult = 1.1
            safe_on = True
            bal_on = True
            agg_on = True
            active_mode = "BAL"
        elif regime == "MEDIUM":
            # Orta oynaklık: dengeli yapı
            safe_mult = 1.0
            bal_mult = 1.0
            agg_mult = 0.9
            safe_on = True
            bal_on = True
            agg_on = avg_conf_7d >= 0.60 and avg_edge_7d >= 0.03
            active_mode = "BAL"
        else:  # HIGH
            # Sert dalgalanma: SAFE ağırlık
            safe_mult = 1.1
            bal_mult = 0.95
            agg_mult = 0.8
            safe_on = True
            bal_on = True
            agg_on = False
            active_mode = "SAFE"

    summary_rows = [
        {"mode": "SAFE", "run": 1 if safe_on else 0, "avg_conf": 0.0, "avg_edge": 0.0, "stake": round(safe_mult, 2)},
        {"mode": "BAL", "run": 1, "avg_conf": round(avg_conf_7d, 3), "avg_edge": round(avg_edge_7d, 4),
         "stake": round(bal_mult, 2)},
        {"mode": "AGG", "run": 1 if agg_on else 0, "avg_conf": 0.0, "avg_edge": 0.0, "stake": round(agg_mult, 2)},
    ]

    brain = {
        "avg_conf_7d": round(avg_conf_7d, 3),
        "avg_edge_7d": round(avg_edge_7d, 4),
        "daily_limit": 4.0,
        "stake_normalize": round(stake_norm, 2),
        "volatility": vol,
        "active_mode": active_mode,
        "levels": {
            "SAFE": safe_on,
            "BAL": bal_on,
            "AGG": agg_on,
            "ULTRA": False,
        },
        "stake_mult": {
            "SAFE": round(safe_mult, 2),
            "BAL": round(bal_mult, 2),
            "AGG": round(agg_mult, 2),
        },
        "summary_rows": summary_rows,
        "today": today,
        "raw_days": last7,
    }
    return brain


def _extract_stats_from_faz6_result(result: Dict[str, Any]) -> Dict[str, Any]:
    body = result.get("result", {})
    preds = body.get("portfolio") or body.get("predictions") or []
    if not preds:
        return {"runs": 0, "avg_conf": 0.0, "avg_edge": 0.0}

    confs = [float(p.get("confidence", 0.0)) for p in preds]
    edges = [float(p.get("edge", 0.0)) for p in preds]

    return {
        "runs": len(preds),
        "avg_conf": sum(confs) / len(confs),
        "avg_edge": sum(edges) / len(edges),
    }


# ============================================================
#          FAZ-7.8 + FAZ-6 BİRLEŞİK KUPON MOTORU
# ============================================================

def build_faz7_faz6_coupons(engine_result: Dict[str, Any]) -> str:
    status = engine_result.get("status", "ok")
    if status != "ok":
        detail = engine_result.get("detail", "Bilinmeyen hata")
        return f"❌ *FAZ-6/FAZ-7 HATA*\n{detail}"

    body = engine_result.get("result", {})
    preds: List[Dict[str, Any]] = body.get("portfolio") or body.get("predictions") or []
    if not preds:
        return "⚠ Kupon oluşturmak için yeterli tahmin bulunamadı."

    # FAZ-7 gün içi istatistiklerini çıkar
    stats = _extract_stats_from_faz6_result(engine_result)
    today_info = {
        "date": date.today().isoformat(),
        "runs": stats["runs"],
        "avg_conf": stats["avg_conf"],
        "avg_edge": stats["avg_edge"],
        "mode": "BAL",
    }

    mem = _register_faz7_today(
        runs=stats["runs"],
        avg_conf=stats["avg_conf"],
        avg_edge=stats["avg_edge"],
        mode="BAL",
    )
    brain = _compute_faz7_brain(mem, today=today_info)

    avg_conf_7d = brain["avg_conf_7d"]
    avg_edge_7d = brain["avg_edge_7d"]
    daily_limit = brain["daily_limit"]
    stake_norm = brain["stake_normalize"]
    vol = brain["volatility"]
    stake_mult = brain["stake_mult"]
    levels = brain["levels"]
    active_mode = brain["active_mode"]

    # Aktif seviye listesi
    level_order = [lvl for lvl in ["SAFE", "BAL", "AGG"] if levels.get(lvl, False)]
    if not level_order:
        level_order = ["SAFE"]

    # Tahminleri 6 maçla sınırlayalım, üç kupona paylaştıralım
    preds_sorted = sorted(
        preds,
        key=lambda p: (p.get("edge", 0.0), p.get("confidence", 0.0)),
        reverse=True,
    )
    preds_used = preds_sorted[: min(len(preds_sorted), 6)]

    coupons: Dict[str, List[Dict[str, Any]]] = {lvl: [] for lvl in level_order}
    for idx, p in enumerate(preds_used):
        lvl = level_order[idx % len(level_order)]
        coupons[lvl].append(p)

    # Mesaj metni
    lines: List[str] = []
    lines.append("💰 *FAZ-7 + FAZ-6 BİRLEŞİK KUPONLAR*\n")
    lines.append(
        f"📊 Ortalama Güven (7g): {avg_conf_7d:.3f}\n"
        f"📊 Ortalama Edge (7g): {avg_edge_7d:.3f}\n"
        f"📆 Günlük Limit: {daily_limit:.1f}\n"
        f"📈 Volatilite: {vol['regime']} (skor: {vol['score']})\n"
        f"🤖 Aktif Mod: {active_mode}\n"
        f"🛠 Stake Normalize: {stake_norm:.2f}x\n"
    )

    emoji_map = {
        "SAFE": "🔥 Kupon 1 — SAFE",
        "BAL": "🔥 Kupon 2 — BALANCED",
        "AGG": "🔥 Kupon 3 — AGGRESSIVE",
    }

    for lvl in level_order:
        coupon = coupons.get(lvl, [])
        if not coupon:
            continue

        lines.append("")
        lines.append(emoji_map.get(lvl, f"🔥 Kupon ({lvl})"))

        lvl_mult = stake_mult.get(lvl, 1.0)

        total_stake = 0.0
        for p in coupon:
            base_stake = float(p.get("recommended_stake", 1.0))
            adj_stake = round(base_stake * lvl_mult * stake_norm, 2)
            total_stake += adj_stake

            lines.append(
                f"- {p.get('id')} | {p.get('pick')} ({p.get('market')})\n"
                f"  Güven: {p.get('confidence')} | Edge: {p.get('edge')} | Stake: {adj_stake}"
            )

        lines.append(f"💰 Kupon Toplam Stake: {round(total_stake, 2)}")
        lines.append("— — —")

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n… (çıktı kısaltıldı)"
    return text


# ============================================================
#               FAZ-7.8 PLAN / STATUS KOMUTLARI
# ============================================================

@bot.message_handler(commands=["faz7_plan"])
def faz7_plan_cmd(message):
    mem = _load_faz7_memory()
    days = mem.get("days", [])
    today = days[-1] if days else None
    brain = _compute_faz7_brain(mem, today=today)

    vol = brain["volatility"]
    levels = brain["levels"]
    s_mult = brain["stake_mult"]

    today_line = "Veri yok"
    if today:
        today_line = (
            f"{today.get('date')} | Maç: {today.get('runs', 0)} | "
            f"Conf: {today.get('avg_conf', 0.0):.3f} | "
            f"Edge: {today.get('avg_edge', 0.0):.3f} | "
            f"Mod: {today.get('mode', 'N/A')}"
        )

    txt = []
    txt.append("🧠 *FAZ-7.8 GÜNLÜK STRATEJİ BEYNİ*\n")
    txt.append(
        f"🎯 Mod: {brain['active_mode']}\n"
        f"📊 Bugün: {today_line}\n"
        f"📊 7g Ortalama Conf: {brain['avg_conf_7d']:.3f} | Edge: {brain['avg_edge_7d']:.3f}\n"
        f"📉 Volatilite: {vol['regime']} (skor: {vol['score']}, "
        f"σC={vol['conf_std']}, σE={vol['edge_std']})\n"
        f"🔧 Stake Normalize: {brain['stake_normalize']:.2f}x\n"
    )

    txt.append("📦 *Seviye Durumu*")
    txt.append(
        f"- SAFE: {'✅' if levels['SAFE'] else '❌'} (x{s_mult['SAFE']})\n"
        f"- BALANCED: {'✅' if levels['BAL'] else '❌'} (x{s_mult['BAL']})\n"
        f"- AGGRESSIVE: {'✅' if levels['AGG'] else '❌'} (x{s_mult['AGG']})\n"
        f"- ULTRA: 🚫 (manuel kapalı)\n"
    )

    if len(days) == 0:
        txt.append("ℹ Henüz hafızada gün yok.")
    elif len(days) < 2:
        txt.append("ℹ Dün ile karşılaştırma için yeterli veri yok.")
    elif len(days) < 3:
        txt.append("ℹ Trend analizi için en az 3 gün gerekli.")

    # Son gün satırı
    if days:
        last = days[-1]
        txt.append("\n🗓 *Son FAZ-7 Kayıt*")
        txt.append(
            f"- {last.get('date')} | Maç: {last.get('runs', 0)} | "
            f"Conf: {last.get('avg_conf', 0.0):.3f} | "
            f"Edge: {last.get('avg_edge', 0.0):.3f} | "
            f"Mod: {last.get('mode', 'N/A')}"
        )

    bot.reply_to(message, "\n".join(txt), parse_mode="Markdown")


@bot.message_handler(commands=["faz7_status"])
def faz7_status_cmd(message):
    mem = _load_faz7_memory()
    brain = _compute_faz7_brain(mem)

    rows = brain["summary_rows"]

    header = "Mod | Run | Avg Conf | Avg Edge | Stake x"
    sep = "----|-----|----------|----------|--------"

    def fmt_row(r):
        return (
            f"{r['mode']:<4}|"
            f" {r['run']:<3}|"
            f" {r['avg_conf']:<8.3f}|"
            f" {r['avg_edge']:<8.4f}|"
            f" {r['stake']:<6.2f}"
        )

    lines = [
        "🧠 *FAZ-7 HAFIZA ÖZETİ* (Son 7 Gün)\n",
        header,
        sep,
    ]
    for r in rows:
        lines.append(fmt_row(r))

    lines.append(
        "\n_Not: Stake çarpanları FAZ-7.8 beyni tarafından "
        "son 7 güne ve oynaklığa göre ayarlanır._"
    )

    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


# ============================================================
#                    FAZ-6 KUPON KOMUTU
# ============================================================

@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    # Kupon üretimi için FAZ-6 balance modunu kullanıyoruz
    result = safe_run_faz6_engine(mode="balance")
    msg = build_faz7_faz6_coupons(result)
    bot.reply_to(message, msg, parse_mode="Markdown")


# ============================================================
#                FLY.IO HEALTHCHECK SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")


def start_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    print("INFO: Health server 0.0.0.0:8080 üzerinde çalışıyor.")
    server.serve_forever()


# ============================================================
#                    HEARTBEAT (ANTI-IDLE)
# ============================================================

def heartbeat():
    while True:
        try:
            requests.get("http://127.0.0.1:8080", timeout=3)
        except Exception:
            pass
        time.sleep(20)


# ============================================================
#                    BOT POLLING LOOP
# ============================================================

def start_bot():
    while True:
        try:
            print("INFO: Telegram bot polling başlıyor...")
            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=60,
            )
        except Exception as e:
            print(f"ERROR: Polling hata verdi: {e!r}")
            time.sleep(3)


# ============================================================
#                      ÇALIŞTIRMA NOKTASI
# ============================================================

def main():
    print("INFO: Bot başlatıldı. Tüm motorlar aktif (FAZ-7.8 dahil).")

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    start_bot()


if __name__ == "__main__":
    main()
