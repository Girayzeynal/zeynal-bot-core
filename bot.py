"""
FAZ-4 – bot.py (Telegram Bot Çekirdeği)

Bu dosya:
- Botun ana iskeletini
- Komut handler kayıtlarını
- Application (telegram bot) başlatıcısını
içerir.

Tamamen python-telegram-bot v20+ ile uyumludur.
"""

import os
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler
)

# Core handlers (FAZ-4)
from core_handlers import (
    handle_start,
    handle_help,
    handle_ping,
    handle_nba_today,
    handle_nba_live,
    handle_nba_finished,
    handle_nba_raw,
)


# ---------------------------------------------------------
#  BOT TOKEN
# ---------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Fly.io / Render environment'dan gelir

if BOT_TOKEN is None:
    raise RuntimeError("❌ BOT_TOKEN environment değişkeni tanımlı değil!")


# ---------------------------------------------------------
#  TELEGRAM BOT UYGULAMASI
# ---------------------------------------------------------

def create_app():
    """
    Telegram Application nesnesini oluşturur.
    Tüm handler'lar burada kaydedilir.
    """

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Genel komutlar
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("ping", handle_ping))

    # FAZ-4 NBA komutları
    app.add_handler(CommandHandler("nba_today", handle_nba_today))
    app.add_handler(CommandHandler("nba_live", handle_nba_live))
    app.add_handler(CommandHandler("nba_finished", handle_nba_finished))
    app.add_handler(CommandHandler("nba_raw", handle_nba_raw))

    return app


# ---------------------------------------------------------
#  MAIN
# ---------------------------------------------------------

def main():
    """
    Botu başlatır.
    """
    app = create_app()
    print("🤖 Zeynal Core Bot – FAZ-4 çekirdek başlatıldı.")
    app.run_polling()


if __name__ == "__main__":
    main()
