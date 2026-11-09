"""Read-only NBA fixture command: US Eastern game dates, Istanbul tipoff times."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

ISTANBUL = ZoneInfo("Europe/Istanbul")
NEW_YORK = ZoneInfo("America/New_York")
NBA_LEAGUE_ID = 12  # API-Sports league mapping; verify against provider before release.


def parse_nba_date(args: list[str], now: datetime) -> str:
    if len(args) > 1:
        raise ValueError("Kullanım: /nba veya /nba YYYY-MM-DD")
    if not args:
        return now.astimezone(NEW_YORK).date().isoformat()
    try:
        day = datetime.strptime(args[0], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Tarih YYYY-MM-DD biçiminde olmalıdır.") from exc
    return day.isoformat()


def utc_dates_for_turkey_day(day: str) -> list[str]:
    """UTC date partitions intersecting one America/New_York calendar day."""
    local_day = datetime.strptime(day, "%Y-%m-%d").date()
    return [local_day.isoformat(), (local_day + timedelta(days=1)).isoformat()]


def validate_provider_payload(payload: object) -> list[dict]:
    """Reject incomplete or error-bearing API responses before selecting games."""
    if not isinstance(payload, dict):
        raise ValueError("Fikstür sağlayıcısı geçersiz yanıt döndürdü.")
    if payload.get("errors") not in (None, [], {}):
        raise ValueError("Fikstür sağlayıcısı API hatası bildirdi.")
    rows = payload.get("response")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Fikstür sağlayıcısı bozuk maç kaydı döndürdü.")
    return rows


def select_local_games(rows: list[dict], day: str) -> list[dict]:
    selected = {}
    for item in rows:
        try:
            if not isinstance(item, dict) or isinstance(item.get("id"), bool) or not isinstance(item.get("id"), (int, str)) or not str(item["id"]).strip():
                continue
            game_id = str(item["id"])
            start = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
            if start.tzinfo is None:
                continue
            local = start.astimezone(ISTANBUL)
            if start.astimezone(NEW_YORK).date().isoformat() != day:
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
    # Türkiye (UTC+03:00) spans exactly two UTC calendar dates.
    utc_days = utc_dates_for_turkey_day(day)
    rows = []
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for utc_day in utc_days:
            async with session.get(
                base + "/games",
                headers={"x-apisports-key": key},
                params={"league": NBA_LEAGUE_ID, "date": utc_day, "timezone": "UTC"},
            ) as response:
                response.raise_for_status()
                try:
                    payload = await response.json()
                except (ValueError, aiohttp.ContentTypeError) as exc:
                    raise ValueError("Fikstür sağlayıcısı geçerli JSON döndürmedi.") from exc
                rows.extend(validate_provider_payload(payload))
    return select_local_games(rows, day)



def parse_espn_scoreboard(payload: object, day: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("ESPN scoreboard invalid")
    rows = []
    for event in payload["events"]:
        try:
            game_id = str(event["id"]).strip()
            start = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            competitions = event["competitions"]
            if not game_id or start.tzinfo is None or len(competitions) != 1:
                continue
            competitors = competitions[0]["competitors"]
            if len(competitors) != 2:
                continue
            teams = {}
            for competitor in competitors:
                side = competitor["homeAway"]
                name = competitor["team"]["displayName"]
                if side not in ("home", "away") or side in teams or not isinstance(name, str) or not name.strip():
                    break
                teams[side] = name
            if set(teams) != {"home", "away"}:
                continue
            status = event["status"]["type"].get("shortDetail") or event["status"]["type"].get("name")
            if not isinstance(status, str) or not status.strip():
                continue
            rows.append({"id": game_id, "date": start.isoformat(),
                         "teams": {"home": {"name": teams["home"]}, "away": {"name": teams["away"]}},
                         "status": {"short": status}})
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            continue
    return select_local_games(rows, day)


async def load_espn_nba_games(day: str) -> list[dict]:
    unique = {}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for utc_day in utc_dates_for_turkey_day(day):
            async with session.get(
                "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
                params={"dates": utc_day.replace("-", "")},
            ) as response:
                response.raise_for_status()
                payload = await response.json()
                for game in parse_espn_scoreboard(payload, day):
                    unique[(game["start"].isoformat(), game["home"], game["away"])] = game
    return sorted(unique.values(), key=lambda game: game["start"])


async def nba_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    try:
        day = parse_nba_date(context.args or [], datetime.now(timezone.utc))
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    source = "API-Sports"
    try:
        games = await load_nba_games(day)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError):
        try:
            games = await load_espn_nba_games(day)
            source = "ESPN"
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError):
            await update.effective_message.reply_text(
                "NBA fikstürü iki bağımsız sağlayıcıdan da doğrulanamadı. Tahmin üretilmedi."
            )
            return
    if not games:
        await update.effective_message.reply_text(
            f"NBA | {day} | Türkiye saati\nDoğrulanmış maç kaydı bulunamadı. Bu, kesin olarak maç olmadığı anlamına gelmez."
        )
        return
    lines = [f"NBA | {day} ABD tarihi | Saatler Türkiye (TRT)", f"Kaynak: {source} | Fikstür (tahmin değil)"]
    for game in games:
        lines.append(
            f"{game['start']:%H:%M} | {game['home']} - {game['away']} | {game['status']}"
        )
    lines.append("Analiz: /analyze NBA YYYY-MM-DD Ev Sahibi vs Deplasman")
    await update.effective_message.reply_text("\n".join(lines)[:4000])
