# -------------------------
# FAZ-4 – NBA HANDLERS
# -------------------------

from nba_fetcher import (
    fetch_nba_today_games,
    fetch_nba_live_games,
    fetch_nba_finished_games
)

from nba_analyzer import (
    analyze_scheduled_games,
    analyze_live_games,
    analyze_finished_games
)


async def handle_nba_today(update, context) -> None:
    games = fetch_nba_today_games()
    text = analyze_scheduled_games(games)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_nba_live(update, context) -> None:
    games = fetch_nba_live_games()
    text = analyze_live_games(games)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_nba_finished(update, context) -> None:
    games = fetch_nba_finished_games()
    text = analyze_finished_games(games)
    await update.message.reply_text(text, parse_mode="Markdown")# core_handlers.py
# FAZ 3 – Komut işlemleri (bot entegrasyonu)

from main import main
from utils import log_event

def register_handlers(bot):
    @bot.message_handler(commands=["analiz"])
    def handle_analiz(m):
        log_event("INFO", f"Kullanıcı {m.from_user.username} analiz talep etti.")
        try:
            main()  # Ana simülasyonu çalıştır
            bot.reply_to(m, "✅ Analiz tamamlandı, sonuçlar terminalde görüntülendi.")
        except Exception as e:
            bot.reply_to(m, f"❌ Hata: {e}")
            log_event("ERROR", str(e))
