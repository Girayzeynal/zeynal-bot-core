"""Read-only NBA fixture command. All displayed dates are Europe/Istanbul local."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

ISTANBUL = ZoneInfo("Europe/Istanbul")
NBA_LEAGUE_ID = 12  # API-Sports league mapping; verify against provider before release.


def parse_nba_date(args: list[str], now: datetime) -> str:
    if len(args) > 1:
        raise ValueError("Kullanım: /nba veya /nba YYYY-MM-DD")
    if not args:
        return now.astimezone(ISTANBUL).date().isoformat()
    try:
        day = datetime.strptime(args[0], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Tarih YYYY-MM-DD biçiminde olmalıdır.") from exc
    return day.isoformat()


def select_local_games(rows: list[dict], day: str) -> list[dict]:
    selected = {}
    for item in rows:
        try:
            game_id = str(item["id"])
            start = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
            if start.tzinfo is None:
                continue
            local = start.astimezone(ISTANBUL)
            if local.date().isoformat() != day:
                continue
            home = item["teams"]["home"]["name"]
            away = item["teams"]["away"]["name"]
            status = item["status"]["short"]
            if not all(isinstance(x, str) and x.strip() for x in (home, away, status)):
                continue
            selected[game_id] = {"start": local, "home": home, "away": away, "status": status}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return sorted(selected.values(), key=lambda g: g["start"])


async def load_nba_games(day: str) -> list[dict]:
    key = os.getenv("API_SPORTS_KEY")
    if not key:
        raise RuntimeError("API-Sports anahtarı yapılandırılmamış.")
    base = os.getenv("API_SPORTS_BASE", "https://v1.basketball.api-sports.io").rstrip("/")
    local_day = datetime.strptime(day, "%Y-%m-%d").date()
    # A Türkiye calendar day (UTC+03:00) spans only the previous and current UTC dates.
    # Avoid an unnecessary third API request per /nba invocation.
    utc_days = [local_day - timedelta(days=1), local_day]
    rows = []
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for utc_day in utc_days:
            async with session.get(
                base + "/games",
                headers={"x-apisports-key": key},
                params={"league": NBA_LEAGUE_ID, "date": utc_day.isoformat(), "timezone": "UTC"},
            ) as response:
                response.raise_for_status()
                payload = await response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("response"), list):
                    raise ValueError("Fikstür sağlayıcısı geçersiz yanıt döndürdü.")
                errors = payload.get("errors")
                if errors and errors != [] and errors != {}:
                    raise ValueError("Fikstür sağlayıcısı API hatası bildirdi.")
                rows.extend(payload["response"])
    return select_local_games(rows, day)


async def nba_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    try:
        day = parse_nba_date(context.args or [], datetime.now(timezone.utc))
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    try:
        games = await load_nba_games(day)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError):
        await update.effective_message.reply_text(
            "NBA fikstürü doğrulanamadı. Sağlayıcı bağlantısı, yanıtı veya yapılandırması kontrol edilmeli. Tahmin üretilmedi."
        )
        return
    if not games:
        await update.effective_message.reply_text(
            f"NBA | {day} | Türkiye saati\nDoğrulanmış maç kaydı bulunamadı. Bu, kesin olarak maç olmadığı anlamına gelmez."
        )
        return
    lines = [f"NBA | {day} | Türkiye saati", "Kaynak: API-Sports | Fikstür (tahmin değil)"]
    for game in games:
        lines.append(
            f"{game['start']:%H:%M} | {game['home']} - {game['away']} | {game['status']}"
        )
    lines.append("Analiz: /analyze NBA YYYY-MM-DD Ev Sahibi vs Deplasman")
    await update.effective_message.reply_text("\n".join(lines)[:4000])
