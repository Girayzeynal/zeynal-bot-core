"""Read-only premium Telegram presentation for the existing FAZ13 production forecast.

No market quotes, player statuses, calibrated probabilities, or new simulations
are manufactured. This module never writes the forecast ledger.
"""
from __future__ import annotations

from datetime import datetime
from secrets import token_hex
from time import time
from zoneinfo import ZoneInfo
import html
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler

_TSI = ZoneInfo("Europe/Istanbul")
_SECTIONS = ("summary", "period", "ranges", "market", "audit", "roster")
_PREFIX = "zprod"
_LOG = logging.getLogger(__name__)


def _stamp(utc):
    return datetime.fromtimestamp(utc, _TSI).strftime("%d.%m.%Y %H:%M")


def _pages(body, limit=3000):
    blocks = []
    current = []
    size = 0
    for line in body.splitlines():
        if len(line.encode("utf-16-le")) // 2 > limit:
            raise ValueError("PREMIUM_LINE_EXCEEDS_TELEGRAM_LIMIT")
        length = len(line.encode("utf-16-le")) // 2 + 1
        if current and size + length > limit:
            blocks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += length
    if current:
        blocks.append("\n".join(current))
    return blocks or ["Bilgi yok."]


def _keyboard(token, section="summary", page=0, count=1):
    def btn(label, key):
        return InlineKeyboardButton(label, callback_data=f"{_PREFIX}:{token}:{key}:0")
    rows = [
        [btn("📊 Periyotlar", "period"), btn("🎯 Aralıklar", "ranges")],
        [btn("📈 Piyasa", "market"), btn("🛡 Model / Kaynak", "audit")],
        [btn("🏥 Kadro / Sakatlık", "roster")],
        [btn("🏠 Özet", "summary")],
    ]
    if count > 1:
        navigation = []
        if page > 0:
            navigation.append(InlineKeyboardButton("‹ Önceki",
                callback_data=f"{_PREFIX}:{token}:{section}:{page-1}"))
        navigation.append(InlineKeyboardButton(f"{page+1}/{count}",
            callback_data=f"{_PREFIX}:{token}:{section}:{page}"))
        if page + 1 < count:
            navigation.append(InlineKeyboardButton("Sonraki ›",
                callback_data=f"{_PREFIX}:{token}:{section}:{page+1}"))
        rows.insert(0, navigation)
    return InlineKeyboardMarkup(rows)


def build_sections(snapshot, original_html, *, now=None):
    """Use only the existing immutable forecast and original audit text."""
    p = snapshot["prediction"]
    home = html.escape(snapshot["home"]["official_name"])
    away = html.escape(snapshot["away"]["official_name"])
    tipoff = snapshot["fixture_start_utc"]
    now = int(time()) if now is None else now
    if not isinstance(now, int):
        raise ValueError("PREMIUM_NOW_INVALID")
    started = now >= tipoff
    sim = p.get("simulation")
    summary = [
        "🏀 <b>ZEYNAL | NBA ANALİZ</b>",
        f"<b>{home}</b> 🆚 <b>{away}</b>",
        f"{_stamp(tipoff)} TSİ · Normal süre (48 dk)", "",
        "📊 <b>SKOR PROJEKSİYONU</b>",
        f"Ev <b>{p['home']:.1f}</b> · Dep <b>{p['away']:.1f}</b>",
        f"Toplam <b>{p['total']:.1f}</b> · Ev farkı {p['margin']:+.1f}", "",
        "🎯 <b>MODEL YÖNÜ</b>: doğrulanmış güncel piyasa baremi yok.",
        "🛡 Yönün güvenilirliği: henüz kalibre edilmedi.",
    ]
    if sim:
        summary.extend(["", "📊 <b>TOPLAM SAYI ARALIĞI</b>",
            f"P05–P95 {sim['total_quantiles']['p05']:.1f}–{sim['total_quantiles']['p95']:.1f}"])
    summary.extend(["", "NOT_CALIBRATED · Güven endeksi: yok",
        "🔒 Var olan FAZ13 tahminidir; model değişmedi."])
    if started:
        summary.insert(0, "Maç başladı; yalnız arşiv görünümü.\n")
    q = p["quarters"]
    half = p["halves"]
    period = ["📊 <b>PERİYOT | SKOR PROJEKSİYONU</b>",
        "Ev – Deplasman · Normal süre · Tahmin, gerçekleşen skor değildir.", ""]
    labels = [("1. Çeyrek", q["home"][0], q["away"][0]),
        ("2. Çeyrek", q["home"][1], q["away"][1]),
        ("İlk Yarı", half["home"][0], half["away"][0]),
        ("3. Çeyrek", q["home"][2], q["away"][2]),
        ("4. Çeyrek", q["home"][3], q["away"][3]),
        ("İkinci Yarı", half["home"][1], half["away"][1])]
    for label, h, a in labels:
        period.extend([f"<b>{label}</b> | {h:.1f} – {a:.1f}",
                       f"Toplam: {h+a:.1f}", ""])
    period.extend([f"<b>MAÇ</b> | {p['home']:.1f} – {p['away']:.1f}",
        f"Toplam: {p['total']:.1f} · Ev farkı: {p['margin']:+.1f}",
        "Çeyrek aralıkları üretim FAZ13 kaydında doğrulanmadı; uydurulmadı."])
    ranges = ["🎯 <b>TAHMİN ARALIKLARI</b>"]
    if sim:
        ranges.extend([
            f"Maç toplamı P05–P95: {sim['total_quantiles']['p05']:.1f}–{sim['total_quantiles']['p95']:.1f}",
            f"Ev kazanır (ham, normal süre): %{100*sim['home_regulation_win_probability']:.1f}",
            f"Deplasman kazanır (ham, normal süre): %{100*sim['away_regulation_win_probability']:.1f}",
            f"Eşitlik (ham, normal süre): %{100*sim['regulation_tie_probability']:.1f}",
        ])
    else:
        ranges.append("Doğrulanmış simülasyon aralığı yok.")
    ranges.extend(["Çeyrek P25–P75/P05–P95: üretim tahmininde mevcut değil.",
                   "Olasılıklar kalibre edilmedi; başarı/güven yüzdesi değildir."])
    market = ("📈 <b>PİYASA | KAYNAK DURUMU</b>\n"
              "Bu üretim FAZ13 kaydına gerçek zamanlı barem ve oran kanıtı bağlı değil.\n"
              "Test botunun fiyatlarını üretimin geçmiş tahmini gibi göstermiyoruz.\n"
              "Canlı piyasa karşılaştırması: VERİ DOĞRULANMADI.")
    roster = ("🏥 <b>KADRO / SAKATLIK | KAYNAK DURUMU</b>\n"
              "Üretim FAZ13 tahmininde maç ve zamanla doğrulanmış güncel oyuncu paketi yok.\n"
              "Kadro, sakatlık, ilk beş ve rotasyon MODELE BAĞLI DEĞİL.\n"
              "Bu, sakat oyuncu bulunmadığı anlamına gelmez.")
    return dict(summary="\n".join(summary), period="\n".join(period),
                ranges="\n".join(ranges), market=market, roster=roster,
                audit=("🛡 <b>MODEL / KAYNAK | ORİJİNAL FAZ13 RAPORU</b>\n"
                       "İlk skorlar ve kaynak kimliği aşağıdadır.\n\n" + original_html))


def enhance(report, cache, chat_id):
    if report.get("status") != "ANALYSIS_OK" or not report.get("snapshot"):
        return report
    if report["snapshot"].get("league") != "NBA":
        return report
    sections = build_sections(report["snapshot"], report["html"])
    token = token_hex(6)
    entry = dict(chat_id=chat_id, sections={k: _pages(v) for k, v in sections.items()},
                 tipoff_utc=report["snapshot"]["fixture_start_utc"])
    while len(cache) >= 64:
        cache.pop(next(iter(cache)))
    cache[token] = entry
    output = dict(report)
    output["html_parts"] = [entry["sections"]["summary"][0]]
    output["reply_markup"] = _keyboard(token)
    return output


async def callback(update, context):
    query = update.callback_query
    if query is None:
        return
    match = re.fullmatch(r"zprod:([0-9a-f]{12}):(summary|period|ranges|market|audit|roster):(\d{1,3})",
                         query.data or "")
    if match is None:
        return
    token, section, page_text = match.groups()
    entry = context.application.bot_data.get("production_premium_reports", {}).get(token)
    if entry is None or update.effective_chat is None or entry["chat_id"] != update.effective_chat.id:
        await query.answer("Rapor oturumu bulunamadı. /analyze ile yeniden açın.", show_alert=True)
        return
    page = int(page_text)
    pages = entry["sections"][section]
    if page >= len(pages):
        await query.answer("Sayfa bulunamadı.", show_alert=True)
        return
    await query.answer()
    body = pages[page]
    if section in ("summary", "market", "roster") and int(time()) >= entry["tipoff_utc"]:
        body = "Maç başladı; arşiv görünümü.\n\n" + body
    try:
        await query.edit_message_text(body, parse_mode="HTML", disable_web_page_preview=True,
            reply_markup=_keyboard(token, section, page, len(pages)))
    except Exception as exc:
        if "Message is not modified" in str(exc):
            return
        _LOG.warning("Production premium page edit failed: %s", type(exc).__name__)
        try:
            await query.message.reply_text("Sayfa geçişi tamamlanamadı. Tekrar deneyin; kod: PREMIUM_PAGE_EDIT_FAILED.")
        except Exception:
            _LOG.warning("Production premium fallback delivery also failed")


def install(app):
    app.bot_data.setdefault("production_premium_reports", {})
    app.add_handler(CallbackQueryHandler(callback,
        pattern=r"^zprod:[0-9a-f]{12}:(summary|period|ranges|market|audit|roster):[0-9]{1,3}$"))
