import sys
import os
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

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
#               FAZ-6 KUPON MOTORU (YENİ - İÇERDE)
# ============================================================

def build_coupon_message(result: dict, max_coupons: int = 3) -> str:
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
        "🔥 Bot aktif!\nFAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7 bağlı.\nKomut listesi için /help yaz."
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
/faz6_coupon - FAZ-6 Kupon (3 kupon)

/faz7_plan - Günlük FAZ-7 strateji & hafıza raporu
"""
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\nFAZ-4 aktif.\nFAZ-5 bağlı.\nFAZ-6 tam online.\nFAZ-7 strateji beyni çalışıyor."
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
#                    FAZ-6 KUPON (3 Kupon)
# ============================================================

@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    result = safe_run_faz6_engine(mode="balance")
    msg = build_coupon_message(result, max_coupons=3)
    bot.reply_to(message, msg, parse_mode="Markdown")


# ============================================================
#                 FAZ-7 STRATEJİ BEYNİ + HAFIZA
# ============================================================

FAZ7_MEMORY_FILE = "faz7_memory.json"
FAZ7_MEMORY_DAYS = 7  # 7 günlük hafıza


def _load_faz7_memory() -> List[Dict[str, Any]]:
    try:
        if not os.path.exists(FAZ7_MEMORY_FILE):
            return []
        with open(FAZ7_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []


def _save_faz7_memory(entries: List[Dict[str, Any]]) -> None:
    try:
        with open(FAZ7_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception:
        # Hafıza yazılamasa bile bot çalışmaya devam etsin
        pass


def _summarize_faz6_for_faz7(engine_result: Dict[str, Any]) -> Dict[str, Any]:
    result = engine_result.get("result", {})
    preds: List[Dict[str, Any]] = (
        result.get("portfolio")
        or result.get("predictions")
        or []
    )

    if not preds:
        return {
            "total_picks": 0,
            "avg_conf": 0.0,
            "avg_edge": 0.0,
            "high_conf_picks": 0,
        }

    total_conf = 0.0
    total_edge = 0.0
    high_conf = 0

    for p in preds:
        c = float(p.get("confidence", 0.0))
        e = float(p.get("edge", 0.0))
        total_conf += c
        total_edge += e
        if c >= 0.60:
            high_conf += 1

    n = len(preds)
    return {
        "total_picks": n,
        "avg_conf": round(total_conf / n, 3),
        "avg_edge": round(total_edge / n, 3),
        "high_conf_picks": high_conf,
    }


def _decide_faz7_levels(day_stats: Dict[str, Any]) -> Dict[str, Any]:
    """
    SAFE / BALANCED / AGGRESSIVE seviyelerini ve stake çarpanlarını belirler.
    """
    avg_conf = float(day_stats.get("avg_conf", 0.0))
    avg_edge = float(day_stats.get("avg_edge", 0.0))
    total_picks = int(day_stats.get("total_picks", 0))

    # Default kapalı
    levels = {
        "safe_on": False,
        "balanced_on": False,
        "aggressive_on": False,
        "ultra_on": False,
    }

    # Threshold mantığı:
    # - Top maç yoksa: sadece SAFE
    if total_picks == 0:
        levels["safe_on"] = True
        mode_label = "SAFE"
    else:
        score = avg_conf * 100 + avg_edge * 1000  # biraz ağırlıklandırma

        if score < 58 * 100 + 10:  # düşük güven & edge
            levels["safe_on"] = True
            mode_label = "SAFE"
        elif score < 62 * 100 + 25:
            levels["balanced_on"] = True
            mode_label = "BALANCED"
        else:
            levels["aggressive_on"] = True
            mode_label = "AGGRESSIVE"

    # Stake çarpanları (FAZ-7 normalizasyon)
    stake_factors = {
        "safe_factor": 0.7,
        "balanced_factor": 1.0,
        "aggressive_factor": 1.3,
        "ultra_factor": 0.0,  # ULTRA by design kapalı
    }

    return {
        "mode_label": mode_label,
        "levels": levels,
        "stake_factors": stake_factors,
    }


def _update_faz7_memory(today_stats: Dict[str, Any],
                        decision: Dict[str, Any]) -> List[Dict[str, Any]]:
    memory = _load_faz7_memory()
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    entry = {
        "date": today_str,
        "total_picks": int(today_stats.get("total_picks", 0)),
        "avg_conf": float(today_stats.get("avg_conf", 0.0)),
        "avg_edge": float(today_stats.get("avg_edge", 0.0)),
        "high_conf_picks": int(today_stats.get("high_conf_picks", 0)),
        "mode_label": decision.get("mode_label"),
    }

    # Aynı güne ait eski kayıt varsa sil
    memory = [m for m in memory if m.get("date") != today_str]
    memory.append(entry)

    # Tarihe göre sırala, son 7 günü tut
    memory.sort(key=lambda x: x.get("date", ""))
    if len(memory) > FAZ7_MEMORY_DAYS:
        memory = memory[-FAZ7_MEMORY_DAYS:]

    _save_faz7_memory(memory)
    return memory


def _render_faz7_memory_table(memory: List[Dict[str, Any]]) -> str:
    if not memory:
        return "_Hafızada kayıt yok (ilk gün)._"

    lines = []
    lines.append("📅 *Son 7 Günlük FAZ-7 Hafıza*")
    for m in memory:
        lines.append(
            f"- {m.get('date')} | "
            f"Maç: {m.get('total_picks')} | "
            f"Conf: {m.get('avg_conf')} | "
            f"Edge: {m.get('avg_edge')} | "
            f"Mod: {m.get('mode_label')}"
        )
    return "\n".join(lines)


def _render_faz7_yesterday_vs_today(memory: List[Dict[str, Any]]) -> str:
    if len(memory) < 2:
        return "_Dün ile karşılaştırma için yeterli veri yok._"

    today = memory[-1]
    yesterday = memory[-2]

    def arrow(curr: float, prev: float) -> str:
        if curr > prev:
            return "📈"
        if curr < prev:
            return "📉"
        return "➖"

    conf_arrow = arrow(today["avg_conf"], yesterday["avg_conf"])
    edge_arrow = arrow(today["avg_edge"], yesterday["avg_edge"])

    return (
        "📊 *Dün / Bugün Karşılaştırma*\n"
        f"- Güven: {yesterday['avg_conf']} → {today['avg_conf']} {conf_arrow}\n"
        f"- Edge:  {yesterday['avg_edge']} → {today['avg_edge']} {edge_arrow}\n"
        f"- Mod:   {yesterday['mode_label']} → {today['mode_label']}"
    )


def _render_faz7_trend_comment(memory: List[Dict[str, Any]]) -> str:
    if len(memory) < 3:
        return "_Trend analizi için en az 3 gün gerekli._"

    last = memory[-3:]
    avg_conf = sum(float(x.get("avg_conf", 0.0)) for x in last) / len(last)
    avg_edge = sum(float(x.get("avg_edge", 0.0)) for x in last) / len(last)

    # Basit yorum
    if avg_conf >= 0.62 and avg_edge >= 0.025:
        comment = "Form yükseliyor, sistem son günlerde sıcak."
    elif avg_conf <= 0.58 and avg_edge <= 0.015:
        comment = "Form düşük, daha kontrollü gitmek mantıklı."
    else:
        comment = "Nötr bölgede, standard disiplinli oyun uygun."

    return (
        "🧠 *FAZ-7 Trend Yorumu (Son 3 Gün)*\n"
        f"- Ortalama Güven: {round(avg_conf, 3)}\n"
        f"- Ortalama Edge:  {round(avg_edge, 3)}\n"
        f"- Not: {comment}"
    )


def _render_faz7_plan_text(day_stats: Dict[str, Any],
                           decision: Dict[str, Any],
                           memory: List[Dict[str, Any]]) -> str:
    mode_label = decision.get("mode_label", "UNKNOWN")
    levels = decision.get("levels", {})
    stake_factors = decision.get("stake_factors", {})

    safe_on = levels.get("safe_on", False)
    bal_on = levels.get("balanced_on", False)
    agg_on = levels.get("aggressive_on", False)
    ultra_on = False  # Tasarımsal olarak kapalı

    lines = []

    # Başlık
    lines.append("🧠 *FAZ-7 GÜNLÜK STRATEJİ BEYNİ*")
    lines.append("")
    lines.append(f"🎯 Mod: *{mode_label}*")
    lines.append(
        f"📊 Bugün | Maç: {day_stats.get('total_picks')} | "
        f"Conf: {day_stats.get('avg_conf')} | Edge: {day_stats.get('avg_edge')}"
    )
    lines.append("")

    # Level durumu
    lines.append("🎚 *Seviye Durumu*")
    lines.append(f"- SAFE: {'✅' if safe_on else '❌'}  (x{stake_factors.get('safe_factor', 0.7)})")
    lines.append(f"- BALANCED: {'✅' if bal_on else '❌'}  (x{stake_factors.get('balanced_factor', 1.0)})")
    lines.append(f"- AGGRESSIVE: {'✅' if agg_on else '❌'}  (x{stake_factors.get('aggressive_factor', 1.3)})")
    lines.append(f"- ULTRA: 🚫 (manuel kapalı)")
    lines.append("")

    # Hafıza tablosu (1. seçenek)
    lines.append(_render_faz7_memory_table(memory))
    lines.append("")

    # Dün / Bugün karşılaştırma (2. seçenek)
    lines.append(_render_faz7_yesterday_vs_today(memory))
    lines.append("")

    # Trend yorumu (4. seçenek)
    lines.append(_render_faz7_trend_comment(memory))

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n… (FAZ-7 çıktı kısaltıldı)"
    return text


def compute_faz7_daily_plan() -> Dict[str, Any]:
    """
    FAZ-6 BALANCE modunu çalıştırır, bugünün istatistiğini çıkarır,
    FAZ-7 kararını üretir ve hafızayı günceller.
    """
    engine_result = safe_run_faz6_engine(mode="balance")

    if engine_result.get("status") != "ok":
        return {
            "status": "error",
            "detail": engine_result.get("detail", "FAZ-6 sonucu alınamadı."),
        }

    day_stats = _summarize_faz6_for_faz7(engine_result)
    decision = _decide_faz7_levels(day_stats)
    memory = _update_faz7_memory(day_stats, decision)

    plan_text = _render_faz7_plan_text(day_stats, decision, memory)

    return {
        "status": "ok",
        "day_stats": day_stats,
        "decision": decision,
        "memory": memory,
        "text": plan_text,
    }


@bot.message_handler(commands=["faz7_plan"])
def faz7_plan_cmd(message):
    plan = compute_faz7_daily_plan()
    if plan.get("status") != "ok":
        bot.reply_to(
            message,
            f"❌ FAZ-7 plan üretilemedi:\n{plan.get('detail', 'Bilinmeyen hata')}",
            parse_mode="Markdown",
        )
        return

    bot.reply_to(message, plan["text"], parse_mode="Markdown")


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
    print("INFO: Bot başlatıldı. Tüm motorlar aktif.")

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    start_bot()


if __name__ == "__main__":
    main()
