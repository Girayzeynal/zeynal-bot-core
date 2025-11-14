import telebot
from telebot.types import Message
import faz5_engine.faz5_engine_main as faz5

bot = telebot.TeleBot("TELEGRAM_BOT_TOKENINI_BURAYA_YAZ")

# /start
@bot.message_handler(commands=['start'])
def start(message: Message):
    bot.reply_to(message, "🔥 Merhaba! FAZ-5 Heavy Engine hazır. Komutlar:\n"
                          "/heavy - Standart Kupon\n"
                          "/heavy_risk - Yüksek Risk Kupon\n"
                          "/heavy_edge - Edge Analiz Kuponu\n"
                          "/heavy_auto - Otomatik Mod\n"
                          "/heavy_full - Full Paket (Tüm analizler)")

# FAZ-5 MAIN ÇAĞIRMA FONKSİYONU
def run_faz5(mode):
    return faz5.run(mode)

# /heavy
@bot.message_handler(commands=['heavy'])
def heavy(message: Message):
    result = run_faz5("standard")
    bot.reply_to(message, result)

# /heavy_risk
@bot.message_handler(commands=['heavy_risk'])
def heavy_risk(message: Message):
    result = run_faz5("risk")
    bot.reply_to(message, result)

# /heavy_edge
@bot.message_handler(commands=['heavy_edge'])
def heavy_edge(message: Message):
    result = run_faz5("edge")
    bot.reply_to(message, result)

# /heavy_auto
@bot.message_handler(commands=['heavy_auto'])
def heavy_auto(message: Message):
    result = run_faz5("auto")
    bot.reply_to(message, result)

# /heavy_full
@bot.message_handler(commands=['heavy_full'])
def heavy_full(message: Message):
    result = run_faz5("full")
    bot.reply_to(message, result)

print("🤖 Telegram bot FAZ-5 Heavy Engine ile çalışıyor...")
