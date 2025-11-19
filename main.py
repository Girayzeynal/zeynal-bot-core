import sys
import os
import time
import json
from typing import List, Dict, Any, Optional
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from statistics import mean, pstdev

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

# FAZ-7 hafıza dosyası
FAZ7_MEMORY_FILE = "faz7_memory.json"


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
#          FAZ-7.5 STRATEJİ BEYNİ – MEMORY & BRAIN
# ============================================================

def _today_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _load_faz7_memory() -> List[Dict[str, Any]]:
    try:
        with open(FAZ7_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"WARNING: FAZ-7 memory read error: {e!r}")
    return []


def _save_faz7_memory(entries: List[Dict[str, Any]]) -> None:
    try:
        with open(FAZ7_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"WARNING: FAZ-7 memory write error: {e!r}")


def _summarise_today_from_preds(preds: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not preds:
        return {
            "date": _today_str(),
            "matches": 0,
            "avg_conf": 0.0,
            "avg_edge": 0.0,
        }
    confs = [float(p.get("confidence", 0.0)) for p in preds]
    edges = [float(p.get("edge", 0.0)) for p in preds]
    return {
        "date": _today_str(),
        "matches": len(preds),
        "avg_conf": round(mean(confs), 3),
        "avg_edge": round(mean(edges), 3),
    }


def _compute_quality(entry: Dict[str, Any]) -> float:
    """
    0–1 arası bir 'gün kalitesi' skoru.
    Conf, edge ve maç sayısını karışık kullanıyoruz.
    """
    conf = float(entry.get("avg_conf", 0.0))
    edge = float(entry.get("avg_edge", 0.0))
    n = int(entry.get("matches", 0))

    conf_score = max(0.0, min(1.0, (conf - 0.55) / 0.2))   # 0.55–0.75 bandı
    edge_score = max(0.0, min(1.0, (edge - 0.015) / 0.04)) # 0.015–0.055 bandı
    volume_score = max(0.0, min(1.0, n / 10.0))            # 10 maçta 1.0

    quality = 0.5 * conf_score + 0.3 * edge_score + 0.2 * volume_score
    return round(quality, 3)


def _faz75_brain_decide(
    today_entry: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    FAZ-7.5 Ultra Brain ana kararı:
    - Mod: SAFE / BAL / AGG
    - Stake çarpanları: safe_x, bal_x, agg_x
    - ULTRA daima manuel kapalı.
    """

    today_q = _compute_quality(today_entry)
    last7 = history[-7:]

    # Volatilite: son 7 gün kalite skorlarının standart sapması
    if last7:
        qs = [_compute_quality(e) for e in last7]
        vol = pstdev(qs) if len(qs) > 1 else 0.0
    else:
        vol = 0.0

    # Trend: son 3 gün kalite hareketi
    recent3 = last7[-3:]
    if len(recent3) >= 2:
        trend_delta = _compute_quality(recent3[-1]) - _compute_quality(recent3[0])
    else:
        trend_delta = 0.0

    # --------------------------------------------------------
    # 1) Ana mod seçimi (SAFE / BAL / AGG)
    # --------------------------------------------------------
    base_mode = "BAL"
    if today_q < 0.45:
        base_mode = "SAFE"
    elif today_q > 0.7 and trend_delta > 0:
        base_mode = "AGG"
    else:
        base_mode = "BAL"

    # --------------------------------------------------------
    # 2) Stake çarpanlarının çıplak halleri
    # --------------------------------------------------------
    safe_x = 0.9
    bal_x = 1.0
    agg_x = 1.1

    # İyi gün kalitesi → genel stake buff
    if today_q > 0.65:
        safe_x += 0.05
        bal_x += 0.10
        agg_x += 0.15
    elif today_q < 0.4:
        safe_x -= 0.1
        bal_x -= 0.15
        agg_x -= 0.2

    # Volatilite yüksekse → overconfidence correction
    if vol > 0.12:
        safe_x -= 0.05
        bal_x -= 0.10
        agg_x -= 0.15

    # Trend düşüşteyse → risk damping
    if trend_delta < -0.05:
        safe_x -= 0.05
        bal_x -= 0.10
        agg_x -= 0.10

    # Mode’a göre ekstra dokunuşlar
    if base_mode == "SAFE":
        safe_x += 0.05
        agg_x -= 0.1
    elif base_mode == "AGG":
        agg_x += 0.1

    # Alt sınır / üst sınır
    def _clip(x: float) -> float:
        return round(max(0.5, min(1.6, x)), 2)

    safe_x = _clip(safe_x)
    bal_x = _clip(bal_x)
    agg_x = _clip(agg_x)

    return {
        "mode": base_mode,
        "today_quality": today_q,
        "volatility": round(vol, 3),
        "trend_delta": round(trend_delta, 3),
        "safe_x": safe_x,
        "bal_x": bal_x,
        "agg_x": agg_x,
        "ultra_enabled": False,
    }


def _update_faz7_memory_with_today(today_entry: Dict[str, Any],
                                   brain: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Bugünün kaydını hafızaya yazar. Son 30 gün tutulur, FAZ-7 display için
    son 7 gün kullanılıyor.
    """
    mem = _load_faz7_memory()
    today = today_entry.get("date", _today_str())

    # aynı güne ait eski kayıt varsa sil
    mem = [e for e in mem if e.get("date") != today]

    entry = {
        **today_entry,
        "mode": brain["mode"],
        "quality": brain["today_quality"],
        "safe_x": brain["safe_x"],
        "bal_x": brain["bal_x"],
        "agg_x": brain["agg_x"],
    }
    mem.append(entry)
    mem.sort(key=lambda e: e.get("date"))

    # 30 günlük hafıza
    if len(mem) > 30:
        mem = mem[-30:]

    _save_faz7_memory(mem)
    return mem


def faz7_compute_plan(preds: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    FAZ-6 kupon üreticisi ve FAZ-7 komutları için tek giriş noktası.
    """
    today_summary = _summarise_today_from_preds(preds)
    mem_before = _load_faz7_memory()
    brain = _faz75_brain_decide(today_summary, mem_before)
    mem_after = _update_faz7_memory_with_today(today_summary, brain)

    return {
        "today": today_summary,
        "brain": brain,
        "memory": mem_after,
    }


def _format_faz7_plan_text(plan: Dict[str, Any]) -> str:
    today = plan["today"]
    brain = plan["brain"]
    mem = plan["memory"]

    mode = brain["mode"]
    m = today["matches"]
    c = today["avg_conf"]
    e = today["avg_edge"]

    text = []
    text.append("🧠 *FAZ-7 GÜNLÜK STRATEJİ BEYNİ*")
    text.append("")
    text.append(f"🎯 Mod: *{mode}*")
    text.append(
        f"📊 Bugün | Maç: {m} | Conf: {c:.3f} | Edge: {e:.3f}"
    )
    text.append("")
    text.append("🧱 *Seviye Durumu*")
    text.append(
        f"- SAFE:     {'✅' if mode == 'SAFE' else '❌'} (x{brain['safe_x']})"
    )
    text.append(
        f"- BALANCED: {'✅' if mode == 'BAL' else '❌'} (x{brain['bal_x']})"
    )
    text.append(
        f"- AGGRESSIVE: {'✅' if mode == 'AGG' else '❌'} (x{brain['agg_x']})"
    )
    text.append("- ULTRA: 🚫 (manuel kapalı)")
    text.append("")

    last7 = mem[-7:]
    if last7:
        text.append("📅 *Son 7 Günlük FAZ-7 Hafıza*")
        for e2 in last7:
            text.append(
                f"- {e2['date']} | Maç: {e2['matches']} | "
                f"Conf: {e2['avg_conf']:.3f} | Edge: {e2['avg_edge']:.3f} "
                f"| Mod: {e2.get('mode','?')}"
            )
    else:
        text.append("📅 Henüz hafıza kaydı yok.")

    if len(last7) >= 2:
        y = last7[-2]
        t = last7[-1]
        diff_c = t["avg_conf"] - y["avg_conf"]
        diff_e = t["avg_edge"] - y["avg_edge"]
        text.append("")
        text.append(
            f"📈 Dün ↔ Bugün farkı | Conf: {diff_c:+.3f} | Edge: {diff_e:+.3f}"
        )
    else:
        text.append("")
        text.append("ℹ Dün ile karşılaştırma için yeterli veri yok.")

    if len(last7) >= 3:
        qs = [_compute_quality(e2) for e2 in last7]
        trend = qs[-1] - qs[0]
        text.append(
            f"📉 7 Günlük trend kalite farkı: {trend:+.3f}"
        )
    else:
        text.append("ℹ Trend analizi için en az 3 gün gerekli.")

    return "\n".join(text)


def _format_faz7_status_text() -> str:
    mem = _load_faz7_memory()
    last7 = mem[-7:]

    modes = ["SAFE", "BAL", "AGG"]
    rows = []

    for mod in modes:
        rows_mod = [e for e in last7 if e.get("mode") == mod]
        run = len(rows_mod)
        if run:
            avg_conf = mean(e["avg_conf"] for e in rows_mod)
            avg_edge = mean(e["avg_edge"] for e in rows_mod)
            stake_x = {
                "SAFE": rows_mod[-1].get("safe_x", 1.0),
                "BAL": rows_mod[-1].get("bal_x", 1.0),
                "AGG": rows_mod[-1].get("agg_x", 1.0),
            }.get(mod, 1.0)
        else:
            avg_conf = 0.0
            avg_edge = 0.0
            stake_x = 1.0 if mod == "BAL" else (1.1 if mod == "SAFE" else 0.9)

        rows.append(
            f"{mod:<4}| {run:>3} |{avg_conf:6.3f} |{avg_edge:7.4f} |{stake_x:7.2f}"
        )

    header = (
        "🧠 *FAZ-7 HAFIZA ÖZETİ* (Son 7 Gün)\n\n"
        "Mod | Run | Avg Conf | Avg Edge | Stake x\n"
        "----|-----|----------|----------|--------\n"
    )
    body = "\n".join(rows)
    footer = "\n\n_Not: Stake çarpanları FAZ-7.5 beyni tarafından son 7 güne göre ayarlanır._"

    return header + body + footer


# ============================================================
#               FAZ-6 KUPON MOTORU (FAZ-7 ENTEGRE)
# ============================================================

def build_coupon_message(result: dict, max_coupons: int = 3) -> str:
    """
    FAZ-6 motor çıktısından kupon üretir.
    FAZ-7.5 beyni ile:
      - SAFE / BAL / AGG kuponları
      - stake değerleri FAZ-7 çarpanları ile normalizasyon
    """
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

    # FAZ-7.5 beyninden günlük planı al
    plan = faz7_compute_plan(preds)
    brain = plan["brain"]

    safe_x = brain["safe_x"]
    bal_x = brain["bal_x"]
    agg_x = brain["agg_x"]
    mode = brain["mode"]

    # 3 kupon: SAFE, BAL, AGG – basit dağılım
    preds = preds[: max_coupons * 2 + 2]  # biraz esnek
    coupons: List[List[Dict[str, Any]]] = [[], [], []]

    for idx, p in enumerate(preds):
        coupons[idx % 3].append(p)

    names = ["SAFE", "BALANCED", "AGGRESSIVE"]
    multipliers = [safe_x, bal_x, agg_x]

    lines: List[str] = []
    lines.append("💰 *FAZ-7 + FAZ-6 BİRLEŞİK KUPONLAR*")
    lines.append("")
    lines.append(
        f"📊 Ortalama Güven: {plan['today']['avg_conf']:.3f}\n"
        f"📊 Ortalama Edge: {plan['today']['avg_edge']:.3f}\n"
        f"🎛 Günlük Limit (varsayım): 4.0\n"
        f"🤖 Aktif Mod: *{mode}*"
    )
    lines.append("")

    for i, coupon in enumerate(coupons):
        if not coupon:
            continue
        cname = names[i]
        mult = multipliers[i]
        emoji = "🔥"

        lines.append(f"{emoji} *Kupon {i+1} — {cname}*")
        total_stake = 0.0

        for p in coupon:
            base_stake = float(p.get("recommended_stake", 1.0))
            stake = round(base_stake * mult, 2)
            total_stake += stake

            lines.append(
                f"- {p.get('id')} | {p.get('pick')} ({p.get('market')})\n"
                f"  Güven: {p.get('confidence')} | Edge: {p.get('edge')} | Stake: {stake}"
            )

        lines.append(f"💰 Kupon Toplam Stake: {round(total_stake, 2)}")
        lines.append("— — —")

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n… (çıktı kısaltıldı)"
    return text


# ============================================================
#                    FAZ-3 TELEGRAM KOMUTLARI
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🔥 Bot aktif!\n"
        "FAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7.5 bağlı.\n"
        "Komut listesi için /help yaz."
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
/faz6_coupon - FAZ-6 Kupon (FAZ-7.5 beyinli)

/faz7_plan - FAZ-7 Günlük Strateji
/faz7_status - FAZ-7 Hafıza Özeti
"""
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\n"
        "FAZ-4 aktif.\n"
        "FAZ-5 bağlı.\n"
        "FAZ-6 tam online.\n"
        "FAZ-7.5 strateji beyni ve hafıza sistemi çalışıyor."
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
#                    FAZ-6 KUPON (FAZ-7.5 BRAIN)
# ============================================================

@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    result = safe_run_faz6_engine(mode="balance")
    msg = build_coupon_message(result, max_coupons=3)
    bot.reply_to(message, msg, parse_mode="Markdown")


# ============================================================
#                    FAZ-7 KOMUTLARI
# ============================================================

@bot.message_handler(commands=["faz7_plan"])
def faz7_plan_cmd(message):
    # faz6_balance ile aynı Predictions mantığını taklit etmek için
    result = safe_run_faz6_engine(mode="balance")
    body = result.get("result", {})
    preds = body.get("portfolio") or body.get("predictions") or []
    plan = faz7_compute_plan(preds)
    text = _format_faz7_plan_text(plan)
    bot.reply_to(message, text, parse_mode="Markdown")


@bot.message_handler(commands=["faz7_status"])
def faz7_status_cmd(message):
    text = _format_faz7_status_text()
    bot.reply_to(message, text, parse_mode="Markdown")


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
    print("INFO: Bot başlatıldı. Tüm motorlar aktif (FAZ-7.5 Ultra Brain dahil).")

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    start_bot()


if __name__ == "__main__":
    main()
