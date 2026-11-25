"""Isolated-bot input guard; never changes a command date or invokes a model."""
import re

from core.league_identity import normalize_name
from telegram.ext import ApplicationHandlerStop


USAGE = ('Kullanım: /analyze NBA YYYY-MM-DD Ev Sahibi vs Deplasman\n'
         'Takımlar arasında vs veya boşluklarla ayrılmış – / — kullanılabilir.\n'
         'Her mesajda yalnız bir /analyze komutu gönderin.\n'
         'Tarih Türkiye takvim günüdür (TSİ). Doğru tarihli komutları '
         '/nba YYYY-MM-DD veya /euroleague YYYY-MM-DD listesinden alabilirsiniz.\n'
         'Tahmin üretilmedi; mevcut tahmin kayıtları değiştirilmedi.')
COMMAND = re.compile(r'(?<!\S)/analyze(?:@[A-Za-z0-9_]+)?(?=\s|$)', re.IGNORECASE)


def input_error(text, parser):
    if len(COMMAND.findall(text)) > 1:
        return ('Birden fazla /analyze komutu tek mesajda alındı. '
                'Komutlar otomatik olarak topluca çalıştırılmadı.\n' + USAGE)
    try:
        _, _, home, away = parser(text)
    except ValueError:
        # Fixed text only; pasted source URLs or other input are not echoed.
        return 'Komut biçimi eksik veya geçersiz.\n' + USAGE
    if len(home) > 300 or len(away) > 300:
        return 'Takım adı en fazla 300 karakter olmalıdır.\n' + USAGE
    try:
        normalize_name(home)
        normalize_name(away)
    except ValueError:
        return 'Ev sahibi ve deplasman için geçerli takım adları gerekir.\n' + USAGE
    return None


class AnalyzeInputGuard:
    def __init__(self, chat_id):
        self.chat_id = chat_id

    async def handle(self, update, context):
        if update.effective_chat is None or update.effective_chat.id != self.chat_id:
            raise ApplicationHandlerStop
        from main import parse_analyze
        message = update.effective_message
        if message is None:
            raise ApplicationHandlerStop
        error = input_error(message.text or '', parse_analyze)
        if error:
            await message.reply_text(error, disable_web_page_preview=True)
            raise ApplicationHandlerStop
        # Valid commands continue to the existing handler unchanged. In
        # particular, never silently substitute the ESPN day for the TSİ day.
