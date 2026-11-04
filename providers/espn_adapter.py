from __future__ import annotations

import asyncio
import calendar
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from providers.espn_completed_event import parse_completed_nba_event
from providers.espn_boxscore_pace import estimate_pace_from_summary


ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
logger = logging.getLogger("zeynal-core.espn")


class ESPNAdapter:
    """
    ESPN ADAPTER — PRODUCTION GRADE (FREE)

    - team_name / abbr -> team_id resolve (cache'li)
    - schedule fetch ONLY team_id ile
    - sadece COMPLETED maçlar
    - retry + backoff
    - TeamBaselineBootstrapper sözleşmesine %100 uyum
    """

    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._session = session
        self._owns_session = session is None
        self._teams_cache: Optional[List[Dict[str, Any]]] = None
        self._teams_cache_ts: float = 0.0
        self._teams_ttl = 6 * 3600  # 6 saat

    # -------------------------------------------------
    # SESSION
    # -------------------------------------------------
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        timeout = aiohttp.ClientTimeout(total=20)
        # Managed and corporate runtimes may require HTTPS_PROXY. aiohttp
        # ignores environment proxies unless explicitly enabled.
        self._session = aiohttp.ClientSession(timeout=timeout, trust_env=True)
        self._owns_session = True
        return self._session

    async def aclose(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    # -------------------------------------------------
    # HTTP (retry + backoff)
    # -------------------------------------------------
    async def _get_json(self, url: str) -> Optional[Dict[str, Any]]:
        backoff = 0.6
        for _ in range(3):
            try:
                s = await self._get_session()
                async with s.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status in (429, 500, 502, 503):
                        await asyncio.sleep(backoff)
                        backoff *= 1.6
                        continue
                    return None
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.6
        return None

    # -------------------------------------------------
    # TEAM DIRECTORY (cache'li)
    # -------------------------------------------------
    async def _load_teams(self) -> Optional[List[Dict[str, Any]]]:
        now = time.time()
        if self._teams_cache and (now - self._teams_cache_ts) < self._teams_ttl:
            return self._teams_cache

        js = await self._get_json(f"{ESPN_BASE}/teams")
        if not js:
            return None

        try:
            teams = (
                js.get("sports", [{}])[0]
                .get("leagues", [{}])[0]
                .get("teams", [])
            )
            self._teams_cache = teams
            self._teams_cache_ts = now
            return teams
        except Exception:
            return None

    # -------------------------------------------------
    # RESOLVE TEAM -> ID / ABBR
    # -------------------------------------------------
    async def resolve_team(self, team_input: str) -> Optional[Dict[str, str]]:
        if not team_input:
            return None

        key = team_input.strip().lower()
        teams = await self._load_teams()
        if not teams:
            return None

        matches: Dict[str, Dict[str, str]] = {}
        for t in teams:
            if not isinstance(t, dict):
                continue
            team = t.get("team", {})
            if not isinstance(team, dict):
                continue
            tid = team.get("id")
            abbr = str(team.get("abbreviation", "")).upper()
            name = str(team.get("displayName", "")).lower()
            short = str(team.get("shortDisplayName", "")).lower()
            if key in (abbr.lower(), name, short) and tid is not None and str(tid).strip():
                matches[str(tid)] = {
                    "id": str(tid), "abbr": abbr,
                    "name": team.get("displayName"),
                }
        # Never select the first of two teams sharing an alias.
        return next(iter(matches.values())) if len(matches) == 1 else None

    # Bootstrapper uyumu için
    async def resolve_team_abbr(self, league: str, team_input: str) -> Optional[str]:
        # ESPN adapter is NBA-only; never resolve a non-NBA team to an NBA franchise.
        if (league or "").upper().strip() != "NBA":
            return None
        ref = await self.resolve_team(team_input)
        return ref["abbr"] if ref else None

    async def fetch_scheduled_nba_scoreboard_date(
        self, date_yyyymmdd: str,
    ) -> List[Dict[str, Any]]:
        """Fetch vetted pregame fixture identities; never write predictions.

        A malformed or unavailable response is an error, not an empty schedule.
        Conflicting duplicate provider IDs are excluded rather than guessed.
        """
        if (not isinstance(date_yyyymmdd, str) or len(date_yyyymmdd) != 8
                or not date_yyyymmdd.isascii() or not date_yyyymmdd.isdigit()):
            raise ValueError("date must be YYYYMMDD")
        try:
            datetime.strptime(date_yyyymmdd, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("invalid calendar date") from exc
        payload = await self._get_json(
            f"{ESPN_BASE}/scoreboard?dates={date_yyyymmdd}"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise RuntimeError("ESPN pregame scoreboard unavailable or malformed")
        from providers.espn_scheduled_fixture import parse_scheduled_nba_fixture
        by_id: Dict[str, Dict[str, Any]] = {}
        conflicts: set[str] = set()
        for raw in payload["events"]:
            parsed = parse_scheduled_nba_fixture(raw)
            if parsed is None:
                continue
            key = parsed["provider_fixture_id"]
            if key in conflicts:
                continue
            if key in by_id and by_id[key] != parsed:
                conflicts.add(key)
                by_id.pop(key, None)
            else:
                by_id[key] = parsed
        return sorted(by_id.values(), key=lambda row: (
            row["start_ts_utc"], row["provider_fixture_id"]
        ))

    async def fetch_nba_scoreboard_quality_report(
        self, date_yyyymmdd: str, observed_at_utc: int | None = None,
    ) -> Dict[str, Any]:
        """Return raw-data quality metrics and vetted events from one fetch.

        A failed HTTP request is an explicit error, not an empty NBA game day.
        """
        if (not isinstance(date_yyyymmdd, str)
                or len(date_yyyymmdd) != 8
                or not date_yyyymmdd.isascii()
                or not date_yyyymmdd.isdigit()):
            raise ValueError("date must be YYYYMMDD")
        try:
            datetime.strptime(date_yyyymmdd, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("invalid calendar date") from exc
        payload = await self._get_json(
            f"{ESPN_BASE}/scoreboard?dates={date_yyyymmdd}"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise RuntimeError("ESPN scoreboard unavailable or malformed")
        from providers.espn_quality_audit import audit_espn_events
        now = observed_at_utc if observed_at_utc is not None else int(datetime.now(timezone.utc).timestamp())
        report = audit_espn_events(payload["events"], observed_at_utc=now)
        from providers.espn_status_shapes import summarize_espn_status_shapes
        report["status_shapes"] = summarize_espn_status_shapes(payload["events"])
        observed = datetime.fromtimestamp(now, tz=timezone.utc)
        rows: Dict[str, Dict[str, Any]] = {}
        conflicts: set[str] = set()
        for raw in payload["events"]:
            parsed = parse_completed_nba_event(raw, observed)
            if parsed is None:
                continue
            key = parsed["provider_fixture_id"]
            if key in conflicts:
                continue
            if key in rows and rows[key] != parsed:
                conflicts.add(key)
                rows.pop(key, None)
            else:
                rows[key] = parsed
        from providers.espn_identity_audit import audit_scoreboard_identity
        vetted_events = sorted(
            rows.values(),
            key=lambda row: (row["start_ts_utc"], row["provider_fixture_id"]),
        )
        report["identity_audit"] = audit_scoreboard_identity(vetted_events, date_yyyymmdd)
        return {
            "date_yyyymmdd": date_yyyymmdd,
            "observed_at_utc": now,
            "quality": report,
            "completed_events": vetted_events,
        }

    async def fetch_completed_nba_scoreboard_date(
        self, date_yyyymmdd: str,
    ) -> List[Dict[str, Any]]:
        """Read a date-scoped ESPN scoreboard without writing outcomes.

        ESPN schedule dates may differ from UTC calendar dates.
        """
        if (not isinstance(date_yyyymmdd, str)
                or len(date_yyyymmdd) != 8
                or not date_yyyymmdd.isascii()
                or not date_yyyymmdd.isdigit()):
            raise ValueError("date must be YYYYMMDD")
        try:
            datetime.strptime(date_yyyymmdd, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("invalid calendar date") from exc
        payload = await self._get_json(
            f"{ESPN_BASE}/scoreboard?dates={date_yyyymmdd}"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            return []
        rows: Dict[str, Dict[str, Any]] = {}
        conflicts: set[str] = set()
        for event in payload["events"]:
            parsed = parse_completed_nba_event(event)
            if parsed is not None:
                source_id = parsed["provider_fixture_id"]
                if source_id in conflicts:
                    continue
                if source_id in rows and rows[source_id] != parsed:
                    conflicts.add(source_id)
                    rows.pop(source_id, None)
                else:
                    rows[source_id] = parsed
        return sorted(rows.values(), key=lambda row: (
            row["start_ts_utc"], row["provider_fixture_id"]
        ))

    async def fetch_completed_nba_events(
        self, team_input: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Fetch and strictly parse completed NBA events for a resolved team.

        No results are persisted here. The caller must match provider IDs
        and independently validate prediction provenance before evaluation.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        ref = await self.resolve_team(team_input)
        if not ref:
            return []
        payload = await self._get_json(f"{ESPN_BASE}/teams/{ref['id']}/schedule")
        if not isinstance(payload, dict):
            return []
        events = payload.get("events")
        if not isinstance(events, list):
            return []
        by_id: Dict[str, Dict[str, Any]] = {}
        conflicts: set[str] = set()
        for event in events:
            parsed = parse_completed_nba_event(event)
            if parsed is None:
                continue
            if ref["id"] not in (parsed["home_team_id"], parsed["away_team_id"]):
                continue
            source_id = parsed["provider_fixture_id"]
            if source_id in conflicts:
                continue
            if source_id in by_id and by_id[source_id] != parsed:
                conflicts.add(source_id)
                by_id.pop(source_id, None)
            else:
                by_id[source_id] = parsed
        return sorted(
            by_id.values(), key=lambda row: (
                row["start_ts_utc"], row["provider_fixture_id"]
            )
        )[-limit:]

    # -------------------------------------------------
    # FETCH RECENT GAMES (PROD SAFE)
    # -------------------------------------------------
    async def fetch_pace_evidence(self, game: dict, now_utc=None) -> Optional[dict]:
        """Fetch actual team totals and derive a labeled, auditable estimate."""
        fixture_id = game.get("provider_fixture_id") if isinstance(game, dict) else None
        if not isinstance(fixture_id, str) or not fixture_id.isascii() or not fixture_id.isdigit():
            return None
        payload = await self._get_json(f"{ESPN_BASE}/summary?event={fixture_id}")
        return estimate_pace_from_summary(payload, game, now_utc)

    async def fetch_team_recent_games(
        self, league: str, team: str, n_games: int
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Dönen format TeamBaselineBootstrapper ile uyumlu:
        {
            ts_utc, pts_for, pts_against, pace, home
        }
        """

        if (league or "").upper().strip() != "NBA":
            return None

        ref = await self.resolve_team(team)
        if not ref:
            logger.info("[ESPN-DIAG] stage=resolve league=NBA team=%s outcome=unresolved", team)
            return None

        team_id = ref["id"]
        url = f"{ESPN_BASE}/teams/{team_id}/schedule"

        js = await self._get_json(url)
        if not js:
            logger.info("[ESPN-DIAG] stage=schedule team=%s outcome=empty_or_http_error", ref["abbr"])
            return None

        events = js.get("events")
        if not isinstance(events, list):
            logger.info("[ESPN-DIAG] stage=schedule team=%s outcome=events_not_list", ref["abbr"])
            return None
        logger.info("[ESPN-DIAG] stage=schedule team=%s raw_events=%d", ref["abbr"], len(events))

        # Use the shared strict completed-event parser. ESPN finals typically
        # use state=post with completed=true; never accept scheduled/live games.
        completed: List[Dict[str, Any]] = []
        for ev in events:
            parsed = parse_completed_nba_event(ev)
            if parsed is None:
                continue
            if team_id not in (parsed["home_team_id"], parsed["away_team_id"]):
                continue
            completed.append(parsed)

        logger.info("[ESPN-DIAG] stage=completed team=%s completed_events=%d", ref["abbr"], len(completed))
        if not completed:
            return None

        completed.sort(key=lambda ev: (ev["start_ts_utc"], ev["provider_fixture_id"]))
        completed = completed[-int(n_games):]

        out: List[Dict[str, Any]] = []
        for ev in completed:
            is_home = ev["home_team_id"] == team_id
            pf = ev["actual_home"] if is_home else ev["actual_away"]
            pa = ev["actual_away"] if is_home else ev["actual_home"]
            # Neutral placeholder; scores do not measure possessions.
            pace = 100.0
            out.append({
                "ts_utc": ev["start_ts_utc"],
                "pts_for": float(pf),
                "pts_against": float(pa),
                "pace": pace,
                "home": is_home,
            })

        logger.info("[ESPN-DIAG] stage=parsed team=%s usable_games=%d selected_completed=%d", ref["abbr"], len(out), len(completed))
        return out if out else None 
