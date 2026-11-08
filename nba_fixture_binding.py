"""Resolve a Turkish-calendar NBA /analyze request to one verified ESPN fixture."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


async def resolve_nba_fixture(adapter, date_str: str, home: str, away: str, *, now_utc=None):
    requested = date.fromisoformat(date_str)
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    home_ref = await adapter.resolve_team(home)
    away_ref = await adapter.resolve_team(away)
    if not home_ref or not away_ref or home_ref["id"] == away_ref["id"]:
        raise ValueError("Takım kimliği doğrulanamadı veya takımlar aynı")
    matches = {}
    for offset in (-1, 0, 1):
        day = (requested + timedelta(days=offset)).strftime("%Y%m%d")
        for fixture in await adapter.fetch_scheduled_nba_scoreboard_date(day):
            if fixture["home_team_id"] != home_ref["id"] or fixture["away_team_id"] != away_ref["id"]:
                continue
            start = datetime.fromtimestamp(fixture["start_ts_utc"], timezone.utc)
            if start.astimezone(ZoneInfo("Europe/Istanbul")).date() != requested:
                continue
            if start <= now:
                continue
            key = fixture["provider_fixture_id"]
            if key in matches and matches[key] != fixture:
                raise ValueError("Çelişkili fikstür kimliği")
            matches[key] = fixture
    if len(matches) != 1:
        raise ValueError("Tekil, başlamamış ESPN NBA fikstürü doğrulanamadı")
    fixture = next(iter(matches.values()))
    if not str(fixture["provider_fixture_id"]).isascii() or not str(fixture["provider_fixture_id"]).isdigit():
        raise ValueError("Geçersiz ESPN fikstür kimliği")
    return fixture
