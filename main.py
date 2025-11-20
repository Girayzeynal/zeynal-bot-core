import os
import json
import logging
import threading
from datetime import datetime, date
from statistics import mean, pstdev

from flask import Flask
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext

# -------------------------------------------------
#  Genel Ayarlar
# -------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
if not TELEGRAM_TOKEN:
    logger.warning("TELEGRAM_TOKEN env değişkeni tanımlı değil!")

MEMORY_FILE = "faz7_memory.json"  # FAZ-7.9 hafıza dosyası

# -------------------------------------------------
#  ÖRNEK FAZ-6 MAÇ DATASI
#  (Eski engine yerine placeholder. İstersen burayı
#   kendi data_fetcher / faz6_engine çıktınla değiştirebilirsin.)
# -------------------------------------------------

SAMPLE_MATCHES = [
    {
        "id": "EL:EFES@REAL",
        "league": "EL",
        "match": "EL:EFES@REAL",
        "pick": "REAL MADRID -5.5",
        "pick_type": "spread",
        "confidence": 0.66,
        "edge": 0.045,
        "base_stake": 0.80,
    },
    {
        "id": "EL:FENER@OLY",
        "league": "EL",
        "match": "EL:FENER@OLY",
        "pick": "OLYMPIACOS -3.5",
        "pick_type": "spread",
        "confidence": 0.64,
        "edge": 0.041,
        "base_stake": 0.76,
    },
    {
        "id": "NBA:BOS@MIA",
        "league": "NBA",
        "match": "NBA:BOS@MIA",
        "pick": "UNDER 224.5",
        "pick_type": "total",
        "confidence": 0.63,
        "edge": 0.036,
        "base_stake": 0.73,
    },
    {
        "id": "NBA:LAL@DEN",
        "league": "NBA",
        "match": "NBA:LAL@DEN",
        "pick": "DEN -4.5",
        "pick_type": "spread",
        "confidence": 0.61,
        "edge": 0.032,
        "base_stake": 0.70,
    },
    {
        "id": "NBA:CHI@NYK",
        "league": "NBA",
        "match": "NBA:CHI@NYK",
        "pick": "NYK ML",
        "pick_type": "moneyline",
        "confidence": 0.60,
        "edge": 0.031,
        "base_stake": 0.69,
    },
    {
        "id": "NBA:GSW@PHX",
        "league": "NBA",
        "match": "NBA:GSW@PHX",
        "pick": "OVER 230.5",
        "pick_type": "total",
        "confidence": 0.59,
        "edge": 0.028,
        "base_stake": 0.67,
    },
]


# -------------------------------------------------
#  FAZ-7.9 HAFIZA YARDIMCI FONKSİYONLARI
# -------------------------------------------------


def load_memory():
    """faz7_memory.json dosyasını yükle."""
    if not os.path.exists(MEMORY_FILE):
        return {"days": []}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "days" not in data or not isinstance(data["days"], list):
            return {"days": []}
        return data
    except Exception as e:
        logger.error("Hafıza yüklenirken hata: %s", e)
        return {"days": []}


def save_memory(memory):
    """Hafızayı dosyaya yaz."""
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Hafıza kaydedilirken hata: %s", e)


def compute_today_stats(matches):
    """Günün maçlarından FAZ-7 için ortalama güven ve edge hesapla."""
    if not matches:
        return {
            "date": date.today().isoformat(),
            "matches": 0,
            "avg_conf": 0.0,
            "avg_edge": 0.0,
            "mode": "BAL",
        }

    avg_conf = mean(m["confidence"] for m in matches)
    avg_edge = mean(m["edge"] for m in matches)
    return {
        "date": date.today().isoformat(),
        "matches": len(matches),
        "avg_conf": round(avg_conf, 3),
        "avg_edge": round(avg_edge, 3),
        "mode": "BAL",  # şimdilik varsayılan
    }


def update_memory_with_today(memory, today_stats):
    """Bugünün verisini hafızaya ekle / güncelle (maks 7 gün tut)."""
    days = memory.get("days", [])
    today_str = today_stats["date"]

    # Aynı gün varsa güncelle
    for d in days:
        if d["date"] == today_str:
            d.update(today_stats)
            break
    else:
        # Yeni gün ekle
        days.append(today_stats)

    # Eski günleri at (son 7 gün)
    days = sorted(days, key=lambda x: x["date"])[-7:]
    memory["days"] = days
    return memory


def summarize_last_7_days(memory):
    """Son 7 günün ortalama conf/edge + mod dağılımını hesapla."""
    days = memory.get("days", [])
    if not days:
        return {
            "avg_conf_7g": 0.0,
            "avg_edge_7g": 0.0,
            "mode_counts": {"SAFE": 0, "BAL": 0, "AGG": 0},
            "volatility_conf": 0.0,
            "volatility_edge": 0.0,
            "trend_slope": 0.0,
        }

    avg_conf_7g = mean(d["avg_conf"] for d in days)
    avg_edge_7g = mean(d["avg_edge"] for d in days)

    # Mod sayaçları (şimdilik sadece BAL kullanıyoruz ama yapı hazır)
    mode_counts = {"SAFE": 0, "BAL": 0, "AGG": 0}
    for d in days:
        mode = d.get("mode", "BAL").upper()
        if mode in mode_counts:
            mode_counts[mode] += 1

    # Volatilite (standart sapma)
    if len(days) >= 2:
        volatility_conf = pstdev(d["avg_conf"] for d in days)
        volatility_edge = pstdev(d["avg_edge"] for d in days)
    else:
        volatility_conf = 0.0
        volatility_edge = 0.0

    # Basit trend (conf için ilk-son farkına göre slope)
    if len(days) >= 2:
        first = days[0]["avg_conf"]
        last = days[-1]["avg_conf"]
        trend_slope = (last - first) / (len(days) - 1)
    else:
        trend_slope = 0.0

    return {
        "avg_conf_7g": round(avg_conf_7g, 3),
        "avg_edge_7g": round(avg_edge_7g, 3),
        "mode_counts": mode_counts,
        "volatility_conf": round(volatility_conf, 3),
        "volatility_edge": round(volatility_edge, 3),
        "trend_slope": round(trend_slope, 4),
    }


def decide_faz79_strategy(today_stats, summary_7g):
    """
    FAZ-7.9 strateji beyninin karar mantığı.

    Çıktı:
      {
        "mode": "SAFE" | "BAL" | "AGG",
        "stake_normalize": float,
        "level_flags": {"SAFE": bool, "BAL": bool, "AGG": bool},
        "stake_multipliers": {"SAFE": float, "BAL": float, "AGG": float},
    }
    """
    avg_conf_7g = summary_7g["avg_conf_7g"]
    avg_edge_7g = summary_7g["avg_edge_7g"]
    vol_conf = summary_7g["volatility_conf"]
    trend = summary_7g["trend_slope"]

    # Başlangıç varsayılanları
    stake_normalize = 1.0
    level_flags = {"SAFE": False, "BAL": False, "AGG": False}
    stake_multipliers = {"SAFE": 1.0, "BAL": 1.0, "AGG": 0.9}
    mode = "BAL"

    # 1) Hafıza boşsa INIT
    if avg_conf_7g == 0.0 and avg_edge_7g == 0.0:
        # INIT modu: sadece BAL açık, stake 1.0
        level_flags["BAL"] = True
        stake_normalize = 1.0
        mode = "BAL"
        return {
            "mode": mode,
            "stake_normalize": stake_normalize,
            "level_flags": level_flags,
            "stake_multipliers": stake_multipliers,
        }

    # 2) Güven yüksek ve volatilite düşük: SAFE + BAL açık
    if avg_conf_7g >= 0.62 and vol_conf < 0.01 and abs(trend) < 0.002:
        level_flags["SAFE"] = True
        level_flags["BAL"] = True
        level_flags["AGG"] = False
        stake_normalize = 0.90  # örnek: hafif korumacı
        mode = "BAL"

    # 3) Güven orta, volatilite orta: sadece BAL açık
    elif avg_conf_7g >= 0.58:
        level_flags["SAFE"] = False
        level_flags["BAL"] = True
        level_flags["AGG"] = False
        stake_normalize = 0.95
        mode = "BAL"

    # 4) Güven düşük veya volatilite yüksek: sadece SAFE
    else:
        level_flags["SAFE"] = True
        level_flags["BAL"] = False
        level_flags["AGG"] = False
        stake_normalize = 0.80
        mode = "SAFE"

    return {
        "mode": mode,
        "stake_normalize": stake_normalize,
        "level_flags": level_flags,
        "stake_multipliers": stake_multipliers,
    }


# -------------------------------------------------
#  FORMATLAYICI FONKSİYONLAR
# -------------------------------------------------


def format_faz6_auto(matches):
    lines = ["🧠 FAZ-6 AUTO SONUCU"]
    for m in matches:
        lines.append(f"📌 {m['match']}")
        if m["pick_type"] == "total":
            pick_str = f"{m['pick']} (total)"
        elif m["pick_type"] == "moneyline":
            pick_str = f"{m['pick']} (moneyline)"
        else:
            pick_str = f"{m['pick']} (spread)"
        lines.append(f"🎯 {pick_str}")
        lines.append(
            f"📈 Güven: {m['confidence']:.2f} | Edge: {m['edge']:.3f} | Stake: {m['base_stake']:.2f}"
        )
        lines.append("— — —")
    return "\n".join(lines)


def format_faz6_coupons(matches, strategy, summary_7g):
    """
    FAZ-7.9 + FAZ-6 birleşik kupon mesajı.
    3 kupon: SAFE, BALANCED, AGGRESSIVE (içerikleri sabit segmentlenmiş).
    """
    avg_conf_7g = summary_7g["avg_conf_7g"]
    avg_edge_7g = summary_7g["avg_edge_7g"]
    stake_norm = strategy["stake_normalize"]
    active_mode = strategy["mode"]
    level_flags = strategy["level_flags"]
    stake_mult = strategy["stake_multipliers"]

    daily_limit = 4.0  # şimdilik sabit

    header_lines = [
        "💰 FAZ-7 + FAZ-6 BİRLEŞİK KUPONLAR",
        f"📊 Ortalama Güven (7g): {avg_conf_7g:.3f}",
        f"📊 Ortalama Edge (7g): {avg_edge_7g:.3f}",
        f"📅 Günlük Limit: {daily_limit:.1f}",
        f"🤖 Aktif Mod: {active_mode}",
        f"🛠 Stake Normalize: {stake_norm:.2f}x",
        "",
    ]

    # Maçları 3 kupona böl (0-1, 2-3, 4-5)
    coupon_indices = {
        "SAFE": [0, 1],
        "BAL": [2, 3],
        "AGG": [4, 5],
    }

    def build_coupon(title, key):
        idxs = coupon_indices[key]
        lines = [f"🔥 Kupon {1 if key=='SAFE' else 2 if key=='BAL' else 3} — {title}"]
        total_stake = 0.0
        for i in idxs:
            if i >= len(matches):
                continue
            m = matches[i]
            base = m["base_stake"]
            # ilgili seviye stake çarpanı + genel normalize
            mult = stake_mult.get(key.replace("BAL", "BAL"), 1.0)
            stake = base * stake_norm * mult
            total_stake += stake

            if m["pick_type"] == "total":
                pick_str = f"{m['pick']} (total)"
            elif m["pick_type"] == "moneyline":
                pick_str = f"{m['pick']} (moneyline)"
            else:
                pick_str = f"{m['pick']} (spread)"

            lines.append(f"- {m['match']} → {pick_str}")
            lines.append(
                f"  Güven: {m['confidence']:.2f} | Edge: {m['edge']:.3f} | Stake: {stake:.2f}"
            )
        lines.append(f"💰 Kupon Toplam Stake: {total_stake:.2f}")
        lines.append("— — —")
        return "\n".join(lines)

    coupons = []
    coupons.append(build_coupon("SAFE", "SAFE"))
    coupons.append(build_coupon("BALANCED", "BAL"))
    coupons.append(build_coupon("AGGRESSIVE", "AGG"))

    return "\n".join(header_lines + coupons)


def format_faz7_plan(today_stats, summary_7g, strategy):
    lines = ["🧠 FAZ-7.9 STRATEJİ BEYNİ", ""]
    lines.append(f"🎯 Mod: {strategy['mode']}")
    lines.append(
        f"📊 Günlük: conf={today_stats['avg_conf']:.3f} edge={today_stats['avg_edge']:.3f}"
    )
    lines.append(
        f"📊 7 Gün Ort.: conf={summary_7g['avg_conf_7g']:.3f} edge={summary_7g['avg_edge_7g']:.3f}"
    )
    lines.append(
        f"📈 Trend: {'INIT' if summary_7g['avg_conf_7g']==0.0 else 'slope ' + str(summary_7g['trend_slope'])}"
    )
    lines.append(
        f"🌊 Volatilite: {summary_7g['volatility_conf']:.3f} (conf), {summary_7g['volatility_edge']:.3f} (edge)"
    )
    lines.append(f"🛠 Stake Normalize: {strategy['stake_normalize']:.2f}x")
    lines.append("")
    lines.append("📦 Seviye Durumu")
    lines.append(
        f"- SAFE: {'✅' if strategy['level_flags']['SAFE'] else '❌'} (x{strategy['stake_multipliers']['SAFE']:.1f})"
    )
    lines.append(
        f"- BALANCED: {'✅' if strategy['level_flags']['BAL'] else '❌'} (x{strategy['stake_multipliers']['BAL']:.1f})"
    )
    lines.append(
        f"- AGGRESSIVE: {'✅' if strategy['level_flags']['AGG'] else '❌'} (x{strategy['stake_multipliers']['AGG']:.1f})"
    )
    lines.append("- ULTRA: 🚫 (manuel kapalı)")
    lines.append("")

    # Son kayıt
    lines.append("🗓 Son FAZ-7 Kayıt")
    lines.append(
        f"- {today_stats['date']} | Maç: {today_stats['matches']} | Conf: {today_stats['avg_conf']:.3f} | Edge: {today_stats['avg_edge']:.3f} | Mod: {strategy['mode']}"
    )
    if len(load_memory().get("days", [])) < 2:
        lines.append("")
        lines.append("ℹ Dün ile karşılaştırma için yeterli veri yok.")
    if len(load_memory().get("days", [])) < 3:
        lines.append("ℹ Trend analizi için en az 3 gün gerekli.")

    return "\n".join(lines)


def format_faz7_status(summary_7g, memory):
    days = memory.get("days", [])
    lines = ["🧠 FAZ-7.9 HAFIZA ÖZETİ (Son 7 Gün)", ""]

    if not days:
        lines.append("Hafızada kayıt yok. INIT modundasın.")
        return "\n".join(lines)

    mc = summary_7g["mode_counts"]
    lines.append(f"SAFE: {mc.get('SAFE',0)}")
    lines.append(f"BAL : {mc.get('BAL',0)}")
    lines.append(f"AGG : {mc.get('AGG',0)}")
    lines.append("")
    lines.append(
        f"7 Günlük Ortalama Confidence: {summary_7g['avg_conf_7g']:.3f}"
    )
    lines.append(f"7 Günlük Ortalama Edge: {summary_7g['avg_edge_7g']:.3f}")
    lines.append("")
    lines.append(
        f"Volatilite (conf): {summary_7g['volatility_conf']:.3f}, trend slope: {summary_7g['trend_slope']:.4f}"
    )
    lines.append("")
    lines.append("Not: Stake çarpanları FAZ-7.9 beyni tarafından son 7 güne göre ayarlanır.")

    return "\n".join(lines)


# -------------------------------------------------
#  TELEGRAM KOMUTLARI
# -------------------------------------------------


def cmd_start(update: Update, context: CallbackContext):
    msg = (
        "🔥 Bot aktif!\n"
        "FAZ-4 aktif.\n"
        "FAZ-5 bağlı.\n"
        "FAZ-6 tam online.\n"
        "FAZ-7.9 strateji beyni ve hafıza sistemi çalışıyor.\n"
        "Komut listesi için /help yaz."
    )
    update.message.reply_text(msg)


def cmd_help(update: Update, context: CallbackContext):
    msg = (
        "📌 Komutlar:\n\n"
        "/start - Botu başlatır\n"
        "/status - Sistemi gösterir\n\n"
        "/faz6_test - FAZ-6 Test (placeholder)\n"
        "/faz6_auto - FAZ-6 Auto maç listesi\n"
        "/faz6_coupon - FAZ-7 + FAZ-6 birleşik kuponlar\n\n"
        "/faz7_plan - FAZ-7.9 günlük strateji beyni\n"
        "/faz7_status - FAZ-7.9 hafıza özeti\n"
    )
    update.message.reply_text(msg)


def cmd_status(update: Update, context: CallbackContext):
    msg = (
        "🟢 Sistem stabil.\n"
        "FAZ-4 aktif.\n"
        "FAZ-5 bağlı.\n"
        "FAZ-6 tam online.\n"
        "FAZ-7.9 strateji beyni ve hafıza sistemi çalışıyor."
    )
    update.message.reply_text(msg)


def cmd_faz6_test(update: Update, context: CallbackContext):
    update.message.reply_text("🧪 FAZ-6 TEST: Placeholder sonuç (engine entegrasyonu yok).")


def cmd_faz6_auto(update: Update, context: CallbackContext):
    text = format_faz6_auto(SAMPLE_MATCHES)
    update.message.reply_text(text)


def cmd_faz6_coupon(update: Update, context: CallbackContext):
    # 1) Günün maçlarından istatistik
    today_stats = compute_today_stats(SAMPLE_MATCHES)
    memory = load_memory()
    memory = update_memory_with_today(memory, today_stats)
    save_memory(memory)
    summary_7g = summarize_last_7_days(memory)
    strategy = decide_faz79_strategy(today_stats, summary_7g)

    text = format_faz6_coupons(SAMPLE_MATCHES, strategy, summary_7g)
    update.message.reply_text(text)


def cmd_faz7_plan(update: Update, context: CallbackContext):
    today_stats = compute_today_stats(SAMPLE_MATCHES)
    memory = load_memory()
    memory = update_memory_with_today(memory, today_stats)
    save_memory(memory)
    summary_7g = summarize_last_7_days(memory)
    strategy = decide_faz79_strategy(today_stats, summary_7g)

    text = format_faz7_plan(today_stats, summary_7g, strategy)
    update.message.reply_text(text)


def cmd_faz7_status(update: Update, context: CallbackContext):
    memory = load_memory()
    summary_7g = summarize_last_7_days(memory)
    text = format_faz7_status(summary_7g, memory)
    update.message.reply_text(text)


# -------------------------------------------------
#  TELEGRAM BOT BOOTSTRAP
# -------------------------------------------------


def run_bot():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", cmd_start))
    dp.add_handler(CommandHandler("help", cmd_help))
    dp.add_handler(CommandHandler("status", cmd_status))

    dp.add_handler(CommandHandler("faz6_test", cmd_faz6_test))
    dp.add_handler(CommandHandler("faz6_auto", cmd_faz6_auto))
    dp.add_handler(CommandHandler("faz6_coupon", cmd_faz6_coupon))

    dp.add_handler(CommandHandler("faz7_plan", cmd_faz7_plan))
    dp.add_handler(CommandHandler("faz7_status", cmd_faz7_status))

    updater.start_polling()
    logger.info("Telegram bot polling başladı.")
    updater.idle()


# -------------------------------------------------
#  HEALTHCHECK İÇİN FLASK APP
# -------------------------------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return "Zeynal Core AI - OK", 200


def start_all():
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    start_all()
