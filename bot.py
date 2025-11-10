import os
import telebot

# Token ortam değişkeni (Fly.io için)
TOKEN = os.getenv("8395841768:AAEmrUCXtIr3n2t2Pf2jTw46Py2w9M9AC-A ")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "Bot ✅ Çalışıyor!")

bot.infinity_polling()
