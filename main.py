import logging
import os
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from faz13_engine import Faz13Engine, PrematchRequest
from baseline.team_baseline_store import TeamBaselineStore
from faz17_engine import Faz17Engine
from faz16_engine import faz16_run_simulation
from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zeynal-bot-core")

async def cmd_analyze(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Kullanım: /analyze LIG | YYYY-MM-DD | Ev - Deplasman")
        return

    try:
        raw = " ".join(context.args)
        parts = [p.strip() for p in raw.split("|")]
        league, date_str = parts[0], parts[1]
        home, away = [x.strip() for x in parts[2].split("-")]
    except:
        await update.message.reply_text("Hatalı format! Örnek: NBA | 2025-12-25 | Lakers - Warriors")
        return

    # Motorları bot_data'dan al
    engines = context.application.bot_data
    
    # 1. FAZ-13: Ana Veri Kontrolü
    core = await engines["faz13"].run_prematch(PrematchRequest(0, league, date_str, home, away))

    # [HATA AVCI MODU]: Eğer veri yoksa diğer fazlara geçme, kullanıcıyı uyar.
    if not getattr(core, "is_valid", True):
        await update.message.reply_text(core.render_html(), parse_mode=ParseMode.HTML)
        return

    # 2. FAZ-17: Market Zenginleştirme
    try:
        core = await engines["faz17"].enrich_with_market(core)
    except Exception as e:
        log.error(f"Market verisi alınamadı: {e}")

    # 3. FAZ-16: Simülasyon (Sadece market verisi varsa anlamlıdır)
    if hasattr(core, "market_total") and core.market_total > 0:
        try:
            vol = float(getattr(core, "market_vol", 15.0))
            core.faz16_simulation = faz16_run_simulation(core.market_total, vol)
        except Exception as exc:
            log.error(f"Simülasyon hatası: {exc}")
    else:
        core.notes.append("⚠️ Market çizgisi bulunamadığı için simülasyon atlandı.")

    # 4. FAZ-22 & 23: Skorlama ve Kayıt
    core = engines["faz22"].score_and_finalize(core)
    await engines["faz23"].record_snapshot(core)

    # Final Çıktı
    await update.message.reply_text(core.render_html(), parse_mode=ParseMode.HTML)

def main() -> None:
    # Environment Variables
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    api_key = os.getenv("API_SPORTS_KEY")
    
    app = Application.builder().token(token).build()

    # Engine Initialization
    baseline_store = TeamBaselineStore(os.getenv("BASELINE_DIR", "data/baselines"))
    
    app.bot_data["faz13"] = Faz13Engine(api_key, "https://v1.basketball.api-sports.io", baseline_store)
    app.bot_data["faz17"] = Faz17Engine(os.getenv("ODDS_API_KEY"), "https://api.the-odds-api.com/v4")
    app.bot_data["faz22"] = Faz22Engine()
    app.bot_data["faz23"] = Faz23Engine(os.getenv("FAZ23_STORAGE", "faz23_storage.sqlite"))

    app.add_handler(CommandHandler("analyze", cmd_analyze))
    
    log.info("Zeynal Core AI Bot Başlatıldı...")
    app.run_polling()

if __name__ == "__main__":
    main() 
