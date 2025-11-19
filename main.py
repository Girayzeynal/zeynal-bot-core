import sys
import os
import time
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional
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

FAZ7_MEMORY_FILE = "faz7_memory.json"


# ============================================================
#                      YARDIMCI FONKSİYONLAR
# ============================================================

def _today_key() -> str:
    """UTC tarih anahtarı (günlük log için)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_faz7_memory() -> Dict[str, Any]:
    """FAZ-7 günlük hafıza dosyasını oku."""
    if not os.path.exists(FAZ7_MEMORY_FILE):
        return {"history": {}, "last_updated": None}
    try:
        with open(FAZ7_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"history": {}, "last_updated": None}
        data.setdefault("history", {})
        return data
    except Exception as e:
        print(f"WARN: FAZ-7 memory read failed: {e!r}")
        return {"history": {}, "last_updated": None}


def _save_faz7_memory(mem: Dict[str, Any]) -> None:
    """FAZ-7 günlük hafızasını diske yaz."""
    try:
        mem["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(FAZ7_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"WARN: FAZ-7 memory write failed: {e!r}")


def _update_faz7_memory(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Günlük planı hafızaya işler.
    Geriye varsa 'dünkü plan'ı döndürür (karşılaştırma için).
    """
    mem = _load_faz7_memory()
    history: Dict[str, Any] = mem.setdefault("history", {})

    today = _today_key()
    # Düne ait kaydı bul (bugünden önceki en büyük tarih)
    yesterday_entry = None
    if history:
        prev_dates = [d for d in history.keys() if d < today]
        if prev_dates:
            prev_key = sorted(prev_dates)[-1]
            yesterday_entry = history.get(prev_key)

    # Bugünün kaydını yaz
    history[today] = {
        "date": today,
        "avg_confidence": plan.get("avg_confidence"),
        "avg_edge": plan.get("avg_edge"),
        "daily_limit": plan.get("daily_limit"),
        "stake_normalize": plan.get("stake_normalize"),
        "levels": plan.get("levels", {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    _save_faz7_memory(mem)
    return yesterday_entry


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
#               FAZ-6 KUPON MOTORU (ANA)
# ============================================================

def _split_by_level(preds: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Tahminleri güven/edge seviyesine göre 4 levele ayır.
    SAFE / BALANCED / AGGRESSIVE / ULTRA
    """
    buckets = {"SAFE": [], "BALANCED": [], "AGGRESSIVE": [], "ULTRA": []}
    for p in preds:
        c = float(p.get("confidence", 0.0))
        e = float(p.get("edge", 0.0))

        if c >= 0.66 and e >= 0.040:
            buckets["ULTRA"].append(p)
        elif c >= 0.62 and e >= 0.034:
            buckets["AGGRESSIVE"].append(p)
        elif c >= 0.60 and e >= 0.030:
            buckets["BALANCED"].append(p)
        elif c >= 0.56 and e >= 0.024:
            buckets["SAFE"].append(p)
        else:
            # çok zayıfsa hiçbir levele girmesin
            pass

    return buckets


def compute_faz7_plan(
    preds: List[Dict[str, Any]],
    update_memory: bool = True,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    FAZ-7 günlük strateji beyni:
    - ortalama güven / edge
    - günlük limit
    - stake normalize çarpanı
    - hangi seviyeler açık
    - Daily Memory Log entegrasyonu
    """
    if not preds:
        plan = {
            "avg_confidence": 0.0,
            "avg_edge": 0.0,
            "daily_limit": 0.0,
            "stake_normalize": 1.0,
            "levels": {
                "SAFE": False,
                "BALANCED": False,
                "AGGRESSIVE": False,
                "ULTRA": False,
            },
        }
        yesterday = _update_faz7_memory(plan) if update_memory else None
        return plan, yesterday

    avg_conf = sum(float(p.get("confidence", 0.0)) for p in preds) / len(preds)
    avg_edge = sum(float(p.get("edge", 0.0)) for p in preds) / len(preds)

    # Günlük maksimum kupon sayısı (kabaca).
    daily_limit = 4.0

    # Stake normalizasyonu:
    # 0.8 taban + (conf-0.60)*1 + (edge-0.03)*5, 0.5–1.3 aralığına clamp.
    raw_norm = 0.8 + (avg_conf - 0.60) + (avg_edge - 0.03) * 5.0
    stake_normalize = max(0.5, min(1.3, raw_norm))

    # Seviye açma/kapama:
    levels = {
        "SAFE": avg_conf >= 0.55 and avg_edge >= 0.020,
        "BALANCED": avg_conf >= 0.60 and avg_edge >= 0.030,
        "AGGRESSIVE": avg_conf >= 0.62 and avg_edge >= 0.034,
        "ULTRA": avg_conf >= 0.66 and avg_edge >= 0.040,
    }

    # ULTRA'yı şimdilik kapalı tutmak için zorunlu override:
    levels["ULTRA"] = False

    plan = {
        "avg_confidence": round(avg_conf, 3),
        "avg_edge": round(avg_edge, 3),
        "daily_limit": round(daily_limit, 1),
        "stake_normalize": round(stake_normalize, 2),
        "levels": levels,
    }

    yesterday = _update_faz7_memory(plan) if update_memory else None
    return plan, yesterday


def build_coupon_message_with_faz7(
    engine_result: Dict[str, Any],
    max_coupons: int = 4,
) -> str:
    """
    FAZ-6 motor çıktısı + FAZ-7 strateji beynini kullanarak
    SAFE / BALANCED / AGGRESSIVE kuponları üretir.
    ULTRA şimdilik otomatik kapalı.
    """
    status = engine_result.get("status", "ok")
    if status != "ok":
        detail = engine_result.get("detail", "Bilinmeyen hata")
        return f"❌ *FAZ-6/FAZ-7 KUPON HATASI*\n{detail}"

    body = engine_result.get("result", engine_result)
    preds: List[Dict[str, Any]] = (
        body.get("portfolio")
        or body.get("predictions")
        or []
    )
    if not preds:
        return "⚠ Kupon oluşturmak için yeterli maç bulunamadı."

    # FAZ-7 planını hesapla + memorize et
    plan, _ = compute_faz7_plan(preds, update_memory=True)

    buckets = _split_by_level(preds)
    levels = plan["levels"]
    norm = plan["stake_normalize"]

    coupons: List[Tuple[str, List[Dict[str, Any]]]] = []

    if levels.get("SAFE"):
        coupons.append(("SAFE", buckets.get("SAFE", [])))
    if levels.get("BALANCED"):
        coupons.append(("BALANCED", buckets.get("BALANCED", [])))
    if levels.get("AGGRESSIVE"):
        coupons.append(("AGGRESSIVE", buckets.get("AGGRESSIVE", [])))
    # ULTRA bilinçli kapalı

    # Boş level'ları at
    coupons = [(name, c) for name, c in coupons if c]
    coupons = coupons[:max_coupons]

    if not coupons:
        return "⚠ FAZ-7 filtresinden sonra oynanabilir kupon kalmadı."

    lines: List[str] = []
    lines.append("💰 *FAZ-7 + FAZ-6 BİRLEŞİK KUPONLAR*\n")
    lines.append(
        f"📊 Ortalama Güven: {plan['avg_confidence']}\n"
        f"📊 Ortalama Edge: {plan['avg_edge']}\n"
        f"🧱 Günlük Limit: {plan['daily_limit']}\n"
        f"🪙 Stake Normalize: {plan['stake_normalize']}x\n"
        ""
    )

    for idx, (name, coupon) in enumerate(coupons, start=1):
        if not coupon:
            continue
        lines.append(f"🔥 Kupon {idx} — {name}")
        total_stake = 0.0
        for p in coupon:
            stake_raw = float(p.get("recommended_stake", 1.0))
            stake = round(stake_raw * norm, 2)
            total_stake += stake
            lines.append(
                f"- {p.get('id')} | {p.get('pick')} ({p.get('market')})\n"
                f"  Güven: {p.get('confidence')} | "
                f"Edge: {p.get('edge')} | "
                f"Stake: {stake}"
            )
        lines.append(f"💵 Toplam Stake: {round(total_stake, 2)}\n")

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
        "🔥 Bot aktif!\nFAZ-3 + FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7 bağlı.\n"
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
/faz6_coupon - FAZ-6 Kupon (FAZ-7 entegrasyonlu)

/faz7_plan - FAZ-7 Günlük Strateji & Dün/Bugün karşılaştırma
"""
    )


@bot.message_handler(commands=["status"])
def status_cmd(message):
    bot.reply_to(
        message,
        "🟢 Sistem stabil.\n"
        "FAZ-4 aktif.\n"
        "FAZ-5 bağlı.\n"
        "FAZ-6 + FAZ-7 tam online."
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
#                    FAZ-6 KUPON (FAZ-7 ENTEGRE)
# ============================================================

@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon_cmd(message):
    result = safe_run_faz6_engine(mode="balance")
    msg = build_coupon_message_with_faz7(result, max_coupons=4)
    bot.reply_to(message, msg, parse_mode="Markdown")


# ============================================================
#                    FAZ-7 GÜNLÜK STRATEJİ
# ============================================================

@bot.message_handler(commands=["faz7_plan"])
def faz7_plan_cmd(message):
    # Güncel FAZ-6 çıktısını çek
    result = safe_run_faz6_engine(mode="balance")
    body = result.get("result", result)
    preds: List[Dict[str, Any]] = (
        body.get("portfolio")
        or body.get("predictions")
        or []
    )

    plan, yesterday = compute_faz7_plan(preds, update_memory=True)

    text_lines = []
    text_lines.append("🧠 *FAZ-7 Günlük Strateji*\n")
    text_lines.append(
        f"📊 Ortalama Güven: {plan['avg_confidence']}\n"
        f"📊 Ortalama Edge: {plan['avg_edge']}\n"
        f"🎯 Günlük Limit: {plan['daily_limit']}\n"
        f"🪙 Stake Normalize: {plan['stake_normalize']}x\n"
    )

    levels = plan["levels"]
    text_lines.append("🎛 Oynanacak Seviye:")
    text_lines.append(f"• SAFE: {levels['SAFE']}")
    text_lines.append(f"• BALANCED: {levels['BALANCED']}")
    text_lines.append(f"• AGGRESSIVE: {levels['AGGRESSIVE']}")
    text_lines.append(f"• ULTRA: {levels['ULTRA']}\n")

    # Dün / Bugün karşılaştırma (Daily Memory Log)
    if yesterday:
        try:
            yc = float(yesterday.get("avg_confidence", 0.0))
            ye = float(yesterday.get("avg_edge", 0.0))
            yn = float(yesterday.get("stake_normalize", 1.0))

            dc = round(plan["avg_confidence"] - yc, 3)
            de = round(plan["avg_edge"] - ye, 3)
            dn = round(plan["stake_normalize"] - yn, 2)

            def _sign(x: float) -> str:
                return f"+{x}" if x > 0 else str(x)

            text_lines.append("📆 Dün/Bugün Karşılaştırma:")
            text_lines.append(
                f"• Güven: {yc} → {plan['avg_confidence']} ({_sign(dc)})"
            )
            text_lines.append(
                f"• Edge: {ye} → {plan['avg_edge']} ({_sign(de)})"
            )
            text_lines.append(
                f"• Normalize: {yn}x → {plan['stake_normalize']}x ({_sign(dn)})"
            )
        except Exception as e:
            text_lines.append(
                f"ℹ Karşılaştırma okunamadı (log hatası: {e!r})"
            )
    else:
        text_lines.append(
            "📆 Dün için kayıt bulunamadı (ya ilk gün ya da hafıza sıfırlanmış)."
        )

    msg = "\n".join(text_lines)
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
    print("INFO: Bot başlatıldı. Tüm motorlar aktif (FAZ-3→7).")

    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    heartbeat_thread = Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    start_bot()


if __name__ == "__main__":
    main()
