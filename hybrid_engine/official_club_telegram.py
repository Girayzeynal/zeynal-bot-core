"""Shared /kadro command for all 82 registered NBA/EuroLeague/EuroCup clubs.

One query checks BOTH official team news pages, always prints the exact
source, path, and refusal. It does NOT pretend to prove OUT, lineup, medical
status or new player-impact forecasts. Does not touch the stored forecast.
"""
import asyncio
import html
import re
from telegram.ext import CommandHandler

from hybrid_engine.official_club_fixture_news import (
    read_fixture_club_news,render_fixture_news)

def parse_team_pair(text):
    raw=text.strip()
    mat=re.fullmatch(
        r"/kadro(?:@\w+)?\s+(NBA|EUROLEAGUE|EUROCUP)\s+(.{3,140}?)\s+vs\s+(.{3,140})",
        raw,flags=re.IGNORECASE)
    if not mat:
        raise ValueError("USAGE_KADRO_LEAGUE_HOME_VS_AWAY")
    league=mat.group(1).upper()
    home=mat.group(2).strip()
    away=mat.group(3).strip()
    if home.casefold()==away.casefold():
        raise ValueError("KADRO_SAME_HOME_AWAY")
    return dict(league=league,home=dict(official_name=home),
                away=dict(official_name=away),fixture_start_utc=None)

async def kadro_command(update,context):
    if update.effective_message is None:
        return
    try:
        ctx=parse_team_pair(update.effective_message.text or "")
    except ValueError:
        await update.effective_message.reply_text(
            "Resmî kaynak sorgusu:\n/kadro EUROLEAGUE Armani Olimpia Milan vs Fenerbahce Tarfin Istanbul\n"
            "/kadro EUROLEAGUE Zalgiris Kaunas vs Panathinaikos AKTOR Athens\n"
            "NBA ve EUROCUP da desteklenir. Bu komut bahis veya eksik oyuncu tahmini üretmez.")
        return
    try:
        source=await asyncio.wait_for(
            asyncio.to_thread(read_fixture_club_news,ctx,
                              allow_no_fixture=True),timeout=25)
        output=render_fixture_news(source)
        if len(output.encode("utf-16-le"))//2>4096:
            raise ValueError("OFFICIAL_KADRO_MESSAGE_BUDGET")
    except (ValueError,TypeError,KeyError,TimeoutError,OSError):
        await update.effective_message.reply_text(
            "Resmî kulüp haber kaynakları denetlenemedi veya yanıt süresi aşıldı. "
            "Bu, takımın eksik oyuncusu olmadığı anlamına gelmez.")
        return
    await update.effective_message.reply_text(
        output,parse_mode="HTML",disable_web_page_preview=True)

def install_kadro_command(application,*,group=0):
    application.add_handler(CommandHandler("kadro",kadro_command),group=group)
