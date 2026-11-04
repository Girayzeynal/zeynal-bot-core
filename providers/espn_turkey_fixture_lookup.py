"""Read-only ESPN NBA fixture lookup for an explicit Türkiye calendar date.

Never infer a fixture from names alone; callers supply independently resolved
ESPN home/away team IDs. Fetch both relevant ESPN schedule dates to account
for the UTC/Türkiye day boundary and reject ambiguous matches.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from providers.espn_adapter import ESPNAdapter


ISTANBUL = ZoneInfo("Europe/Istanbul")


async def resolve_nba_fixture_for_turkey_date(
    adapter: ESPNAdapter, date_str: str, *,
    home_team_id: str, away_team_id: str,
) -> dict:
    if not isinstance(adapter, ESPNAdapter):
        raise TypeError("ESPNAdapter required")
    try:
        if not isinstance(date_str, str) or len(date_str) != 10:
            raise ValueError("invalid date")
        local_day = date.fromisoformat(date_str)
        if local_day.isoformat() != date_str:
            raise ValueError("noncanonical date")
    except (TypeError, ValueError) as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc
    if any(not isinstance(tid, str) or not tid.strip() for tid in (home_team_id, away_team_id)):
        raise ValueError("Both ESPN team IDs required")
    if home_team_id == away_team_id:
        raise ValueError("Home and away ESPN IDs must differ")
    # A Türkiye calendar day starts on the previous UTC date.
    local_start = datetime(local_day.year, local_day.month, local_day.day, tzinfo=ISTANBUL)
    utc_start = local_start.astimezone(timezone.utc)
    utc_dates = sorted({utc_start.date(), (utc_start + timedelta(days=1)).date()})
    rows = []
    for utc_day in utc_dates:
        rows.extend(await adapter.fetch_scheduled_nba_scoreboard_date(utc_day.strftime("%Y%m%d")))
    matching = {}
    for row in rows:
        if row.get("home_team_id") != home_team_id or row.get("away_team_id") != away_team_id:
            continue
        tipoff = row.get("start_ts_utc")
        if type(tipoff) is not int or tipoff <= 0:
            continue
        if datetime.fromtimestamp(tipoff, tz=ISTANBUL).date() != local_day:
            continue
        key = row.get("provider_fixture_id")
        if not isinstance(key, str) or not key:
            continue
        if key in matching and matching[key] != row:
            raise ValueError("Conflicting ESPN fixture identity across schedule dates")
        matching[key] = row
    if len(matching) != 1:
        raise ValueError("No unique pregame ESPN fixture matched the Türkiye date and teams")
    return next(iter(matching.values()))
