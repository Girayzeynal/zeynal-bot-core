"""Read-only EuroLeague/EuroCup source validation; no calibrated profiles or writes."""
from copy import deepcopy
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import re
import time
from uuid import UUID

import aiohttp

BASE = "https://api-live.euroleague.net/v2/competitions"
COMPETITIONS = {"EUROLEAGUE": ("E", "EuroLeague"), "EUROCUP": ("U", "EuroCup")}
PACE_METHOD = "EUROLEAGUE_LIVE_BOXSCORE_044_40_V1"
BASELINE_CACHE_SECONDS = 60
STAT_FIELDS = ("points", "fieldGoalsMade2", "fieldGoalsAttempted2", "fieldGoalsMade3",
               "fieldGoalsAttempted3", "fieldGoalsMadeTotal", "fieldGoalsAttemptedTotal",
               "freeThrowsMade", "freeThrowsAttempted", "offensiveRebounds", "turnovers")


def identity(league, year):
    if not isinstance(league, str) or type(year) is not int or not 2000 <= year <= 2100:
        raise ValueError("Explicit competition and starting season year required")
    canonical = league.upper().strip().replace(" ", "")
    if canonical not in COMPETITIONS:
        raise ValueError("Only EuroLeague and EuroCup are supported; FIBA EuroCup is distinct")
    code, name = COMPETITIONS[canonical]
    return canonical, code, name, f"{code}{year}"


def _season(payload, league, year):
    _, code, name, season = identity(league, year)
    if (payload["code"] != season or payload["competitionCode"] != code
            or type(payload["year"]) is not int or payload["year"] != year
            or payload["alias"] != f"{year}-{str(year+1)[-2:]}"
            or payload["name"].casefold() != f"{name} {year}-{str(year+1)[-2:]}".casefold()):
        raise ValueError("Competition/season identity mismatch")


def _count(value):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < 0 or value > 100000 or int(value) != value):
        raise ValueError("Missing or malformed statistic")
    return int(value)


def parse_game(raw, *, league, year, observed_at_utc):
    """Validate explicit UTC identity and completed-score evidence, never local dates."""
    try:
        canonical, code, _, season = identity(league, year)
        _season(raw["season"], league, year)
        game_code = raw["gameCode"]
        if type(game_code) is not int or not 1 <= game_code <= 10000:
            return None
        fixture_id = f"{season}_{game_code}"
        if raw["identifier"] != fixture_id or str(UUID(raw["id"])) != raw["id"]:
            return None
        if (raw["confirmedDate"] is not True or raw["confirmedHour"] is not True
                or raw["gameStatus"] != "Confirmed" or type(raw["played"]) is not bool
                or type(observed_at_utc) is not int or not 0 < observed_at_utc <= int(time.time())):
            return None
        date = datetime.fromisoformat(raw["utcDate"].replace("Z", "+00:00"))
        if date.tzinfo is None or date.utcoffset().total_seconds() != 0:
            return None
        if not datetime(year, 7, 1, tzinfo=timezone.utc) <= date < datetime(year+1, 7, 1, tzinfo=timezone.utc):
            return None
        clubs = {side: raw[side]["club"] for side in ("local", "road")}
        for club in clubs.values():
            if (not re.fullmatch(r"[A-Z0-9]{1,8}", club["code"])
                    or club["isVirtual"] is not False or not club["name"].strip()):
                return None
        if clubs["local"]["code"] == clubs["road"]["code"]:
            return None
        if not re.fullmatch(r"[A-Z0-9]{1,4}", raw["phaseType"]["code"]):
            return None
        result = dict(provider="EUROLEAGUE_LIVE", league=canonical, competition_code=code,
            season_code=season, provider_fixture_id=fixture_id, provider_game_uuid=raw["id"],
            game_code=game_code, start_ts_utc=int(date.timestamp()),
            home_team_id=clubs["local"]["code"], away_team_id=clubs["road"]["code"],
            status="PLAYED" if raw["played"] else "UNPLAYED", phase=raw["phaseType"]["code"])
        if not raw["played"]:
            # A confirmed fixture with 0-0 is not a completed game or a prediction.
            return result
        if date.timestamp() >= observed_at_utc:
            return None
        scores, periods = {}, {}
        for side in ("local", "road"):
            scores[side] = _count(raw[side]["score"])
            part = raw[side]["partials"]
            periods[side] = [_count(part[f"partials{i}"]) for i in range(1, 5)]
            overtime = part["extraPeriods"]
            if not isinstance(overtime, dict) or set(overtime) != {str(i+1) for i in range(len(overtime))}:
                return None
            periods[side] += [_count(overtime[str(i+1)]) for i in range(len(overtime))]
            if sum(periods[side]) != scores[side] or scores[side] > 250:
                return None
        n = len(periods["local"])
        if n != len(periods["road"]) or n > 12 or scores["local"] == scores["road"]:
            return None
        if any(sum(periods["local"][:i]) != sum(periods["road"][:i]) for i in range(4, n)):
            return None  # Every extra period requires a preceding tie.
        result.update(actual_home=scores["local"], actual_away=scores["road"],
                      duration_minutes=40+5*(n-4), scope="FINAL_WITH_OT")
        return result
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def audit_catalog(competition, season, payload, *, league, year, observed_at_utc):
    canonical, code, name, _ = identity(league, year)
    if not all(isinstance(item, dict) for item in (competition, season, payload)):
        raise ValueError("Malformed competition/season response")
    try:
        if competition.get("code") != code or competition.get("name", "").casefold() != name.casefold():
            raise ValueError("Official competition mapping disagrees")
        _season(season, league, year)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed competition/season metadata") from exc
    if (not isinstance(payload.get("data"), list) or type(payload.get("total")) is not int
            or len(payload["data"]) != payload["total"]):
        raise ValueError("Incomplete or malformed season collection")
    groups, uuid_groups, conflicts, invalid = {}, {}, set(), 0
    for raw in payload["data"]:
        parsed = parse_game(raw, league=canonical, year=year, observed_at_utc=observed_at_utc)
        if parsed is None:
            invalid += 1
            continue
        key = parsed["provider_fixture_id"]
        groups.setdefault(key, []).append((parsed, raw))
        uuid_groups.setdefault(parsed["provider_game_uuid"], set()).add(key)
    # A UUID reused by two season-scoped identities is also ambiguous.
    for key, rows in groups.items():
        if any(row[0] != rows[0][0] for row in rows):
            conflicts.add(key)
    for keys in uuid_groups.values():
        if len(keys) > 1:
            for key in keys:
                conflicts.add(key)
    games = [rows[0][0] for key, rows in groups.items() if key not in conflicts]
    duplicates = sum(len(rows)-1 for key, rows in groups.items() if key not in conflicts)
    conflicting_records = sum(len(rows) for key, rows in groups.items() if key in conflicts)
    if len(games) + invalid + duplicates + conflicting_records != len(payload["data"]):
        raise RuntimeError("Season coverage reconciliation failed")
    return dict(league=canonical, games=sorted(games, key=lambda g: (g["start_ts_utc"], g["game_code"])),
                raw_games={g["provider_fixture_id"]: deepcopy(groups[g["provider_fixture_id"]][0][1]) for g in games},
                total_raw=len(payload["data"]), accepted_unique=len(games), invalid_records=invalid,
                duplicate_identical=duplicates, conflicting_records=conflicting_records,
                conflicting_fixture_ids=sorted(conflicts))


def estimate_pace(raw_game, stats, *, league, year, observed_at_utc):
    """Estimate possessions per 40 minutes from reconciled team totals, never 48."""
    game = parse_game(raw_game, league=league, year=year, observed_at_utc=observed_at_utc)
    if game is None or game["status"] != "PLAYED":
        return None
    try:
        inputs, player_ids = {}, set()
        for side, label, team_id in (("local", "home", game["home_team_id"]),
                                     ("road", "away", game["away_team_id"])):
            block = stats[side]
            total = {key: _count(block["total"][key]) for key in STAT_FIELDS}
            if _count(block["total"]["timePlayed"]) != game["duration_minutes"] * 60:
                return None
            summed = {key: _count(block["team"][key]) for key in STAT_FIELDS}
            if not isinstance(block["players"], list) or not block["players"]:
                return None
            for player in block["players"]:
                membership = player["player"]
                _season(membership["season"], league, year)
                pid = membership["person"]["code"]
                if (membership["club"]["code"] != team_id or not isinstance(pid, str)
                        or not pid.strip() or pid in player_ids):
                    return None
                player_ids.add(pid)
                for key in STAT_FIELDS:
                    summed[key] += _count(player["stats"][key])
            if summed != total or total["points"] != game[f"actual_{label}"]:
                return None
            if (total["fieldGoalsMadeTotal"] != total["fieldGoalsMade2"] + total["fieldGoalsMade3"]
                    or total["fieldGoalsAttemptedTotal"] != total["fieldGoalsAttempted2"] + total["fieldGoalsAttempted3"]
                    or 2*total["fieldGoalsMade2"] + 3*total["fieldGoalsMade3"] + total["freeThrowsMade"] != total["points"]):
                return None
            for made, attempted in (("fieldGoalsMade2", "fieldGoalsAttempted2"),
                                     ("fieldGoalsMade3", "fieldGoalsAttempted3"),
                                     ("freeThrowsMade", "freeThrowsAttempted")):
                if total[made] > total[attempted]:
                    return None
            possessions = (total["fieldGoalsAttemptedTotal"] + 0.44*total["freeThrowsAttempted"]
                           - total["offensiveRebounds"] + total["turnovers"])
            if possessions <= 0:
                return None
            inputs[label] = dict(fga=total["fieldGoalsAttemptedTotal"], fta=total["freeThrowsAttempted"],
                                 orb=total["offensiveRebounds"], total_turnovers=total["turnovers"],
                                 estimated_possessions=possessions)
        pace = sum(row["estimated_possessions"] for row in inputs.values()) / 2 * 40 / game["duration_minutes"]
        url = f"{BASE}/{game['competition_code']}/seasons/{game['season_code']}/games/{game['game_code']}"
        evidence = dict(method=PACE_METHOD, kind="BOX_SCORE_ESTIMATE", pace=pace, game=game,
                        duration_minutes=game["duration_minutes"], normalization_minutes=40,
                        inputs=inputs, observed_at_utc=observed_at_utc, source_url=url, stats_url=url+"/stats")
        compact_game = {key: deepcopy(raw_game[key]) for key in
            ("id", "identifier", "gameCode", "season", "confirmedDate", "confirmedHour",
             "gameStatus", "played", "utcDate", "phaseType")}
        for side in ("local", "road"):
            compact_game[side] = dict(score=raw_game[side]["score"],
                partials=deepcopy(raw_game[side]["partials"]),
                club={key: raw_game[side]["club"][key] for key in ("code", "name", "isVirtual")})
        compact_stats = {side: dict(total={key: stats[side]["total"][key] for key in (*STAT_FIELDS, "timePlayed")},
            team={key: stats[side]["team"][key] for key in STAT_FIELDS}, players=[
                dict(player=dict(person={"code": row["player"]["person"]["code"]},
                     club={"code": row["player"]["club"]["code"]}, season=deepcopy(row["player"]["season"])),
                     stats={key: row["stats"][key] for key in STAT_FIELDS})
                for row in stats[side]["players"]]) for side in ("local", "road")}
        snapshot = dict(schema_version=1, league=game["league"], year=year,
                        observed_at_utc=observed_at_utc, game=compact_game, stats=compact_stats)
        evidence["snapshot"] = snapshot
        evidence["sha256"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        return evidence
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def replay_pace_evidence(evidence):
    """Replay research observations only. Hashes do not establish provider authenticity."""
    try:
        snapshot = evidence["snapshot"]
        if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1:
            raise ValueError("Unsupported Euroleague Live observation schema")
        replayed = estimate_pace(snapshot["game"], snapshot["stats"], league=snapshot["league"],
            year=snapshot["year"], observed_at_utc=snapshot["observed_at_utc"])
        if replayed is None or replayed != evidence:
            raise ValueError("Euroleague Live observation replay/integrity mismatch")
        return replayed["game"]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed Euroleague Live observation") from exc


class EuroleagueLiveAdapter:
    def __init__(self, session=None, *, baseline_season_year=None, allow_estimated_pace=False):
        if type(allow_estimated_pace) is not bool:
            raise ValueError("Estimated-pace adoption requires an explicit boolean")
        if baseline_season_year is not None:
            identity("EUROLEAGUE", baseline_season_year)
        if allow_estimated_pace and baseline_season_year is None:
            raise ValueError("Estimated baselines require an explicit season year")
        self._session = session
        self._owns_session = session is None
        self.baseline_season_year = baseline_season_year
        self.allow_estimated_pace = allow_estimated_pace
        self.request_diagnostics = []
        self.baseline_diagnostics = {"status": "not_requested"}
        self._request_not_before = 0.0
        self._baseline_catalogs = {}
        self._baseline_evidence = {}

    def _request_diagnostic(self, url, outcome, http_status=None):
        self.request_diagnostics.append(dict(endpoint=url.split("?")[0], outcome=outcome,
            http_status=http_status, observed_at_utc=int(time.time())))
        del self.request_diagnostics[:-128]

    async def _get_json(self, url):
        if time.monotonic() < self._request_not_before:
            self._request_diagnostic(url, "rate_limit_cooldown")
            return None
        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=15))
                self._owns_session = True
            async with self._session.get(url) as response:
                if response.status != 200:
                    self._request_diagnostic(url, "http_error", response.status)
                    if response.status == 429:
                        retry_after = response.headers.get("Retry-After", "")
                        # This is a local minimum policy, not a fabricated server hint.
                        delay = 60
                        try:
                            if isinstance(retry_after, str) and retry_after.isascii() and retry_after.isdigit():
                                delay = max(delay, int(retry_after))
                            elif isinstance(retry_after, str) and retry_after:
                                deadline = parsedate_to_datetime(retry_after)
                                if deadline.tzinfo is not None:
                                    delay = max(delay, math.ceil(deadline.timestamp()-time.time()))
                        except (ValueError, TypeError, OverflowError):
                            pass
                        self._request_not_before = max(self._request_not_before, time.monotonic()+delay)
                    return None
                try:
                    result = await response.json()
                except (aiohttp.ContentTypeError, ValueError, TypeError):
                    self._request_diagnostic(url, "invalid_json", response.status)
                    return None
                self._request_diagnostic(url, "ok" if isinstance(result, dict) else "invalid_payload", response.status)
                return result if isinstance(result, dict) else None
        except (aiohttp.ClientError, TimeoutError):
            self._request_diagnostic(url, "transport_error")
            return None

    async def aclose(self):
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def fetch_catalog(self, league, year):
        canonical, code, _, season = identity(league, year)
        competition, metadata, games = await asyncio.gather(
            self._get_json(f"{BASE}/{code}"), self._get_json(f"{BASE}/{code}/seasons/{season}"),
            self._get_json(f"{BASE}/{code}/seasons/{season}/games"))
        if any(item is None for item in (competition, metadata, games)):
            raise RuntimeError("Competition/season data unavailable; no empty fallback")
        return audit_catalog(competition, metadata, games, league=canonical, year=year,
                             observed_at_utc=int(time.time()))

    async def fetch_pace_evidence(self, raw_game, *, league, year):
        parsed = parse_game(raw_game, league=league, year=year, observed_at_utc=int(time.time()))
        if parsed is None or parsed["status"] != "PLAYED":
            return None
        key = (parsed["season_code"], parsed["provider_fixture_id"])
        cached = self._baseline_evidence.get(key)
        if (self.allow_estimated_pace and cached and time.monotonic()-cached[0] < BASELINE_CACHE_SECONDS
                and cached[1]["game"] == parsed):
            return deepcopy(cached[1])  # Preserve original observation time.
        url = f"{BASE}/{parsed['competition_code']}/seasons/{parsed['season_code']}/games/{parsed['game_code']}"
        game, stats = await asyncio.gather(self._get_json(url), self._get_json(url+"/stats"))
        observed = int(time.time())
        if parse_game(game, league=league, year=year, observed_at_utc=observed) != parsed or stats is None:
            return None
        evidence = estimate_pace(game, stats, league=league, year=year, observed_at_utc=observed)
        if self.allow_estimated_pace and evidence is not None:
            self._baseline_evidence[key] = (time.monotonic(), deepcopy(evidence))
        return evidence

    async def _baseline_catalog(self, league):
        canonical, _, _, season = identity(league, self.baseline_season_year)
        cached = self._baseline_catalogs.get(season)
        if cached and time.monotonic()-cached[0] < BASELINE_CACHE_SECONDS:
            return cached[1]
        catalog = await self.fetch_catalog(canonical, self.baseline_season_year)
        self._baseline_catalogs[season] = (time.monotonic(), catalog)
        return catalog

    @staticmethod
    def _resolve_catalog_team(catalog, team_input):
        if not isinstance(team_input, str) or not team_input.strip():
            return None
        text = team_input.strip().casefold()
        matches = set()
        for raw in catalog["raw_games"].values():
            for side in ("local", "road"):
                club = raw[side]["club"]
                if text in (club["code"].casefold(), club["name"].strip().casefold()):
                    matches.add(club["code"])
        return next(iter(matches)) if len(matches) == 1 else None

    async def resolve_team_abbr(self, league, team_input):
        if not self.allow_estimated_pace:
            return None
        try:
            identity(league, self.baseline_season_year)
        except ValueError:
            return None
        catalog = await self._baseline_catalog(league)
        if catalog["invalid_records"] or catalog["conflicting_fixture_ids"]:
            return None
        return self._resolve_catalog_team(catalog, team_input)

    async def fetch_team_recent_games(self, league, team, n_games):
        """Explicit research opt-in; no guessed season, names, pace or incomplete sample."""
        if not self.allow_estimated_pace:
            self.baseline_diagnostics = {"status": "estimated_pace_disabled"}
            return None
        if type(n_games) is not int or not 1 <= n_games <= 20:
            raise ValueError("n_games must be an integer from one to twenty")
        try:
            canonical, _, _, _ = identity(league, self.baseline_season_year)
        except ValueError:
            return None
        self.request_diagnostics.clear()
        self.baseline_diagnostics = {"status": "catalog_requested", "team": team}
        try:
            catalog = await self._baseline_catalog(canonical)
        except (RuntimeError, ValueError):
            self.baseline_diagnostics = dict(status="catalog_unavailable_or_invalid", team=team,
                request_failures=[dict(item) for item in self.request_diagnostics if item["outcome"] != "ok"])
            raise
        if catalog["invalid_records"] or catalog["conflicting_fixture_ids"]:
            self.baseline_diagnostics = {"status": "catalog_rejected", "team": team}
            return None
        team_id = self._resolve_catalog_team(catalog, team)
        if team_id is None:
            self.baseline_diagnostics = {"status": "unresolved_or_ambiguous_team", "team": team}
            return None
        selected = [game for game in catalog["games"]
                    if game["status"] == "PLAYED" and game["phase"] == "RS"
                    and team_id in (game["home_team_id"], game["away_team_id"])][-n_games:]
        rows = []
        for game in selected:
            evidence = await self.fetch_pace_evidence(catalog["raw_games"][game["provider_fixture_id"]],
                                                      league=canonical, year=self.baseline_season_year)
            if evidence is None:
                self.baseline_diagnostics = dict(status="selected_game_unavailable_or_rejected", team=team_id,
                    fixture_id=game["provider_fixture_id"], selected_games=len(selected),
                    collected_before_failure=len(rows),
                    request_failures=[dict(item) for item in self.request_diagnostics if item["outcome"] != "ok"])
                return None  # Never silently drop a selected game to improve coverage.
            home = game["home_team_id"] == team_id
            rows.append(dict(ts_utc=game["start_ts_utc"], home=home,
                pts_for=game["actual_home"] if home else game["actual_away"],
                pts_against=game["actual_away"] if home else game["actual_home"],
                pace=evidence["pace"], pace_kind="BOX_SCORE_ESTIMATE", pace_evidence=evidence,
                game_id=game["provider_fixture_id"], source=PACE_METHOD,
                timestamp_precision="exact", season_code=game["season_code"]))
        self.baseline_diagnostics = dict(status="records_returned" if rows else "no_completed_regular_season_history",
                                         team=team_id, selected_games=len(selected), returned_games=len(rows))
        return rows or None
