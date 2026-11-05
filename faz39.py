"""Pre-window readiness and an armed, network-free prospective capture path.

This is an opt-in development tool. It installs no scheduler and never deploys.
FAZ33's score engines, packet validator, transaction and immutable tables are reused.
"""
import argparse
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp

from faz25 import exclusive
from faz32 import read_store
from faz33 import Runner, compact_schedule
from faz34 import cut_proofs
from faz35 import validate_config
from faz37 import ClockGuard
from nba_research_store import validate_summary
from nba_season_2027 import parse_scheduled
from prediction_inputs import canonical_json, digest
from prospective_cuts import CutLedger, HORIZONS, GRACE, inspect
from providers.espn_adapter import ESPNAdapter, ESPN_BASE
from providers.espn_pace_evidence import capture_pace_evidence

REPO = 'Girayzeynal/zeynal-bot-core'
GITHUB = 'https://api.github.com/repos/' + REPO
UTC_URL = 'https://timeapi.io/api/time/current/zone?timeZone=UTC'
MAX_LEAD = 120
MIN_ARM_LEAD = 5
MAX_RTT = 2
MAX_CLOCK_ERROR = 2
SOURCE_BUDGET_SECONDS = 1


class Timings:
    """Bounded descriptive measurements, including failed operations; never an SLA."""
    def __init__(self):
        self.samples = {}; self.errors = {}; self.dropped = {}

    @contextmanager
    def measure(self, name):
        began = time.perf_counter_ns()
        try:
            yield
        except BaseException:
            self.errors[name] = self.errors.get(name, 0) + 1
            raise
        finally:
            self.record(name, max(0, time.perf_counter_ns() - began) / 1e6)

    def record(self, name, elapsed_ms):
        values = self.samples.setdefault(name, [])
        if len(values) < 4096:
            values.append(elapsed_ms)
        else:
            self.dropped[name] = self.dropped.get(name, 0) + 1

    def summary(self):
        result = {}
        for name, samples in self.samples.items():
            values = sorted(samples)
            result[name] = dict(count=len(values), errors=self.errors.get(name, 0),
                dropped=self.dropped.get(name, 0), max_ms=values[-1],
                **{'p' + str(p) + '_ms': values[math.ceil(len(values) * p / 100) - 1]
                   for p in (50, 95, 99)})
        return result


class Refused(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def local_source(*, budget_seconds=SOURCE_BUDGET_SECONDS):
    """No remote calls. Refuse dirty or untracked Python code and pin this branch."""
    repo = Path(__file__).resolve().parent
    require(type(budget_seconds) in (int, float) and math.isfinite(budget_seconds)
            and 0 < budget_seconds <= SOURCE_BUDGET_SECONDS, 'INVALID_SOURCE_TIME_BUDGET')
    deadline = time.perf_counter() + budget_seconds
    def remaining():
        seconds = deadline - time.perf_counter()
        require(seconds > 0, 'SOURCE_VERIFICATION_TIMEOUT')
        return seconds
    def git(*args, binary=False):
        try:
            value = subprocess.check_output(['git', *args], cwd=repo,
                text=not binary, timeout=remaining())
        except subprocess.TimeoutExpired as exc:
            raise Refused('SOURCE_VERIFICATION_TIMEOUT') from exc
        except subprocess.CalledProcessError as exc:
            raise Refused('SOURCE_GIT_FAILED') from exc
        remaining()
        return value if binary else value.strip()
    branch, sha = git('branch', '--show-current'), git('rev-parse', 'HEAD')
    require(branch.startswith('feature/faz39-'), 'FAZ39_DEVELOPMENT_BRANCH_REQUIRED')
    require(not git('status', '--porcelain', '--untracked-files=no'), 'SOURCE_DIRTY')
    untracked = git('ls-files', '--others', '--exclude-standard').splitlines()
    require(not any(p.endswith('.py') for p in untracked), 'UNTRACKED_PYTHON_SOURCE')
    # Imported files must also equal the committed source, even with skip-worktree.
    for name in ('faz39.py', 'faz33.py', 'prospective_cuts.py', 'faz37.py'):
        expected = git('show', 'HEAD:' + name, binary=True)
        require((repo / name).read_bytes() == expected, 'EXECUTED_SOURCE_DIFFERS')
        remaining()
    return dict(branch=branch, sha=sha)


class PublicSources:
    """Free HTTPS GETs only; explicit errors, bounded size/time, inherited proxy."""
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(trust_env=True,
            timeout=aiohttp.ClientTimeout(total=10), headers={
                'User-Agent': 'zeynal-faz39-research', 'Cache-Control': 'no-cache'})
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def fetch(self, url):
        require(url.startswith('https://'), 'HTTPS_REQUIRED')
        began, mono = time.time(), time.monotonic()
        try:
            async with self.session.get(url, allow_redirects=False) as response:
                require(response.status == 200, 'HTTP_' + str(response.status))
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    require(size <= 8 * 1024 * 1024, 'SOURCE_TOO_LARGE')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                body = raw.decode('utf-8')
        except asyncio.TimeoutError as exc:
            raise Refused('TIMEOUT') from exc
        except (aiohttp.ClientError, OSError) as exc:
            raise Refused('NETWORK_UNAVAILABLE') from exc
        return dict(source_url=url, http_status=200, body=body,
            response_sha256=hashlib.sha256(raw).hexdigest(),
            request_started_utc=began, observed_utc=time.time(),
            elapsed_seconds=time.monotonic() - mono)


def source_body(proof, url):
    require(proof['source_url'] == url and proof['http_status'] == 200,
            'SOURCE_URL_OR_HTTP_STATUS')
    require(hashlib.sha256(proof['body'].encode()).hexdigest() == proof['response_sha256'],
            'SOURCE_HASH_MISMATCH')
    require(all(type(proof[k]) in (int, float) and math.isfinite(proof[k])
                for k in ('request_started_utc', 'observed_utc', 'elapsed_seconds')),
            'INVALID_SOURCE_CLOCK')
    require(0 < proof['request_started_utc'] <= proof['observed_utc'] and
            0 <= proof['elapsed_seconds'] <= 10, 'INVALID_SOURCE_CHRONOLOGY')
    return proof['body']


def source_json(proof, url):
    return json.loads(source_body(proof, url))


def utc_anchor(proof):
    try:
        raw = source_json(proof, UTC_URL)
    except json.JSONDecodeError as exc:
        raise Refused('UTC_SCHEMA_CHANGED') from exc
    require(isinstance(raw, dict) and isinstance(raw.get('dateTime'), str), 'UTC_SCHEMA_CHANGED')
    require(raw.get('timeZone') == 'UTC', 'UTC_ZONE_UNVERIFIED')
    try:
        stamp = datetime.fromisoformat(raw['dateTime'].replace('Z', '+00:00'))
    except ValueError as exc:
        raise Refused('UTC_SCHEMA_CHANGED') from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    require(stamp.utcoffset().total_seconds() == 0, 'UTC_OFFSET_UNVERIFIED')
    require(proof['elapsed_seconds'] <= MAX_RTT and
            abs(proof['observed_utc'] - stamp.timestamp()) <= MAX_CLOCK_ERROR,
            'UTC_ATTESTATION_FAILED')
    return stamp.timestamp()


def schedule_evidence(proof, fixture_id, team_ids):
    raw = source_json(proof, ESPN_BASE + '/summary?event=' + fixture_id)
    event = deepcopy(raw['header'])
    event['date'] = event['competitions'][0]['date']
    event.setdefault('status', deepcopy(event['competitions'][0]['status']))
    event = compact_schedule(event)
    fixture = parse_scheduled(event, team_ids)
    require(fixture['provider_fixture_id'] == fixture_id, 'ESPN_ID_MISMATCH')
    return fixture, dict(event=event, sha256=digest(event),
        source_url=proof['source_url'], source_response_sha256=proof['response_sha256'],
        source_observed_utc=int(proof['observed_utc']), ingested_utc=int(proof['observed_utc']))


def official_game(proof, fixture, directory):
    day = datetime.fromtimestamp(fixture['start_ts_utc'], ZoneInfo('America/New_York')).date()
    html = source_body(proof, 'https://www.nba.com/games?date=' + day.isoformat())
    match = re.search(r'<script[^>]*id=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>', html, re.S)
    require(match is not None, 'OFFICIAL_SCHEDULE_UNAVAILABLE')
    try:
        data = json.loads(match.group(1))['props']['pageProps']
        require(isinstance(data, dict), 'OFFICIAL_SCHEDULE_SCHEMA_CHANGED')
    except (ValueError, KeyError, TypeError) as exc:
        raise Refused('OFFICIAL_SCHEDULE_SCHEMA_CHANGED') from exc
    require(data.get('selectedDate', day.isoformat()) == day.isoformat(), 'OFFICIAL_DAY_CONFLICT')
    found = []
    def walk(value):
        if isinstance(value, dict):
            home, away = value.get('homeTeam'), value.get('awayTeam')
            if (isinstance(home, dict) and isinstance(away, dict)
                    and home.get('teamTricode') == directory[fixture['home_team_id']]['abbr']
                    and away.get('teamTricode') == directory[fixture['away_team_id']]['abbr']
                    and 'gameId' in value):
                found.append(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(data)
    require(len(found) == 1, 'OFFICIAL_FIXTURE_AMBIGUOUS_OR_MISSING')
    game = found[0]
    try:
        stamp = datetime.fromisoformat(game['gameTimeUtc'].replace('Z', '+00:00'))
        require(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0,
                'OFFICIAL_START_TIMEZONE_UNVERIFIED')
        require(type(game['gameStatus']) is int and game['gameStatus'] == 1 and
                game['seasonYear'] == '2026-27' and game['seasonType'] == 'Regular Season' and
                stamp.timestamp() == fixture['start_ts_utc'], 'OFFICIAL_START_OR_STATUS_CONFLICT')
    except Refused:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Refused('OFFICIAL_SCHEDULE_SCHEMA_CHANGED') from exc
    return game


def verify_ci(proofs, source):
    ref = source_json(proofs['ref'], GITHUB + '/git/ref/heads/' + quote(source['branch'], safe='/'))
    require(ref['object']['sha'] == source['sha'], 'REMOTE_SHA_MISMATCH')
    runs = source_json(proofs['runs'], GITHUB + '/actions/runs?head_sha=' + source['sha'] + '&per_page=100')
    candidates = [r for r in runs['workflow_runs'] if r['head_sha'] == source['sha']
        and r['head_branch'] == source['branch'] and r['event'] == 'push'
        and r['path'].split('@')[0] == '.github/workflows/python-tests.yml']
    require(bool(candidates), 'CI_NOT_AVAILABLE')
    run = max(candidates, key=lambda r: (r['run_number'], r.get('run_attempt', 1), r['id']))
    require(run['status'] == 'completed' and run['conclusion'] == 'success', 'CI_NOT_SUCCESSFUL')
    jobs = source_json(proofs['jobs'], GITHUB + '/actions/runs/' + str(run['id']) + '/jobs?per_page=100')
    for name in ('unit-tests', 'docker-build'):
        found = [j for j in jobs['jobs'] if j['name'] == name and j.get('head_sha') == source['sha']
                 and j['run_id'] == run['id']]
        require(len(found) == 1 and found[0]['status'] == 'completed' and
                found[0]['conclusion'] == 'success', 'CI_JOB_NOT_SUCCESSFUL:' + name)
    return run['id']


def validate_ready(p, at):
    require(p['schema_version'] in (1, 2) and p['mode'] in ('PROSPECTIVE', 'SYNTHETIC_TEST'), 'READY_SCHEMA')
    if p['schema_version'] == 2:
        require(re.fullmatch('[0-9a-f]{32}', p['ledger_id']) is not None, 'READY_LEDGER_ID_INVALID')
    require(re.fullmatch('[0-9a-f]{40}', p['source']['sha']) is not None and
            p['source']['branch'].startswith('feature/faz39-'), 'READY_SOURCE_INVALID')
    fixture = p['fixture']
    cut = fixture['start_ts_utc'] - HORIZONS[p['horizon']]
    require(cut - MAX_LEAD <= p['ready_utc'] < cut - MIN_ARM_LEAD,
            'PRECHECKS_NOT_COMPLETED_BEFORE_WINDOW')
    require(p['ready_utc'] <= at, 'FUTURE_READINESS')
    for proof in p['proofs'].values():
        require(0 < proof['observed_utc'] <= p['ready_utc'] and
                0 <= at - proof['observed_utc'] <= GRACE, 'STALE_OR_FUTURE_READINESS_SOURCE')
    utc_anchor(p['proofs']['utc'])
    verify_ci(p['proofs'], p['source'])
    directory_raw = source_json(p['proofs']['directory'], ESPN_BASE + '/teams')
    directory = {r['team']['id']: dict(abbr=r['team']['abbreviation'], name=r['team']['displayName'])
                 for r in directory_raw['sports'][0]['leagues'][0]['teams']}
    require(directory == p['directory'], 'DIRECTORY_MISMATCH')
    require(set(directory) == set(p['team_ids']), 'DIRECTORY_TEAM_SET_MISMATCH')
    target, _ = schedule_evidence(p['proofs']['schedule'], fixture['provider_fixture_id'], set(p['team_ids']))
    require(target == fixture, 'READY_FIXTURE_CHANGED')
    official_game(p['proofs']['official'], fixture, directory)
    require(digest(p['history_rows']) == p['history_sha256'], 'FROZEN_HISTORY_HASH')
    ids, signatures = set(), set()
    counts = {fixture['home_team_id']: 0, fixture['away_team_id']: 0}
    for row in p['history_rows']:
        r = row['payload']
        require(digest(r) == row['sha256'] and row['observation_id'] ==
                digest(dict(summary=r['summary'], source_observed_utc=r['source_observed_utc'])), 'HISTORY_HASH')
        require(0 < r['source_observed_utc'] <= r['ingested_utc'] < p['ready_utc'], 'HISTORY_LEAK')
        facts = validate_summary(r['summary'], r['source_observed_utc'], set(p['team_ids']))
        e = facts['event']
        require(e == r['facts']['event'] and e['provider_fixture_id'] != fixture['provider_fixture_id'], 'HISTORY_FACTS')
        signature = (e['start_ts_utc'], tuple(sorted((e['home_team_id'], e['away_team_id']))))
        require(e['provider_fixture_id'] not in ids and signature not in signatures, 'DUPLICATE_HISTORY')
        ids.add(e['provider_fixture_id']); signatures.add(signature)
        require(p['ready_utc'] - 45 * 86400 < e['start_ts_utc'] < p['ready_utc'], 'HISTORY_OUTSIDE_WINDOW')
        if capture_pace_evidence(r['summary'], e, observed_at_utc=r['source_observed_utc']) is not None:
            for team in counts:
                counts[team] += int(team in (e['home_team_id'], e['away_team_id']))
    require(all(count >= 6 for count in counts.values()), 'REFERENCE_MIN_6_VERIFIED_GAMES')
    return p


class ReadyStore:
    def __init__(self, ledger):
        self.ledger = ledger
        with ledger.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS faz39_ready (sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            for op in ('UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS faz39_ready_no_{op} BEFORE {op} ON faz39_ready BEGIN SELECT RAISE(ABORT,'immutable FAZ39'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS faz39_ready_no_replace BEFORE INSERT ON faz39_ready WHEN EXISTS (SELECT 1 FROM faz39_ready WHERE sha256=NEW.sha256) BEGIN SELECT RAISE(ABORT,'immutable FAZ39 replacement'); END")
            db.execute('CREATE TABLE IF NOT EXISTS faz39_identity '
                       '(singleton INTEGER PRIMARY KEY CHECK(singleton=1), ledger_id TEXT NOT NULL UNIQUE)')
            for op in ('UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS faz39_identity_no_{op} BEFORE {op} ON faz39_identity BEGIN SELECT RAISE(ABORT,'immutable FAZ39 identity'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS faz39_identity_no_replace BEFORE INSERT ON faz39_identity WHEN EXISTS (SELECT 1 FROM faz39_identity) BEGIN SELECT RAISE(ABORT,'immutable FAZ39 identity replacement'); END")
            db.execute('BEGIN IMMEDIATE')
            identity = db.execute('SELECT ledger_id FROM faz39_identity WHERE singleton=1').fetchone()
            if identity is None:
                identity = (uuid.uuid4().hex,)
                db.execute('INSERT INTO faz39_identity VALUES (1,?)', identity)
            self.ledger_id = identity[0]
            require(re.fullmatch('[0-9a-f]{32}', self.ledger_id) is not None, 'LEDGER_ID_CORRUPT')

    def config_hash(self, config, version=2):
        if version == 1:
            return digest(config)
        return digest(dict(schema_version=2, ledger_id=self.ledger_id,
                           storage=validate_config(config)['storage']))

    def check_config(self, config, p):
        require(p['config_sha256'] == self.config_hash(config, p['schema_version']) and
                p['mode'] == self.ledger.mode and
                (p['schema_version'] == 1 or p['ledger_id'] == self.ledger_id), 'READY_CONFIG_MISMATCH')

    def put(self, p):
        validate_ready(p, time.time())
        require(p['mode'] == self.ledger.mode, 'READY_LEDGER_MODE_MISMATCH')
        if p['schema_version'] == 2:
            require(p['ledger_id'] == self.ledger_id, 'READY_LEDGER_ID_MISMATCH')
        sha, raw = digest(p), canonical_json(p)
        with self.ledger.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT payload FROM faz39_ready WHERE sha256=?', (sha,)).fetchone()
            if old:
                require(old == (raw,), 'READY_HASH_CONFLICT')
            else:
                require(time.time() < p['fixture']['start_ts_utc'] - HORIZONS[p['horizon']] - MIN_ARM_LEAD,
                        'PRECHECKS_FINISHED_TOO_LATE')
                db.execute('INSERT INTO faz39_ready VALUES (?,?)', (sha, raw))
        return sha

    def get(self, sha):
        with self.ledger.connect() as db:
            row = db.execute('SELECT payload FROM faz39_ready WHERE sha256=?', (sha,)).fetchone()
        require(row is not None, 'READINESS_NOT_FOUND')
        p = json.loads(row[0]); require(digest(p) == sha, 'READINESS_HASH_MISMATCH')
        return p


async def prepare(config, fixture_id, horizon, sources):
    """All network and expensive source/CI/history work happens before the cut."""
    c = validate_config(config)['collection']; source = local_source()
    ledger = CutLedger(c['database']); store = read_store(c['research_database'])
    with exclusive(ledger.path) as acquired:
        require(acquired, 'BUSY')
        ready_store = ReadyStore(ledger)
        proofs = {'schedule': await sources.fetch(ESPN_BASE + '/summary?event=' + fixture_id)}
        fixture, _ = schedule_evidence(proofs['schedule'], fixture_id, store.team_ids)
        cut = fixture['start_ts_utc'] - HORIZONS[horizon]
        require(cut - MAX_LEAD <= time.time() < cut - MIN_ARM_LEAD, 'PREPARE_OUTSIDE_PREWINDOW')
        proofs['directory'] = await sources.fetch(ESPN_BASE + '/teams')
        raw = source_json(proofs['directory'], ESPN_BASE + '/teams')
        directory = {r['team']['id']: dict(abbr=r['team']['abbreviation'], name=r['team']['displayName'])
                     for r in raw['sports'][0]['leagues'][0]['teams']}
        # Reuse the verified history importer, with no prediction generation here.
        api = ESPNAdapter()
        try:
            runner = Runner(ledger, store, api, model_sha=source['sha'])
            await asyncio.wait_for(runner.refresh_history(fixture),
                timeout=max(.001, cut - MIN_ARM_LEAD - time.time()))
        finally:
            await api.aclose()
        day = datetime.fromtimestamp(fixture['start_ts_utc'], ZoneInfo('America/New_York')).date()
        proofs['official'] = await sources.fetch('https://www.nba.com/games?date=' + day.isoformat())
        proofs['ref'] = await sources.fetch(GITHUB + '/git/ref/heads/' + quote(source['branch'], safe='/'))
        proofs['runs'] = await sources.fetch(GITHUB + '/actions/runs?head_sha=' + source['sha'] + '&per_page=100')
        runs = source_json(proofs['runs'], proofs['runs']['source_url'])['workflow_runs']
        candidates = [r for r in runs if r['head_sha'] == source['sha'] and r['head_branch'] == source['branch']
                      and r['event'] == 'push' and r['path'].split('@')[0] == '.github/workflows/python-tests.yml']
        require(bool(candidates), 'CI_NOT_AVAILABLE')
        latest = max(candidates, key=lambda r: (r['run_number'], r.get('run_attempt', 1), r['id']))
        proofs['jobs'] = await sources.fetch(GITHUB + '/actions/runs/' + str(latest['id']) + '/jobs?per_page=100')
        # Refresh the schedule at the END of preflight, not after the window opens.
        proofs['schedule'] = await sources.fetch(ESPN_BASE + '/summary?event=' + fixture_id)
        proofs['utc'] = await sources.fetch(UTC_URL)
        require(local_source() == source, 'SOURCE_CHANGED_DURING_PREPARE')
        now = time.time()
        rows = [r for r in store.select(int(now), 'PROSPECTIVE', 2027)
                if now - 45 * 86400 < r['payload']['facts']['event']['start_ts_utc'] < now]
        p = dict(schema_version=2, mode='PROSPECTIVE', ledger_id=ready_store.ledger_id,
                 config_sha256=ready_store.config_hash(config), original_config_sha256=digest(config), source=source,
                 fixture=fixture, horizon=horizon, ready_utc=now, proofs=proofs, directory=directory,
                 team_ids=sorted(store.team_ids), history_rows=rows, history_sha256=digest(rows))
        sha = ready_store.put(p)
        return dict(status='READY_BEFORE_CUT', receipt_sha256=sha, model_sha=source['sha'],
                    scheduled_cutoff_utc=cut, new_prospective_cuts=0)


class FrozenHistory:
    def __init__(self, p):
        self.team_ids = set(p['team_ids']); self.rows = deepcopy(p['history_rows'])

    def select(self, *args):
        return deepcopy(self.rows)


class CaptureGate:
    def __init__(self, ready, receipt_sha, utc_proof, source_check=None, *, clock_guard=None):
        self.ready = deepcopy(ready); self.receipt_sha = receipt_sha
        self.timings = Timings()
        self.utc_proof = deepcopy(utc_proof); self.source_check = source_check or local_source
        self.guard = clock_guard or ClockGuard()
        self.trusted_utc = utc_anchor(utc_proof)
        self.trusted_observed = utc_proof['observed_utc']
        self.trusted_at_start = self.trusted_utc + max(0, self.guard.start_wall - self.trusted_observed)
        self.cut = ready['fixture']['start_ts_utc'] - HORIZONS[ready['horizon']]
        require(time.time() < self.cut, 'PRECHECKS_NOT_READY_BEFORE_CUT')
        validate_ready(ready, time.time())
        require(utc_proof['observed_utc'] < self.cut and
                0 <= time.time() - utc_proof['observed_utc'] <= MAX_RTT, 'ARM_UTC_NOT_FRESH')
        with self.timings.measure('git_source_check'):
            require(self.source_check() == ready['source'], 'SOURCE_CHANGED_SINCE_PREPARE')
        require(digest(ready) == receipt_sha, 'READINESS_HASH_MISMATCH')

    def utc_bounds(self):
        elapsed = self.guard.last_mono - self.guard.start_mono
        estimate = self.trusted_at_start + elapsed
        return (estimate - MAX_CLOCK_ERROR,
                estimate + MAX_CLOCK_ERROR + self.utc_proof['elapsed_seconds'])

    def check(self, *, allow_wait=False):
        self.guard.check(); now = self.guard.last_wall
        require(digest(self.ready) == self.receipt_sha, 'READINESS_CHANGED_AFTER_ARM')
        require(now <= self.cut + GRACE and now < self.ready['fixture']['start_ts_utc'], 'MISSED_CUT')
        require(0 <= now - self.trusted_observed <= GRACE, 'UTC_ATTESTATION_EXPIRED')
        lower, upper = self.utc_bounds()
        require(allow_wait or (now >= self.cut and lower >= self.cut), 'WAITING_FOR_CUT')
        require(upper <= self.cut + GRACE, 'UTC_WINDOW_UNCERTAIN')
        # Pure timestamp checks on already-validated evidence: no HTTP/CI/parsing here.
        require(all(0 <= now - p['observed_utc'] <= GRACE for p in self.ready['proofs'].values()),
                'READINESS_SOURCE_EXPIRED')
        with self.timings.measure('git_source_check'):
            require(self.source_check() == self.ready['source'], 'SOURCE_CHANGED_AFTER_ARM')
        # Source checks/digesting can themselves be delayed: never return their OLD time.
        self.guard.check(); now = self.guard.last_wall
        require(now <= self.cut + GRACE, 'MISSED_CUT')
        require(self.utc_bounds()[1] <= self.cut + GRACE, 'UTC_WINDOW_UNCERTAIN')
        require(now - self.trusted_observed <= GRACE and
                all(now - p['observed_utc'] <= GRACE for p in self.ready['proofs'].values()),
                'READINESS_SOURCE_EXPIRED')
        return int(now)


class TimedConnection(sqlite3.Connection):
    def execute(self, sql, *args, **kwargs):
        statement = sql.strip().upper()
        label = ('sqlite_begin_immediate' if statement.startswith('BEGIN IMMEDIATE') else
                 'sqlite_cut_insert' if statement.startswith('INSERT INTO FAZ33_CUTS') else None)
        if label is None:
            return super().execute(sql, *args, **kwargs)
        with self.timings.measure(label):
            return super().execute(sql, *args, **kwargs)


class EvidenceLedger(CutLedger):
    def __init__(self, path, mode, gate):
        self.gate = gate
        self.insert_gate_error = None
        super().__init__(path, mode, clock_check=gate.check)

    def connect(self):
        with self.gate.timings.measure('sqlite_connect'):
            db = sqlite3.connect(self.path, timeout=1, factory=TimedConnection)
        db.timings = self.gate.timings
        def final_gate(recorded):
            try:
                with self.gate.timings.measure('sqlite_final_gate'):
                    now = self.gate.check()
                    require(recorded == now, 'RECORDING_SECOND_CHANGED_BEFORE_INSERT')
                    return now
            except (ValueError, OSError) as exc:
                self.insert_gate_error = exc
                raise
        db.create_function('faz39_final_gate', 1, final_gate)
        # Runs INSIDE SQLite, after parameter serialization and after obtaining its
        # write lock. The reference table/old triggers are not altered.
        db.execute('''CREATE TEMP TRIGGER faz39_final_gate BEFORE INSERT ON main.faz33_cuts
                      BEGIN SELECT faz39_final_gate(NEW.recorded_utc); END''')
        return db

    def insert(self, packet):
        p = deepcopy(packet)
        require(p['fixture'] == self.gate.ready['fixture'] and
                p['horizon'] == self.gate.ready['horizon'] and
                p['model_sha'] == self.gate.ready['source']['sha'], 'UNARMED_TARGET_OR_MODEL')
        p['faz39'] = dict(receipt_sha256=self.gate.receipt_sha, readiness=self.gate.ready,
                         arm_utc_attestation=self.gate.utc_proof,
                         clock_evidence=self.gate.guard.evidence(),
                         utc_uncertainty_seconds=MAX_CLOCK_ERROR,
                         generation_utc_bounds=self.gate.utc_bounds())
        self.insert_gate_error = None
        try:
            return super().insert(p)
        except sqlite3.Error:
            if self.insert_gate_error is not None:
                raise self.insert_gate_error
            raise


class ArmedRunner(Runner):
    def __init__(self, ledger, gate):
        p = gate.ready
        super().__init__(ledger, FrozenHistory(p), None, model_sha=p['source']['sha'])
        self.gate = gate; self.directory = deepcopy(p['directory'])
        proof = p['proofs']['directory']
        self.directory_observation = dict(teams=self.directory, sha256=digest(self.directory),
            source_observed_utc=int(proof['observed_utc']), ingested_utc=int(proof['observed_utc']))

    def check_source(self):
        self.gate.check()

    async def recheck(self, fixture):
        self.gate.check()
        target, schedule = schedule_evidence(self.gate.ready['proofs']['schedule'],
                                            fixture['provider_fixture_id'], self.store.team_ids)
        require(target == fixture, 'CACHED_SCHEDULE_CONFLICT')
        return schedule


def existing_cut(ledger, ready, receipt_sha):
    """Read-only duplicate comparison; an unrelated prior record is NOT success."""
    fid, horizon = ready['fixture']['provider_fixture_id'], ready['horizon']
    with sqlite3.connect(Path(ledger.path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1) as db:
        row = db.execute('SELECT cutoff_utc,recorded_utc,payload,sha256 FROM faz33_cuts '
                         'WHERE fixture_id=? AND horizon=?', (fid, horizon)).fetchone()
        if row is None:
            return None
        cutoff, recorded, raw, sha = row
        p = json.loads(raw); binding = p.get('faz39', {})
        require(digest(p) == sha, 'EXISTING_CUT_HASH_MISMATCH')
        require(p['fixture'] == ready['fixture'] and p['horizon'] == horizon and
                p['model_sha'] == ready['source']['sha'] and p['usage'] == ready['mode'] and
                p['cutoff_utc'] == cutoff and binding.get('receipt_sha256') == receipt_sha and
                binding.get('readiness') == ready and digest(ready) == receipt_sha,
                'EXISTING_CUT_BINDING_CONFLICT')
        stored = db.execute('SELECT payload FROM faz39_ready WHERE sha256=?', (receipt_sha,)).fetchone()
        require(stored == (canonical_json(ready),), 'EXISTING_CUT_RECEIPT_CONFLICT')
    return dict(fixture_id=fid, horizon=horizon, cutoff_utc=cutoff, recorded_utc=recorded,
                model_sha=p['model_sha'], prediction_sha256=sha, receipt_sha256=receipt_sha)


async def capture_armed(runner):
    """One target, one transaction, no network, no history refresh or CI lookup."""
    p = runner.gate.ready; fid = p['fixture']['provider_fixture_id']; horizon = p['horizon']
    timings = runner.gate.timings
    def measured_proofs():
        with timings.measure('cut_proofs'):
            return cut_proofs(runner.ledger.path)
    began = time.perf_counter_ns()
    with exclusive(runner.ledger.path) as acquired:
        timings.record('application_lock', (time.perf_counter_ns() - began) / 1e6)
        if not acquired:
            return dict(status='BUSY', new_prospective_cuts=0, timings=timings.summary())
        before = measured_proofs()
        try:
            with timings.measure('ledger_has'):
                has = runner.ledger.has(fid, horizon)
            if has:
                with timings.measure('existing_cut_comparison'):
                    proof = existing_cut(runner.ledger, p, runner.gate.receipt_sha)
                require(proof is not None, 'EXISTING_CUT_DISAPPEARED')
                return dict(status='ALREADY_RECORDED', new_prospective_cuts=0,
                            existing_proof=proof, timings=timings.summary())
            runner.gate.check()
            result = await runner.capture(dict(fixture=p['fixture']), horizon, refresh=False)
        except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            # Do not infer zero writes after a failure: inspect the actual committed rows.
            after = measured_proofs()
            require(all(after.get(k) == v for k, v in before.items()), 'ORIGINAL_CUT_CHANGED')
            count = len(set(after) - set(before))
            return dict(status='REFUSED', reason=str(exc),
                        new_prospective_cuts=count if runner.ledger.mode == 'PROSPECTIVE' else 0,
                        new_synthetic_cuts=count if runner.ledger.mode == 'SYNTHETIC_TEST' else 0,
                        timings=timings.summary())
        after = measured_proofs()
        require(all(after.get(k) == v for k, v in before.items()), 'ORIGINAL_CUT_CHANGED')
        count = len(set(after) - set(before))
        return dict(result, new_prospective_cuts=count if runner.ledger.mode == 'PROSPECTIVE' else 0,
                    new_synthetic_cuts=count if runner.ledger.mode == 'SYNTHETIC_TEST' else 0,
                    new_cut_proofs=[v for k, v in after.items() if k not in before],
                    original_cuts_unchanged=True, network_calls_in_capture=0, timings=timings.summary())


async def arm(config, receipt_sha, sources, *, wait_seconds=120):
    """Start BEFORE the cut. Clock/receipt/source checks are never deferred to it."""
    require(type(wait_seconds) is int and 0 <= wait_seconds <= MAX_LEAD, 'INVALID_WAIT_BUDGET')
    c = validate_config(config)['collection']
    ledger = CutLedger(c['database']); store = ReadyStore(ledger); ready = store.get(receipt_sha)
    store.check_config(config, ready)
    existing = existing_cut(ledger, ready, receipt_sha)
    if existing is not None:
        return dict(status='ALREADY_RECORDED', new_prospective_cuts=0, existing_proof=existing)
    cut = ready['fixture']['start_ts_utc'] - HORIZONS[ready['horizon']]
    # This check must precede ALL network work, even when invoked at 20:04:44.
    require(time.time() < cut - MIN_ARM_LEAD, 'ARM_MUST_START_BEFORE_WINDOW')
    proof = await sources.fetch(UTC_URL)
    gate = CaptureGate(ready, receipt_sha, proof)
    require(time.time() < cut - MIN_ARM_LEAD, 'ARM_PRECHECKS_FINISHED_TOO_LATE')
    runner = ArmedRunner(EvidenceLedger(c['database'], ready['mode'], gate), gate)
    if cut - time.time() > wait_seconds:
        return dict(status='WAITING_FOR_CUT', reason='WAIT_BUDGET_TOO_SHORT', new_prospective_cuts=0)
    # Bounded foreground wait; monotonic/wall divergence is checked every second.
    while time.time() < cut or gate.utc_bounds()[0] < cut:
        gate.check(allow_wait=True)
        await asyncio.sleep(min(1, max(.01, cut - gate.utc_bounds()[0])))
    return await capture_armed(runner)


def audit(database):
    """Read-only replay of readiness/clock bindings at each original recording time."""
    result = inspect(database); result.pop('examples', None)
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        ready_count = 0
        for sha, raw in db.execute('SELECT sha256,payload FROM faz39_ready'):
            ready = json.loads(raw)
            require(digest(ready) == sha, 'READINESS_HASH_MISMATCH')
            validate_ready(ready, ready['ready_utc'])
            require(ready['mode'] == result['mode'], 'READY_LEDGER_MODE_MISMATCH')
            if ready['schema_version'] == 2:
                identity = db.execute('SELECT ledger_id FROM faz39_identity WHERE singleton=1').fetchall()
                require(identity == [(ready['ledger_id'],)], 'READY_LEDGER_ID_MISMATCH')
                expected = digest(dict(schema_version=2, ledger_id=ready['ledger_id'],
                    storage=dict(mode='LOCAL_ONLY', external_target=None, upload_enabled=False)))
                require(ready['config_sha256'] == expected, 'READY_CONFIG_MISMATCH')
            ready_count += 1
        rows = db.execute('SELECT recorded_utc,payload FROM faz33_cuts').fetchall()
        count = 0
        for recorded, raw in rows:
            packet = json.loads(raw)
            if 'faz39' not in packet:
                continue
            binding = packet['faz39']; ready = binding['readiness']; sha = binding['receipt_sha256']
            require(digest(ready) == sha, 'READY_BINDING_HASH')
            stored = db.execute('SELECT payload FROM faz39_ready WHERE sha256=?', (sha,)).fetchone()
            require(stored == (canonical_json(ready),), 'READY_BINDING_NOT_STORED')
            validate_ready(ready, recorded)
            require(packet['fixture'] == ready['fixture'] and packet['horizon'] == ready['horizon'] and
                    packet['model_sha'] == ready['source']['sha'] and packet['usage'] == ready['mode'],
                    'READY_PACKET_IDENTITY')
            anchor = binding['arm_utc_attestation']; utc_anchor(anchor)
            cut = ready['fixture']['start_ts_utc'] - HORIZONS[ready['horizon']]
            require(ready['ready_utc'] <= anchor['observed_utc'] < cut and
                    0 <= recorded - anchor['observed_utc'] <= GRACE, 'ARM_CLOCK_BINDING')
            count += 1
    result['faz39_bound_cuts'] = count
    result['faz39_ready_receipts'] = ready_count
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare'); p.add_argument('config'); p.add_argument('fixture_id')
    p.add_argument('--horizon', choices=HORIZONS, default='T6H')
    p = commands.add_parser('arm'); p.add_argument('config'); p.add_argument('--receipt-sha256', required=True)
    p.add_argument('--wait-seconds', type=int, default=120)
    p = commands.add_parser('audit'); p.add_argument('database')
    args = parser.parse_args()
    async def run():
        if args.command == 'audit':
            return dict(status='AUDIT_OK', **audit(args.database))
        config = json.loads(Path(args.config).read_text())
        async with PublicSources() as sources:
            if args.command == 'prepare':
                return await prepare(config, args.fixture_id, args.horizon, sources)
            return await arm(config, args.receipt_sha256, sources, wait_seconds=args.wait_seconds)
    try:
        result = asyncio.run(run())
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, asyncio.TimeoutError) as exc:
        result = dict(status='REFUSED', reason=str(exc), new_prospective_cuts=None,
                      required_action='Reopen and audit the ledger; do not infer zero writes from an error.')
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] in ('READY_BEFORE_CUT', 'RECORDED', 'ALREADY_RECORDED', 'WAITING_FOR_CUT', 'AUDIT_OK') else 1


if __name__ == '__main__':
    raise SystemExit(main())
