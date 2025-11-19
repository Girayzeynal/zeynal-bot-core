import sys
import os
import time
import json
from typing import List, Dict, Any
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import deque, defaultdict
import datetime as dt

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
#          FAZ-7 RUNTIME MEMORY + AUTO-WEIGH STRATEJİ
# ============================================================

FAZ7_WINDOW_DAYS = 7
FAZ7_MAX_RUNS = 500
FAZ7_RUN_LOG: deque = deque(maxlen=FAZ7_MAX_RUNS)

SAFE_MODES = {"test", "auto"}
BALANCED_MODES = {"balance", "real"}
AGGRESSIVE_MODES = {"risk", "edge"}


def _faz7_bucket_for_mode(mode: str) -> str:
    m = (mode or "").lower().strip()
    if m in SAFE_MODES:
        return "SAFE"
    if m in BALANCED_MODES:
        return "BAL"
    if m in AGGRESSIVE_MODES:
        return "AGG"
    # default: dengeli
    return "BAL"


def _faz7_register_run(mode: str, engine_result: Dict[str, Any]) -> None:
    """
    Her FAZ-6 çalışmasından sonra:
    - ortalama confidence
    - ortalama edge
    FAZ-7 runtime hafızasına yazılır.
    """
    try:
        now = dt.datetime.utcnow()
        bucket = _faz7_bucket_for_mode(mode)

        result_block = engine_result.get("result", {})
        preds = (
            result_block.get("portfolio")
            or result_block.get("predictions")
            or []
        )

        if not preds:
            avg_conf = 0.0
            avg_edge = 0.0
            count = 0
        else:
            total_conf = 0.0
            total_edge = 0.0
            count = 0
            for p in preds:
                total_conf += float(p.get("confidence", 0.0))
                total_edge += float(p.get("edge", 0.0))
                count += 1

            if count > 0:
                avg_conf = total_conf / count
                avg_edge = total_edge / count
            else:
                avg_conf = 0.0
                avg_edge = 0.0

        FAZ7_RUN_LOG.append(
            {
                "ts": now.isoformat(),
                "mode": mode,
                "bucket": bucket,
                "avg_conf": avg_conf,
                "avg_edge": avg_edge,
                "count": count,
            }
        )
    except Exception as e:
        # FAZ-7 hafıza hiçbir zaman sistemi bozmasın
        print(f"WARNING: FAZ-7 register_run hata: {e!r}")


def faz7_get_recent_stats(days: int = 7) -> Dict[str, Dict[str, float]]:
    """
    Son N gün için SAFE / BAL / AGG özet istatistikleri.
    """
    now = dt.datetime.utcnow()
    cutoff = now - dt.timedelta(days=days)

    agg: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {
            "runs": 0,
            "avg_conf": 0.0,
            "avg_edge": 0.0,
        }
    )

    sums_conf: Dict[str, float] = defaultdict(float)
    sums_edge: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)

    for item in FAZ7_RUN_LOG:
        try:
            ts = dt.datetime.fromisoformat(item["ts"])
        except Exception:
            continue

        if ts < cutoff:
            continue

        bucket = item.get("bucket", "BAL")
        avg_conf = float(item.get("avg_conf", 0.0))
        avg_edge = float(item.get("avg_edge", 0.0))

        sums_conf[bucket] += avg_conf
        sums_edge[bucket] += avg_edge
        counts[bucket] += 1
        agg[bucket]["runs"] += 1

    for bucket in ["SAFE", "BAL", "AGG"]:
        c = counts.get(bucket, 0)
        if c > 0:
            agg[bucket]["avg_conf"] = round(sums_conf[bucket] / c, 3)
            agg[bucket]["avg_edge"] = round(sums_edge[bucket] / c, 4)
        else:
            agg[bucket]["avg_conf"] = 0.0
            agg[bucket]["avg_edge"] = 0.0

    return agg


def faz7_auto_weigh_selector(days: int = 7) -> Dict[str, float]:
    """
    SAFE / BAL / AGG için stake çarpanlarını döner.
    Basit ama stabil bir skor hesabı:
        score = 0.7 * avg_conf + 0.3 * (avg_edge * 30)
    Sonra en iyi bucket +%10, en kötü bucket -%10 alır.
    """
    stats = faz7_get_recent_stats(days)

    # Varsayılan = nötr
    weights = {
        "SAFE": 1.0,
        "BAL": 1.0,
        "AGG": 1.0,
    }

    # Hiç veri yoksa nötr kal
    if not any(stats[b]["runs"] > 0 for b in ["SAFE", "BAL", "AGG"]):
        return weights

    scores = {}
    for bucket in ["SAFE", "BAL", "AGG"]:
        s = stats[bucket]
        # avg_conf ~ 0.5–0.7, avg_edge ~ 0.01–0.05 civarı varsayımı
        score = 0.7 * s["avg_conf"] + 0.3 * (s["avg_edge"] * 30.0)
        scores[bucket] = score

    # En iyi ve en kötü bucket'ı bul
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_bucket, _ = ordered[0]
    worst_bucket, _ = ordered[-1]

    # Hafifçe ağırlık ver
    weights[best_bucket] = 1.10  # +%10
    weights[worst_bucket] = 0.90  # -%10

    # Ortadaki bucket 1.00 civarı kalsın
    for b in ["SAFE", "BAL", "AGG"]:
        weights[b] = round(weights[b], 2)

    return weights


def faz7_build_status_text() -> str:
    """
    /faz7_status çıktısı: son 7 gün + FAZ-7 ağırlıkları.
    """
    stats = faz7_get_recent_stats(FAZ7_WINDOW_DAYS)
    weights = faz7_auto_weigh_selector(FAZ7_WINDOW_DAYS)

    lines = []
    lines.append("🧠 *FAZ-7 HAFIZA ÖZETİ* (Son 7 Gün)\n")

    header = (
        "Mod | Run | Avg Conf | Avg Edge | Stake x\n"
        "----|-----|----------|----------|--------"
    )
    lines.append("```")
    lines.append(header)

    order = [("SAFE", "SAFE"), ("BAL", "BAL"), ("AGG", "AGG")]
    for key, label in order:
        s = stats.get(key, {"runs": 0, "avg_conf": 0.0, "avg_edge": 0.0})
        line = (
            f"{label:4}|"
            f"{s['runs']:4d} |"
            f"{s['avg_conf']:.3f}   |"
            f"{s['avg_edge']:.4f}   |"
            f"{weights.get(key, 1.0):.2f}"
        )
        lines.append(line)

    lines.append("```")
    lines.append(
        "_Not: Stake çarpanları FAZ-7 tarafından son 7 güne göre ayarlanır._"
    )

    return "\n".join(lines)


# ============================================================
#               FAZ-6 KUPON MOTORU (FAZ-7 ENTEGRE)
# ============================================================

def build_coupon_message(result: dict, max_coupons: int = 3) -> str:
    """
    FAZ-6 motor çıktısından kupon mesajı üretir.
    Stake değerlerini FAZ-7 Auto-Weigh ile normalize eder.
    """
    if not isinstance(result, dict):
        return "❌ Kupon üretilemedi (geçersiz sonuç)."

    status = result.get("status", "ok")
    if status != "ok":
        detail = result.get("detail", "Kupon için geçerli sonuç yok.")
        return f"❌ Kupon üretilemedi:\n{detail}"

    mode = (result.get("mode") or "balance").lower().strip()
    bucket = _faz7_bucket_for_mode(mode)

    body = result.get("result", result)
    preds = body.get("portfolio") or body.get("predictions") or []

    if not preds:
        return "❌ Kupon üretilemedi: uygun tahmin bulunamadı."

    # FAZ-7 stake çarpanlarını al
    weights = faz7_auto_weigh_selector(FAZ7_WINDOW_DAYS)
    factor = weights.get(bucket, 1.0)

    # Tahminleri bölüştür
    per_coupon = max(1, len(preds) // max_coupons or 1)

    coupons = []
    for i in range(0, len(preds), per_coupon):
        coupons.append(preds[i:i + per_coupon])
        if len(coupons) >= max_coupons:
            break

    text = (
        "💵 *FAZ-6 Kupon Önerileri*\n"
        f"🤖 FAZ-7 Modu: {bucket} (stake x{factor:.2f})\n\n"
    )

    for idx, coupon in enumerate(coupons, start=1):
        text += f"🎟 Kupon {idx}\n"
        total_stake = 0.0

        for p in coupon:
            sel = p.get("pick") or p.get("selection") or "N/A"
            market = p.get("market", "")
            conf = float(p.get("confidence", p.get("conf", 0)))
            edge = float(p.get("edge", 0))
            match_id = p.get("id", p.get("match", "?"))

            base_stake = float(p.get("recommended_stake", 1.0))
            stake = round(base_stake * factor, 2)
            total_stake += stake

            text += (
                f"• {match_id} → {sel} ({market})\n"
                f"  Güven: {conf:.2f} | Edge: {edge:.3f} | Stake: {stake}\n"
            )

        text += f"💰 Kupon Toplam Stake: {round(total_stake, 2)}\n"
        text += "— — —\n"

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
/faz6_coupon - FAZ-6 Kupon (FAZ-7 stake x)

/faz7_status - FAZ-7 hafıza + stake çarpanları
"""
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\nFAZ-4 aktif.\nFAZ-5 bağlı.\nFAZ-6 online.\nFAZ-7 hafıza ve stake ayarlayıcı aktif."
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
    """
    Her türlü hatayı yakalayıp anlamlı dict dönen güvenli wrapper.
    Aynı zamanda FAZ-7 hafızasını besler.
    """
    mode_norm = (mode or "auto").lower().strip()

    try:
        result = _raw_run_faz6_engine(mode=mode_norm)

        if not isinstance(result, dict):
            wrapped = {
                "status": "error",
                "mode": mode_norm,
                "detail": f"Motor beklenmeyen tip döndürdü: {type(result).__name__}",
                "raw": result,
            }
            _faz7_register_run(mode_norm, wrapped)
            return wrapped

        if "status" not in result:
            result = {"status": "ok", "mode": mode_norm, **result}
        else:
            if "mode" not in result:
                result["mode"] = mode_norm

        _faz7_register_run(mode_norm, result)
        return result

    except Exception as e:
        err = {
            "status": "error",
            "mode": mode_norm,
            "detail": f"FAZ-6 motor exception: {repr(e)}",
        }
        _faz7_register_run(mode_norm, err)
        return err


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
#                  FAZ-7 STATUS KOMUTU
# ============================================================

@bot.message_handler(commands=["faz7_status"])
def faz7_status_cmd(message):
    text = faz7_build_status_text()
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
    print("INFO: Bot başlatıldı. Tüm motorlar aktif (FAZ-3..FAZ-7).")

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    start_bot()


if __name__ == "__main__":
    main()
