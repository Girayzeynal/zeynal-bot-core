import os
import json
import time
import logging
import re

import telebot
from telebot.apihelper import ApiException
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
    parse_mode="HTML",              # 🔴 Markdown yok, HTML güvenli
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
# 🛡 FAZ-8 ULTIMATE OUTPUT SHIELD
#   - HTML / emoji / uzun mesaj / 4096 limit koruması
#   - Tüm cevaplar faz8_safe_reply / faz8_safe_send üzerinden gider
# ================================================================
MAX_TG_LEN = 3900  # Telegram 4096 sınırı için güvenli buffer
HTML_TAG_RE = re.compile(r"<[^>]+>")

def strip_html_tags(text: str) -> str:
    return HTML_TAG_RE.sub("", text or "")


def chunk_text(text: str, max_len: int = MAX_TG_LEN):
    """
    Mesajı Telegram limitine göre parçalara böler.
    Önce satır bazlı, satır çok uzunsa hard-cut.
    """
    if not isinstance(text, str):
        text = str(text)

    parts = []
    current = ""

    for line in text.splitlines(keepends=True):
        # Tek satır bile çok uzunsa parçalara ayrılır
        while len(line) > max_len:
            parts.append(line[:max_len])
            line = line[max_len:]
        if len(current) + len(line) > max_len:
            if current:
                parts.append(current)
            current = line
        else:
            current += line

    if current:
        parts.append(current)

    if not parts:
        parts = [""]

    return parts


def faz8_safe_send(chat_id: int, text: str, reply_to_message_id: int | None = None):
    """
    Bütün gönderimler buradan geçer.
    1) HTML parse deneyip hata alırsa
    2) HTML tag'lerini strip edip plain text yollar
    3) O da patlarsa kısa uyarı mesajı yollar
    """
    text = text or ""
    chunks = chunk_text(text, MAX_TG_LEN)
    last_msg = None

    for idx, chunk in enumerate(chunks):
        reply_id = reply_to_message_id if idx == 0 else None

        try:
            last_msg = bot.send_message(
                chat_id,
                chunk,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_to_message_id=reply_id,
            )
        except ApiException as e:
            log.warning(f"[FAZ-8] HTML gönderim hatası, plain text'e düşüyor: {e}")
            safe_chunk = strip_html_tags(chunk)
            try:
                last_msg = bot.send_message(
                    chat_id,
                    safe_chunk,
                    parse_mode=None,
                    disable_web_page_preview=True,
                    reply_to_message_id=reply_id,
                )
            except Exception as e2:
                log.error(f"[FAZ-8] Mesaj gönderilemedi: {e2}")
                try:
                    last_msg = bot.send_message(
                        chat_id,
                        "⚠️ Mesaj çok uzun veya format hatası nedeniyle kısaltıldı.",
                        parse_mode=None,
                        disable_web_page_preview=True,
                        reply_to_message_id=reply_id,
                    )
                except Exception as e3:
                    log.error(f"[FAZ-8] Fallback bile gönderilemedi: {e3}")
                break
        except Exception as e:
            log.error(f"[FAZ-8] Beklenmeyen send hatası: {e}")
            break

    return last_msg


def faz8_safe_reply(message, text: str):
    return faz8_safe_send(message.chat.id, text, reply_to_message_id=message.message_id)


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

    avg_conf = df["conf"].mean()
    avg_edge = df["edge"].mean()

    # basit linear regression slope
    slope = float(np.polyfit(df["t"], df["conf"], 1)[0])

    if slope > 0.01:
        trend = "UP"
    elif slope < -0.01:
        trend = "DOWN"
    else:
        trend = "FLAT"

    vol = float(df["conf"].std() if len(df) > 1 else 0.0)

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
# 🧠 FAZ-7.9 KOMUTLARI
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

    faz8_safe_reply(message, msg)


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

    faz8_safe_reply(message, msg)


@bot.message_handler(commands=["faz7_register"])
def faz7_register_cmd(message):
    """
    Kullanım: /faz7_register 0.65 0.04
    """
    try:
        parts = message.text.split()
        if len(parts) != 3:
            faz8_safe_reply(
                message,
                "✅ Kullanım: <code>/faz7_register conf edge</code>\n"
                "Örn: <code>/faz7_register 0.62 0.035</code>"
            )
            return

        conf = float(parts[1])
        edge = float(parts[2])

        register_daily_stats(conf, edge)
        info = faz79_brain()

        faz8_safe_reply(
            message,
            (
                "✅ Günlük FAZ-7.9 kaydı alındı.\n\n"
                f"conf={conf:.3f}, edge={edge:.3f}\n"
                f"Yeni Mod: <b>{info['mode']}</b>\n"
                f"Trend: {info['trend']} (slope {info['slope']})"
            )
        )
    except Exception as e:
        faz8_safe_reply(message, f"❌ Kayıt hatası: {e}")


# ================================================================
# 🏀 FAZ-6 – BASİT KUPON & SİMÜLASYON
#    (Eski screenshot'taki çıktıya benzer, HTML-safe)
# ================================================================
def build_faz6_coupons_text():
    return (
        "🔥 <b>FAZ-6 KUPONLARI (4-Seviyeli AI Dağılım)</b>\n\n"

        "🔥 <b>Kupon 1 — SAFE</b>\n"
        "- EL:EFES@REAL | REAL MADRID -5.5 (spread)\n"
        "  Güven: 0.66 | Edge: 0.045 | Stake: 0.88\n"
        "- EL:FENER@OLY | OLYMPIACOS -3.5 (spread)\n"
        "  Güven: 0.64 | Edge: 0.041 | Stake: 0.84\n"
        "💰 Toplam Stake: 1.72\n"
        "— — —\n\n"

        "🔥 <b>Kupon 2 — BALANCED</b>\n"
        "- NBA:BOS@MIA | UNDER 224.5 (total)\n"
        "  Güven: 0.63 | Edge: 0.036 | Stake: 0.80\n"
        "- NBA:LAL@DEN | DEN -4.5 (spread)\n"
        "  Güven: 0.61 | Edge: 0.032 | Stake: 0.76\n"
        "💰 Toplam Stake: 1.56\n"
        "— — —\n\n"

        "🔥 <b>Kupon 3 — AGGRESSIVE</b>\n"
        "- NBA:CHI@NYK | NYK ML (moneyline)\n"
        "  Güven: 0.60 | Edge: 0.031 | Stake: 0.75\n"
        "💰 Toplam Stake: 0.75\n"
        "— — —\n\n"

        "🔥 <b>Kupon 4 — ULTRA</b>\n"
        "- NBA:GSW@PHX | OVER 230.5 (total)\n"
        "  Güven: 0.59 | Edge: 0.028 | Stake: 0.73\n"
        "💰 Toplam Stake: 0.73\n"
    )


@bot.message_handler(commands=["faz6_coupon"])
def faz6_coupon(message):
    faz8_safe_reply(message, build_faz6_coupons_text())


def build_nba_simulation_text():
    """
    Daha sonra gerçek veriyle beslenecek.
    Şimdilik screenshot'taki stabil örneği HTML formatında dönüyoruz.
    """
    home = "MIA"
    away = "NYK"
    skor = 104
    tempo = 98.8
    pace = 98.8
    win_team = home
    win_prob = 0.50

    return (
        "🏀 <b>NBA Simülasyon Sonuçları</b>\n\n"
        f"🏠 {home} vs ✈️ {away}\n"
        f"📈 Tahmini Skor: <b>{skor}</b>\n"
        f"⏱ Tempo: <b>{tempo}</b>\n"
        f"🎯 Kazanan: <b>{win_team}</b> ({int(win_prob * 100)}%)\n\n"
        "🧠 <b>Ham Analiz</b>:\n"
        "🔥 <b>NBA – Canlı Maçlar</b>\n"
        f"🏀 {home} (54) – {away} (50)\n"
        f"⏱ Pace Tahmini: <b>{pace}</b>"
    )


@bot.message_handler(commands=["simulate_nba"])
def cmd_simulate_nba(message):
    try:
        faz8_safe_reply(message, "🏀 Simülasyon başlatılıyor...")
        text = build_nba_simulation_text()
        faz8_safe_reply(message, text)
    except Exception as e:
        faz8_safe_reply(message, f"❌ Simülasyon hatası: {e}")


# Basit FAZ-6 placeholder komutları (şimdilik)
@bot.message_handler(commands=["faz6_test"])
def faz6_test(message):
    faz8_safe_reply(message, "🧪 FAZ-6 Test modu placeholder.")


@bot.message_handler(commands=["faz6_auto"])
def faz6_auto(message):
    faz8_safe_reply(message, "🤖 FAZ-6 Auto modu placeholder.")


@bot.message_handler(commands=["faz6_risk"])
def faz6_risk(message):
    faz8_safe_reply(message, "⚠️ FAZ-6 Risk modu placeholder.")


@bot.message_handler(commands=["faz6_edge"])
def faz6_edge(message):
    faz8_safe_reply(message, "📐 FAZ-6 Edge modu placeholder.")


@bot.message_handler(commands=["faz6_real"])
def faz6_real(message):
    faz8_safe_reply(message, "📊 FAZ-6 Real modu placeholder.")


@bot.message_handler(commands=["faz6_balance"])
def faz6_balance(message):
    faz8_safe_reply(message, "⚖️ FAZ-6 Balance modu placeholder.")


# ================================================================
# 🧰 GENEL KOMUTLAR (/start, /help, /status)
# ================================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    text = (
        "🔥 <b>Bot aktif!</b>\n"
        "FAZ-4 + FAZ-5 + FAZ-6 + FAZ-7.9 + FAZ-8 OUTPUT SHIELD bağlı.\n"
        "Komut listesi için <code>/help</code> yaz."
    )
    faz8_safe_reply(message, text)


@bot.message_handler(commands=["help"])
def cmd_help(message):
    text = (
        "📌 <b>Komutlar</b>:\n\n"
        "/start - Botu başlatır\n"
        "/help - Komut listesi\n"
        "/status - Sistem durumu\n\n"
        "/simulate_nba - NBA canlı simülasyon\n\n"
        "— <b>FAZ-6</b> —\n"
        "/faz6_test - FAZ-6 Test\n"
        "/faz6_auto - FAZ-6 Auto\n"
        "/faz6_risk - FAZ-6 Risk\n"
        "/faz6_edge - FAZ-6 Edge\n"
        "/faz6_real - FAZ-6 Real\n"
        "/faz6_balance - FAZ-6 Balance\n"
        "/faz6_coupon - FAZ-6 Kupon\n\n"
        "— <b>FAZ-7.9</b> —\n"
        "/faz7_status - FAZ-7.9 hafıza özeti\n"
        "/faz7_plan - FAZ-7.9 strateji planı\n"
        "/faz7_register - Günlük conf & edge kaydı\n"
    )
    faz8_safe_reply(message, text)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    info = faz79_brain()
    text = (
        "✅ Bot çalışıyor.\n"
        "Mod: <b>Fly.io + Webhook + Flask</b>\n"
        "FAZ-7.9 hafıza motoru: <b>AKTİF</b>\n"
        "Simülasyon motoru: <b>AKTİF</b>\n"
        "FAZ-8 OUTPUT SHIELD: <b>AKTİF</b>\n\n"
        f"Son Mod: <b>{info['mode']}</b>, conf={info['conf']}, edge={info['edge']}"
    )
    faz8_safe_reply(message, text)


# ================================================================
# 🚀 STARTUP: WEBHOOK AYARLA & FLASK ÇALIŞTIR
# ================================================================
def setup_webhook(max_retries: int = 3, base_delay: float = 2.0):
    """
    FAZ-8.3 – Webhook Auto-Retry Shield
    - Eski webhook'u sil
    - max_retries defa dene
    - Her denemede gecikmeyi arttır
    """
    try:
        log.info("Eski webhook kaldırılıyor...")
        bot.delete_webhook()
    except Exception as e:
        log.warning(f"Eski webhook silinirken hata (önemli değil): {e}")

    if not WEBHOOK_URL:
        log.warning("WEBHOOK_URL tanımlı değil, webhook set edilmedi!")
        return

    for attempt in range(1, max_retries + 1):
        try:
            log.info(f"[FAZ-8.3] Webhook deneme {attempt}: {WEBHOOK_URL}")
            bot.set_webhook(url=WEBHOOK_URL)
            log.info("[FAZ-8.3] Webhook başarıyla set edildi.")
            return
        except Exception as e:
            log.error(f"[FAZ-8.3] Webhook set hatası (attempt {attempt}): {e}")
            time.sleep(base_delay * attempt)

    log.error("[FAZ-8.3] Webhook set edilemedi, artık retry yok.")


if __name__ == "__main__":
    init_memory()
    setup_webhook()
    port = int(os.getenv("PORT", 8080))
    log.info(f"Flask HTTP server 0.0.0.0:{port} üzerinde çalışıyor.")
    app.run(host="0.0.0.0", port=port)
