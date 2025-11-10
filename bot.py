import os
import telebot

# Token ortam değişkeni (Fly.io için)
TOKEN = os.getenv("BOT_TOKEN ")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "Bot ✅ Çalışıyor!")

bot.infinity_polling()
