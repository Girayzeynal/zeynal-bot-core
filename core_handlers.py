"""
FAZ-4 – Core Handlers

Bu dosya:
- Temel bot komutlarını (/start, /help, /ping)
- FAZ-4 NBA komutlarını (/nba_today, /nba_live, /nba_finished, /nba_raw)
barındırır.

Tüm fonksiyonlar async tasarlanmıştır ve python-telegram-bot v20+ ile uyumludur.
"""

from nba_fetcher import (
    fetch_nba_today_games,
    fetch_nba_live_games,
    fetch_nba_finished_games,
    fetch_nba_schedule_real,
)

from nba_analyzer import (
    analyze_scheduled_games,
    analyze_live_games,
    analyze_finished_games,
)


# ---------------------------------------------------------
#  TEMEL KOMUTLAR
# ---------------------------------------------------------

async def handle_start(update, context) -> None:
    """
    /start komutu – botun karşılama mesajı.
    """
    text = (
        "👋 Merhaba, ben Zeynal Core Bot.\n\n"
        "FAZ-4 çekirdeği aktif.\n"
        "NBA veri motoru ve analiz sistemi devrede.\n\n"
        "Yardım için /help komutunu kullanabilirsin."
    )
    await update.message.reply_text(text)


async def handle_help(update, context) -> None:
    """
    /help komutu – botun komut listesini gösterir.
    """
    text = (
        "🧠 *HoopBrain / Zeynal Core – Komut Listesi*\n\n"
        "Genel:\n"
        "• /start – Karşılama mesajı\n"
        "• /help – Bu yardım ekranı\n"
        "• /ping – Botun canlılık testi\n\n"
        "FAZ-4 – NBA Motoru:\n"
        "• /nba_today – Bugünkü NBA maçları (dummy – iskelet test)\n"
        "• /nba_live – Canlı NBA maçları (dummy – iskelet test)\n"
        "• /nba_finished – Bitmiş NBA maçları (dummy – iskelet test)\n"
        "• /nba_raw – ESPN scoreboard API ham veri testi\n\n"
        "Not: FAZ-4 şu an iskelet modunda; gerçek oran/veri akışı adım adım bağlanacak."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_ping(update, context) -> None:
    """
    /ping komutu – basit canlılık testi.
    """
    await update.message.reply_text("✅ Bot çalışıyor, FAZ-4 çekirdeği aktif.")



# ---------------------------------------------------------
#  FAZ-4 – NBA HANDLERS
# ---------------------------------------------------------

async def handle_nba_today(update, context) -> None:
    """
    /nba_today – Bugünkü NBA maçları (dummy veri ile).
    İleride gerçek API verisiyle beslenecek.
    """
    games = fetch_nba_today_games()
    text = analyze_scheduled_games(games)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_nba_live(update, context) -> None:
    """
    /nba_live – Canlı NBA maçları (dummy veri).
    """
    games = fetch_nba_live_games()
    text = analyze_live_games(games)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_nba_finished(update, context) -> None:
    """
    /nba_finished – Bitmiş NBA maçları (dummy veri).
    """
    games = fetch_nba_finished_games()
    text = analyze_finished_games(games)
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_nba_raw(update, context) -> None:
    """
    /nba_raw – ESPN scoreboard endpoint'inden gelen ham veriyi test eder.
    Bu komut FAZ-4 veri boru hattının dış dünyaya bağlandığı ilk noktadır.
    """
    data = fetch_nba_schedule_real()
    # Telegram mesaj limiti ~4096 karakter, biz 3500 ile sınırlıyoruz
    snippet = str(data)
    if len(snippet) > 3500:
        snippet = snippet[:3500] + "... (kısaltıldı)"
    await update.message.reply_text(snippet)
