# core_handlers.py
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
