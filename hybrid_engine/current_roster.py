"""Append-only current NBA availability observations, never old forecast inputs.

NBA PDF text is a parsed source observation, not an independently verified
medical/eligibility fact. ESPN IDs and publication/actual retrieval clocks stay
explicit. No player effect, lineup, model adjustment or calibration occurs.
"""
from copy import deepcopy
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

from core.league_identity import normalize_name
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.nba_injury_source import official_nba_injury_report_reference
from telegram_delivery import tsi


TTL = 300
MAX_BYTES = 8*1024*1024
PREFIX = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'
STATUS = {'Out': 'Oynamayacak', 'Questionable': 'Oynaması belirsiz', 'Doubtful': 'Oynaması zor',
          'Probable': 'Oynaması muhtemel', 'Available': 'Oynayabilir',
          'Day-To-Day': 'Gün gün izleniyor', 'Suspended': 'Cezalı'}


def utc(text):
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('EXPLICIT_SOURCE_UTC_REQUIRED')
    return int(value.timestamp())


def team_key(text):
    key = normalize_name(text)
    return 'laclippers' if key == 'losangelesclippers' else key


def player_key(text):
    if ',' in text:
        last, first = text.split(',', 1)
        text = first.strip()+' '+last.strip()
    return normalize_name(text)


def context_for(snapshot):
    result = {key: deepcopy(snapshot[key]) for key in ('league', 'season', 'fixture_id',
        'provider_fixture_ids', 'fixture_start_utc', 'prediction_generated_at_utc', 'model_digest', 'home', 'away')}
    result['original_snapshot_sha256'] = digest(snapshot)
    if (result['league'] != 'NBA' or len(result['provider_fixture_ids']) != 1 or
            re.fullmatch(r'[0-9]{1,15}', result['provider_fixture_ids'][0]) is None or
            type(result['prediction_generated_at_utc']) is not int or type(result['fixture_start_utc']) is not int or
            not 0 < result['prediction_generated_at_utc'] < result['fixture_start_utc']):
        raise ValueError('NBA_ROSTER_FORECAST_CONTEXT_REQUIRED')
    for side in ('home', 'away'):
        team = result[side]
        if not re.fullmatch(r'[0-9]{1,8}', team.get('provider_id', '')):
            raise ValueError('EXPLICIT_ESPN_TEAM_ID_REQUIRED')
        team_key(team['official_name'])
    if result['home']['provider_id'] == result['away']['provider_id']:
        raise ValueError('DISTINCT_ROSTER_TEAMS_REQUIRED')
    return result


NBA_COM_INJURY_INDEX='https://www.nba.com/players/injury-report'


def season_index(season):
    match = re.fullmatch(r'(20[0-9]{2})/(20[0-9]{2})', season)
    if match is None or int(match[2]) != int(match[1])+1:
        raise ValueError('EXPLICIT_ROSTER_SEASON_REQUIRED')
    return f'https://official.nba.com/nba-injury-report-{match[1]}-{match[2][-2:]}-season/'


def allowed_url(url):
    if re.fullmatch(re.escape(PREFIX)+r'(summary\?event=[0-9]{1,15}|teams/[0-9]{1,8}/roster\?season=20[0-9]{2})', url):
        return True
    if re.fullmatch(r'https://official\.nba\.com/nba-injury-report-20[0-9]{2}-[0-9]{2}-season/', url):
        return True
    if url==NBA_COM_INJURY_INDEX:
        return True
    return bool(re.fullmatch(r'https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_20[0-9]{2}-[0-9]{2}-[0-9]{2}_[0-9]{2}_[0-9]{2}(AM|PM)\.pdf', url))


def native_get(url, *, deadline):
    """Free fixed public origins; no keys, redirects, unbounded body or retries."""
    import requests
    if not allowed_url(url):
        raise ValueError('ROSTER_SOURCE_URL_REFUSED')
    began = int(time.time())
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise TimeoutError('ROSTER_REQUEST_BUDGET')
    try:
        with requests.get(url, timeout=(min(2, remaining), min(4, remaining)),
                          stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                retry = response.headers.get('Retry-After', '')
                return dict(url=url, status='SOURCE_HTTP_ERROR', http_status=response.status_code,
                            retry_after=min(3600, int(retry)) if retry.isascii() and retry.isdigit() else 300)
            chunks = bytearray()
            for block in response.iter_content(65536):
                chunks.extend(block)
                if len(chunks) > MAX_BYTES or time.monotonic() > deadline:
                    raise ValueError('ROSTER_SOURCE_BUDGET')
    except requests.RequestException:
        return dict(url=url, status='SOURCE_UNAVAILABLE')
    completed = int(time.time())
    body = bytes(chunks)
    return dict(url=url, status='RECEIVED', started_at_utc=began, observed_at_utc=completed,
                body_sha256=hashlib.sha256(body).hexdigest(), body=body)


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls.extend(value for key, value in attrs if key == 'href' and value and
                             value.startswith('https://ak-static.cms.nba.com/referee/injury/'))


def latest_report(body, now, season):
    parser = Links(); parser.feed(body.decode('utf-8'))
    candidates = []
    for url in set(parser.urls):
        try:
            ref = official_nba_injury_report_reference(url, retrieved_at_utc=now, prediction_utc=now)
            year = datetime.fromtimestamp(ref['report_timestamp_utc'], ZoneInfo('America/New_York')).year
            if int(season[:4]) <= year <= int(season[-4:]) and now-ref['report_timestamp_utc'] <= 6*3600:
                candidates.append(ref)
        except ValueError:
            continue
    return max(candidates, key=lambda r: r['report_timestamp_utc']) if candidates else None


def bind_summary(document, context, now):
    header = document['header']; comps = header['competitions']
    fid = context['provider_fixture_ids'][0]
    if header['id'] != fid or len(comps) != 1 or comps[0]['id'] != fid:
        raise ValueError('ROSTER_FIXTURE_ID_MISMATCH')
    comp = comps[0]
    if utc(comp['date']) != context['fixture_start_utc'] or header['season']['year'] != int(context['season'][-4:]):
        raise ValueError('ROSTER_FIXTURE_CLOCK_OR_SEASON_MISMATCH')
    state = comp['status']['type']
    if state.get('name') != 'STATUS_SCHEDULED' or state.get('completed') is not False or now >= context['fixture_start_utc']:
        raise ValueError('ROSTER_FIXTURE_NOT_PREMATCH')
    teams = {}
    if len(comp['competitors']) != 2:
        raise ValueError('ROSTER_FIXTURE_PAIR_REQUIRED')
    for row in comp['competitors']:
        side = row['homeAway']; team = row['team']; expected = context[side]
        if (side not in ('home', 'away') or side in teams or team['id'] != expected['provider_id'] or
                row['id'] != team['id'] or team_key(team['displayName']) != team_key(expected['official_name']) or
                re.fullmatch('[A-Z]{2,4}', team['abbreviation']) is None):
            raise ValueError('ROSTER_FIXTURE_TEAM_MISMATCH')
        teams[side] = dict(id=team['id'], name=team['displayName'], abbreviation=team['abbreviation'])
    return teams


def espn_rows(document, teams, now):
    rows = []; rejected = 0; seen = set()
    groups = document.get('injuries')
    if not isinstance(groups, list) or len(groups) > 2:
        return [], 1
    ids = {v['id']: v for v in teams.values()}
    for group in groups:
        tid = group['team']['id']
        if tid not in ids or tid in seen or team_key(group['team']['displayName']) != team_key(ids[tid]['name']):
            raise ValueError('ROSTER_INJURY_TEAM_MISMATCH')
        seen.add(tid)
        source_rows = group['injuries']
        if not isinstance(source_rows, list) or len(source_rows) > 50:
            raise ValueError('ROSTER_ROW_BUDGET')
        for item in source_rows:
            try:
                athlete = item['athlete']; pid = athlete['id']; name = athlete['displayName']
                at = utc(item['date']); status = item['status']
                if not re.fullmatch('[0-9]{1,15}', pid) or status not in STATUS or not 0 < at <= now:
                    raise ValueError('INVALID_STATUS')
                normalize_name(name)
                detail = item.get('details', {})
                note = ' · '.join(str(detail.get(k) or '') for k in ('type', 'detail', 'side')).strip(' ·')[:300]
                rows.append(dict(team_id=tid, team_name=ids[tid]['name'], player_id=pid, player_name=name,
                                 status=status, source='ESPN', status_updated_at_utc=at, note=note,
                                 identity_status='SOURCE_PLAYER_ID', independent_status_verified=False))
            except (KeyError, ValueError, TypeError):
                rejected += 1
    return rows, rejected


def roster_ids(document, team, season):
    if (document['team']['id'] != team['id'] or
            team_key(document['team']['displayName']) != team_key(team['name']) or
            document['season']['year'] != int(season[-4:])):
        raise ValueError('ROSTER_DIRECTORY_TEAM_OR_SEASON_MISMATCH')
    athletes = document['athletes']
    if not isinstance(athletes, list) or len(athletes) > 100:
        raise ValueError('ROSTER_DIRECTORY_BUDGET')
    result = {}; duplicate_keys = set(); id_keys = {}
    for athlete in athletes:
        pid = athlete['id']; key = player_key(athlete['displayName'])
        if not re.fullmatch('[0-9]{1,15}', pid):
            raise ValueError('ROSTER_DIRECTORY_PLAYER_ID')
        if key in result:
            duplicate_keys.add(key)
        if pid in id_keys:
            duplicate_keys.update((key, id_keys[pid]))
        result[key] = pid; id_keys[pid] = key
    for key in duplicate_keys:
        result.pop(key, None)
    return result


def nba_rows(extraction, teams, directories, context, report_at):
    start = datetime.fromtimestamp(context['fixture_start_utc'], ZoneInfo('America/New_York'))
    matchup = teams['away']['abbreviation']+'@'+teams['home']['abbreviation']
    result = []; rejected = 0
    for row in extraction.get('rows', []):
        if row.get('matchup') != matchup:
            continue
        try:
            # Check the game date and clock too, not just a recurring team pair.
            day = datetime.strptime(row['game_date'], '%m/%d/%Y').date()
            clock = re.fullmatch(r'(\d{1,2}):(\d{2})(?:\s*(AM|PM))?(?:\s*\(ET\))?', row['game_time'], re.I)
            if clock is None:
                raise ValueError('NBA_GAME_CLOCK')
            hour, minute = int(clock[1]), int(clock[2])
            if clock[3]:
                if not 1 <= hour <= 12: raise ValueError('NBA_GAME_CLOCK')
                hour = hour % 12 + (12 if clock[3].upper() == 'PM' else 0)
            precision = 'EXPLICIT_24H_OR_MERIDIEM'
            if not clock[3] and 1 <= hour <= 12:
                # NBA tables use 07:00(ET) without an AM/PM marker. Do not
                # pretend this proves a UTC clock; date+ordered pair binds the
                # observation and the display exposes the clock limitation.
                precision = 'MERIDIEM_NOT_STATED'
                matches_clock = (hour % 12, minute) == (start.hour % 12, start.minute)
            else:
                matches_clock = (hour, minute) == (start.hour, start.minute)
            if day != start.date() or not matches_clock:
                raise ValueError('NBA_GAME_CLOCK_MISMATCH')
            found = [t for t in teams.values() if team_key(t['name']) == team_key(row['team'])]
            if len(found) != 1 or row['status'] not in STATUS:
                raise ValueError('NBA_TEAM_OR_STATUS')
            team = found[0]; key = player_key(row['player_name'])
            pid = directories.get(team['id'], {}).get(key)
            result.append(dict(team_id=team['id'], team_name=team['name'], player_id=pid,
                player_name=row['player_name'], status=row['status'], source='NBA_OFFICIAL_PDF',
                status_updated_at_utc=report_at, note=row['reason'][:300],
                source_clock_precision=precision,
                identity_status='EXACT_ESPN_ROSTER_MATCH' if pid else 'PLAYER_ID_NOT_VERIFIED',
                independent_status_verified=False))
        except (KeyError, ValueError, TypeError):
            rejected += 1
    return result, rejected


def pdf_extract(path, *, deadline):
    if importlib.util.find_spec('pdfplumber') is None:
        return dict(status='PDF_DEPENDENCY_MISSING', rows=[], extraction_verified=False)
    remaining = min(6, deadline-time.monotonic())
    if remaining <= 0: raise TimeoutError('ROSTER_PDF_BUDGET')
    # The parser needs no credentials or network configuration. An explicit
    # allowlist also excludes provider aliases such as API_BASKETBALL_KEY.
    env = {k: os.environ[k] for k in ('PATH','PYTHONPATH','LANG','LC_ALL','TMPDIR') if k in os.environ}
    env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MALLOC_ARENA_MAX='1', PYTHONDONTWRITEBYTECODE='1')
    run = subprocess.run([sys.executable, '-m', 'hybrid_engine.roster_pdf_worker', str(path)],
                         capture_output=True, timeout=remaining, env=env, check=False)
    if run.returncode or len(run.stdout) > 512*1024:
        return dict(status='PDF_WORKER_RESOURCE_OR_PARSE_FAILURE', rows=[], extraction_verified=False)
    return json.loads(run.stdout)


def review_diagnostics(review):
    """Safe bounded evidence summary; not an eligibility or playing assessment."""
    grouped={}
    for r in review.get('records',[]):
        if r.get('status') not in ('Out','Suspended'): continue
        key=(r.get('team_id'),r.get('player_id') or 'UNMAPPED:'+str(r.get('player_name','')))
        item=grouped.setdefault(key,dict(team=str(r.get('team_name',''))[:160],
            player=str(r.get('player_name',''))[:160],player_id=r.get('player_id'),sources=set()))
        item['sources'].add(r['source'])
    missing=[]
    for item in grouped.values():
        absent={'ESPN','NBA_OFFICIAL_PDF'}-item['sources']
        if absent:
            missing.append(dict(item,sources=sorted(item['sources']),missing_sources=sorted(absent)))
    return dict(official_stage=review.get('official_stage'),official_code=review.get('official_code'),
        official_http_status=review.get('official_http_status'),
        official_extraction_status=review.get('official_extraction_status'),
        official_parsed_rows=review.get('official_parsed_rows'),
        official_fixture_rows=review.get('official_fixture_rows'),
        official_note_scope=review.get('official_note_scope'),
        official_discovery_mode=review.get('official_discovery_mode'),
        latest_report_verified=review.get('latest_report_verified'),
        official_pdf_clock_verified=review.get('official_pdf_clock_verified'),
        index_failure=review.get('index_failure'),
        successful_source_urls=[s.get('url') for s in review.get('sources',[])],
        missing_absence_corroboration=missing[:20],missing_absence_count=len(missing),
        diagnostic_only=True,confidence_index=None)


def inspect_review(directory,fixture_id):
    """Read old source observations without API requests, rewrites or backfill."""
    root=local_path(directory); selected=None; scanned=0
    for path in root.glob('review-*.json'):
        scanned+=1
        if scanned>1000 or path.is_symlink() or path.stat().st_size>1024*1024:
            raise ValueError('ROSTER_INSPECTION_ARCHIVE_BUDGET')
        w=json.loads(path.read_text()); p=w['payload']
        if digest(p)!=w['sha256'] or path.stem!='review-'+w['sha256']:
            raise ValueError('ROSTER_INSPECTION_PIN')
        if fixture_id not in p['provider_fixture_ids']: continue
        if selected is None or (p['observed_at_utc'],w['sha256'])>(selected['payload']['observed_at_utc'],selected['sha256']):
            selected=w
    if selected is None:
        return dict(status='ARCHIVE_UNAVAILABLE',diagnostic_only=True,api_requests_made=0,forecast_changed=False)
    p=selected['payload']
    return dict(status='READ_ONLY_ARCHIVED_ROSTER_DIAGNOSTIC',provider_fixture_ids=p['provider_fixture_ids'],
        observed_at_utc=p['observed_at_utc'],source_review_sha256=selected['sha256'],
        details=review_diagnostics(p),legacy_failure_stage_unknown=bool(p.get('warnings') and not p.get('official_stage')),
        api_requests_made=0,forecast_changed=False,online_training=False,production_changed=False)


def official_error_code(exc):
    known={'ROSTER_SOURCE_UNAVAILABLE','ROSTER_SOURCE_COOLDOWN','ROSTER_SOURCE_PIN_OR_CLOCK',
        'INVALID_OFFICIAL_PDF','ROSTER_PDF_ARCHIVE_CONFLICT','ROSTER_EXTRACTION_PIN',
        'INCONSISTENT_INJURY_REPORT_PAGE_TITLE','UNVERIFIED_INJURY_CONTINUATION_LAYOUT',
        'EXPLICIT_REPORT_TOO_OLD','EXPLICIT_REPORT_TITLE_NOT_VERIFIED','EXPLICIT_REPORT_TITLE_CLOCK_MISMATCH',
        'EXPLICIT_REPORT_BODY_CHANGED'}
    if str(exc) in known: return str(exc)
    if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)): return 'OFFICIAL_SOURCE_OR_PARSE_TIMEOUT'
    if isinstance(exc,OSError): return 'OFFICIAL_ARCHIVE_IO_ERROR'
    return 'OFFICIAL_SCHEMA_OR_EXTRACTION_ERROR'


class CurrentRosterReview:
    def __init__(self, directory, *, getter=native_get, extractor=pdf_extract, clock=time.time, report_archive=None):
        self.directory = local_path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.getter = getter; self.extractor = extractor; self.clock = clock
        self.lock = threading.Lock(); self.cache = {}; self.sources = {}; self.cooldowns = {}
        self.last_source_failure=None
        self.report_archive=None if report_archive is None else local_path(report_archive)
        self.failure_codes={}

    def _get(self, url, deadline):
        self.last_source_failure=None
        if not allowed_url(url): raise ValueError('ROSTER_SOURCE_URL_REFUSED')
        now = int(self.clock())
        prior = self.sources.get(url)
        if prior and 0 <= now-prior['observed_at_utc'] < TTL:
            return prior
        if now < self.cooldowns.get(url, 0):
            self.last_source_failure=self.failure_codes.get(url)
            raise ValueError('ROSTER_SOURCE_COOLDOWN')
        r = self.getter(url, deadline=deadline)
        if r.get('status') != 'RECEIVED':
            self.cooldowns[url] = now + min(3600, max(30, r.get('retry_after', 300)))
            status=r.get('http_status')
            self.last_source_failure=dict(url=url,http_status=status if type(status) is int and 100<=status<=599 else None)
            self.failure_codes[url]=deepcopy(self.last_source_failure)
            raise ValueError('ROSTER_SOURCE_UNAVAILABLE')
        now = int(self.clock()); body = r['body']
        if (r['url'] != url or type(body) is not bytes or len(body) > MAX_BYTES or
                hashlib.sha256(body).hexdigest() != r['body_sha256'] or
                type(r['started_at_utc']) is not int or type(r['observed_at_utc']) is not int or
                not 0 < r['started_at_utc'] <= r['observed_at_utc'] <= now or now-r['observed_at_utc'] > TTL):
            raise ValueError('ROSTER_SOURCE_PIN_OR_CLOCK')
        # Content-addressed JSON envelope stores exact bytes via hex, never overwrite.
        pin = digest({k: v for k, v in r.items() if k != 'body'})
        publish_json(self.directory/('source-'+pin+'.json'), {**{k: v for k, v in r.items() if k != 'body'}, 'body_hex': body.hex()})
        while self.sources and (len(self.sources) >= 16 or sum(len(x['body']) for x in self.sources.values())+len(body) > MAX_BYTES):
            self.sources.pop(next(iter(self.sources)))
        if len(body) <= MAX_BYTES: self.sources[url] = r
        return r

    def review(self, context):
        now = int(self.clock()); key = digest(context)
        base = dict(format='CURRENT_NBA_ROSTER_REVIEW_V1', fixture_id=context['fixture_id'],
            season=context['season'], provider_fixture_ids=list(context['provider_fixture_ids']),
            model_digest=context.get('model_digest'),
            original_snapshot_sha256=context['original_snapshot_sha256'], prediction_utc=context['prediction_generated_at_utc'],
            fixture_start_utc=context['fixture_start_utc'], observed_at_utc=now,
            record_class='SOURCE_ACCESS_PROBE_NOT_FORECAST_LINKED' if context.get('source_probe') is True else 'CURRENT_OBSERVATION_NOT_FORECAST_INPUT', forecast_changed=False,
            model_adjustment_applied=False, lineup_verified=False, confidence_index=None,
            actual_telegram_delivery_verified=False, records=[], sources=[], warnings=[])
        if now >= context['fixture_start_utc']:
            return dict(base, status='POST_TIPOFF_NO_CURRENT_BACKFILL')
        cached = self.cache.get(key)
        if cached and 0 <= now-cached['observed_at_utc'] < TTL and now < cached['valid_until_utc']:
            return deepcopy(cached)
        if not self.lock.acquire(blocking=False): return dict(base, status='REVIEW_BUSY')
        deadline = time.monotonic()+18
        try:
            fid = context['provider_fixture_ids'][0]
            r = self._get(PREFIX+'summary?event='+fid, deadline)
            document = json.loads(r['body']); teams = bind_summary(document, context, int(self.clock()))
            rows, rejected = espn_rows(document, teams, int(self.clock()))
            base['records'] = rows; base['rejected_rows'] = rejected
            base['sources'].append({k: v for k, v in r.items() if k != 'body'})
            stage='INDEX_FETCH'
            try:
                explicit=None
                index=None
                discovery='LIVE_OFFICIAL_INDEX'
                try:
                    index=self._get(season_index(context['season']),deadline)
                except ValueError:
                    # Public first-party NBA.com index is an official second
                    # publication path; never enumerate PDF timestamps or
                    # spoof authentication/redirects. Only original 403 permits
                    # trying the fixed NBA.com page. Do NOT retry 429/401/404.
                    denied=self.last_source_failure
                    if not denied or denied.get('http_status')!=403:
                        raise
                    base['index_failure']=dict(stage='INDEX_FETCH',http_status=403)
                    try:
                        index=self._get(NBA_COM_INJURY_INDEX,deadline)
                    except ValueError:
                        # Existing explicitly imported fresh, SHA-pinned
                        # official CDN report, not claimed latest.
                        if self.report_archive is None: raise
                        from hybrid_engine.official_report_link import select_link,reference,MAX_AGE
                        selected=select_link(self.report_archive,context['season'],int(self.clock()))
                        if selected is None: raise
                        explicit,entry_pin=selected
                        ref=reference(explicit['url'],int(self.clock()))
                        base.update(official_discovery_mode='EXPLICIT_OFFICIAL_CDN_LINK',
                            latest_report_verified=False,
                            explicit_report_entry_sha256=entry_pin,
                            explicit_report_expires_at_utc=ref['report_timestamp_utc']+MAX_AGE)
                        base['warnings'].append('INDEX_403_EXPLICIT_LINK_NOT_ASSERTED_LATEST')
                    else:
                        discovery='LIVE_NBA_COM_OFFICIAL_INDEX'
                if index is not None:
                    base['sources'].append({k:v for k,v in index.items() if k!='body'})
                    stage='INDEX_DISCOVERY'
                    ref=latest_report(index['body'],int(self.clock()),context['season'])
                    base.update(official_discovery_mode=discovery,
                                latest_report_verified=ref is not None)
                base['official_report'] = ref
                base.update(official_stage=stage,official_code='NO_RECENT_PUBLISHED_REPORT')
                if ref:
                    stage='PDF_FETCH'
                    pdf = self._get(ref['source_url'], deadline)
                    if explicit and pdf['body_sha256']!=explicit['pdf_sha256']:
                        raise ValueError('EXPLICIT_REPORT_BODY_CHANGED')
                    base['sources'].append({k: v for k, v in pdf.items() if k != 'body'})
                    stage='PDF_ARCHIVE'
                    path = self.directory/('pdf-'+pdf['body_sha256']+'.pdf')
                    if not pdf['body'].startswith(b'%PDF-'): raise ValueError('INVALID_OFFICIAL_PDF')
                    try:
                        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    except FileExistsError:
                        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != pdf['body_sha256']:
                            raise ValueError('ROSTER_PDF_ARCHIVE_CONFLICT')
                    else:
                        with os.fdopen(fd, 'wb') as stream: stream.write(pdf['body']); stream.flush(); os.fsync(stream.fileno())
                    stage='PDF_EXTRACTION'
                    extraction = self.extractor(path, deadline=deadline)
                    if explicit or extraction.get('report_titles'):
                        from hybrid_engine.official_report_link import assert_report_title,reference
                        if explicit: reference(ref['source_url'],int(self.clock()))
                        assert_report_title(extraction,ref)
                        base['official_pdf_clock_verified']=True
                    base['official_extraction_status'] = extraction['status']
                    base.update(official_stage=stage,official_code=extraction['status'],
                        official_parsed_rows=len(extraction.get('rows',[])),
                        official_parser_rejected_count=extraction.get('rejected_count'),
                        official_parser_version=extraction.get('parser_version'),
                        official_note_scope='ROW_FRAGMENTS_NOT_FULL_MEDICAL_REASONS' if
                            any(row.get('reason_fragment') for row in extraction.get('rows',[])) else 'SOURCE_TABLE_CELLS')
                    if extraction.get('rows'):
                        if (extraction.get('source_pdf_sha256') != pdf['body_sha256'] or
                                extraction.get('rows_sha256') != digest(extraction['rows']) or
                                len(extraction['rows']) > 500):
                            raise ValueError('ROSTER_EXTRACTION_PIN')
                        directories = {}
                        stage='PLAYER_IDENTITIES'
                        for team in teams.values():
                            try:
                                dr = self._get(PREFIX+'teams/'+team['id']+'/roster?season='+context['season'][-4:], deadline)
                                directories[team['id']] = roster_ids(json.loads(dr['body']), team, context['season'])
                                base['sources'].append({k: v for k, v in dr.items() if k != 'body'})
                            except (ValueError, KeyError, TypeError, OSError):
                                base['warnings'].append('PLAYER_DIRECTORY_UNVERIFIED')
                        stage='FIXTURE_ROWS'
                        official, rejected = nba_rows(extraction, teams, directories, context, ref['report_timestamp_utc'])
                        base['records'].extend(official); base['rejected_rows'] += rejected
                        base.update(official_stage=stage,official_fixture_rows=len(official),
                            official_code='SOURCE_ROWS_MATCHED_NOT_MEDICALLY_VERIFIED' if official else 'NO_MATCHING_OFFICIAL_ROWS')
            except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
                base.update(official_stage=stage,official_code=official_error_code(exc))
                if stage in ('INDEX_FETCH','PDF_FETCH') and self.last_source_failure:
                    base['official_http_status']=self.last_source_failure['http_status']
                base['warnings'].append('OFFICIAL_REPORT_UNAVAILABLE_OR_UNVERIFIED')
            now = int(self.clock()); base['observed_at_utc'] = now
            base['valid_until_utc'] = min([context['fixture_start_utc'], now+TTL]+
                                         [s['observed_at_utc']+TTL for s in base['sources']])
            if base.get('explicit_report_expires_at_utc') is not None:
                base['valid_until_utc']=min(base['valid_until_utc'],base['explicit_report_expires_at_utc'])
            if now >= context['fixture_start_utc']:
                base.update(status='TIPOFF_DURING_REVIEW', records=[])
            else:
                base['status'] = 'CURRENT_SOURCE_OBSERVATIONS' if base['records'] else 'NO_SOURCE_STATUS_RECORDS'
                if now >= base['valid_until_utc']:
                    base['status'] = 'SOURCE_OBSERVATIONS_STALE'
            base['source_available_after_original_forecast'] = (None if base['prediction_utc'] is None else
                any(s['observed_at_utc'] > base['prediction_utc'] for s in base['sources']))
            wrapped = dict(payload=base, sha256=digest(base))
            publish_json(self.directory/('review-'+wrapped['sha256']+'.json'), wrapped)
            if len(self.cache) >= 32: self.cache.pop(next(iter(self.cache)))
            self.cache[key] = deepcopy(base)
            return base
        except (ValueError, KeyError, TypeError, OSError):
            return dict(base, status='SOURCE_OR_FIXTURE_REVIEW_FAILED', records=[])
        finally:
            self.lock.release()


def render_review(review):
    esc = html.escape
    lines = ['🏥 <b>GÜNCEL KADRO / SAKATLIK GÖZLEMİ</b>',
             'İlk tahminin girdisi değildir; skor ve eski kayıt değiştirilmedi.',
             'Kontrol: '+tsi(review['observed_at_utc'])]
    if review['status'] in ('POST_TIPOFF_NO_CURRENT_BACKFILL', 'TIPOFF_DURING_REVIEW'):
        lines.append('Maç başladı; güncel bilgiler geçmiş maç öncesi kadrosu olarak toplanmadı.')
    elif review['status'] in ('SOURCE_OR_FIXTURE_REVIEW_FAILED', 'REVIEW_BUSY'):
        lines.append('Kaynak/maç denetimi tamamlanamadı; bu, sakat veya cezalı oyuncu yok demek değildir.')
    elif review['status'] == 'SOURCE_OBSERVATIONS_STALE':
        lines.append('Kaynak gözlemi inceleme sırasında eskidi; güncel kadro onayı değildir.')
    rows = review['records']; groups = {}
    for row in rows:
        key = (row['team_id'], row.get('player_id') or player_key(row['player_name']))
        groups.setdefault(key, []).append(row)
    for entries in groups.values():
        if len({r['status'] for r in entries}) > 1:
            lines.append('⚠️ Kaynak durumları uyuşmuyor; taraf seçilmedi.')
        for row in entries:
            lines.extend(['', '<b>'+esc(row['team_name'])+' · '+esc(row['player_name'])+'</b>',
                esc(STATUS[row['status']])+' · '+('NBA resmî rapor metni' if row['source'] == 'NBA_OFFICIAL_PDF' else 'ESPN maç kaydı'),
                'Kaynak durum zamanı: '+tsi(row['status_updated_at_utc'])])
            if row['note']: lines.append('Kaynak notu: '+esc(row['note']))
            if review['observed_at_utc']-row['status_updated_at_utc']>24*3600:
                lines.append('Durum kaydının tarihi eski; bugünkü oynama durumunun onayı değildir.')
            if re.search(r'\bsuspend|\bsuspension', row['note'], re.I) or row['status'] == 'Suspended':
                lines.append('Kaynakta ceza bildirimi var; bağımsız uygunluk denetimi yapılmadı.')
            if row['identity_status'] == 'PLAYER_ID_NOT_VERIFIED':
                lines.append('Oyuncu kimliği bağımsız eşleşmedi; ham rapor satırı.')
            if row.get('source_clock_precision') == 'MERIDIEM_NOT_STATED':
                lines.append('NBA raporunda AM/PM yok; tarih/takım eşleştirmesi ESPN maç kaydına bağlı.')
    if not rows:
        lines.append('Gösterilebilir oyuncu durum kaydı yok. Boş liste, tam kadro veya ceza yokluğu kanıtı değildir.')
    ref = review.get('official_report')
    if ref:
        lines.extend(['', 'NBA rapor yayını: '+tsi(ref['report_timestamp_utc']), esc(ref['source_url'])])
        if review.get('official_extraction_status') == 'PDF_DEPENDENCY_MISSING':
            lines.append('NBA PDF ayrıştırıcısı kurulu değil; resmî rapor içeriği doğrulanmadı.')
        elif not any(r['source'] == 'NBA_OFFICIAL_PDF' for r in rows):
            lines.append('Bu maç için resmî rapor satırı eşleştirilemedi; rapor verilmiş sayılmadı.')
    if review.get('warnings'): lines.append('Bazı kaynaklar veya oyuncu kimlikleri doğrulanamadı.')
    if review.get('official_discovery_mode')=='EXPLICIT_OFFICIAL_CDN_LINK':
        lines.append('NBA dizini 403 verdi; açıkça eklenen taze resmî PDF bağlantısı kullanıldı. En güncel rapor olduğu doğrulanmadı.')
    if review.get('official_stage'):
        stages={'INDEX_FETCH':'NBA sayfasına erişim','INDEX_DISCOVERY':'Yayımlanmış rapor seçimi',
            'PDF_FETCH':'PDF indirme','PDF_ARCHIVE':'PDF bütünlüğü ve arşiv',
            'PDF_EXTRACTION':'PDF ayrıştırma','PLAYER_IDENTITIES':'Oyuncu kimliği',
            'FIXTURE_ROWS':'Rapordaki maç eşleştirmesi'}
        lines.append('Resmî kaynak aşaması: '+stages.get(review['official_stage'],'Kaynak denetimi'))
        lines.append('Tanı kodu: '+esc(review.get('official_code')))
        if review.get('official_http_status') is not None:
            lines.append('Kaynak HTTP yanıtı: '+str(review['official_http_status']))
        if review.get('official_note_scope')=='ROW_FRAGMENTS_NOT_FULL_MEDICAL_REASONS':
            lines.append('Resmî rapor notları satır parçaları olabilir; tıbbi neden veya oyuncu etkisi çıkarılmadı.')
    for source in review['sources']:
        lines.append(esc(source['url']))
        lines.append('Kaynak SHA: '+source['body_sha256'][:12]+' · Erişim: '+tsi(source['observed_at_utc']))
    lines.extend(['', 'Kayıtlar kaynak gözlemidir; bağımsız tıbbi/ceza uygunluğu doğrulaması değildir.',
        'İlk beş, dakika/rotasyon ve oyuncu etkisi doğrulanmadı; modele uygulanmadı.',
        'NOT_CALIBRATED · Güven endeksi yok'])
    return '\n'.join(lines)


def main():
    """Public access probe without inventing a forecast or old prediction time."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-id', required=True)
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--inspect',action='store_true',help='Read last archived source review; no network or writes')
    args = parser.parse_args()
    if re.fullmatch('[0-9]{1,15}', args.fixture_id) is None:
        parser.error('ESPN maç kimliği sayısal olmalıdır')
    if args.inspect:
        print(json.dumps(inspect_review(args.output_directory,args.fixture_id),sort_keys=True)); return
    service = CurrentRosterReview(args.output_directory)
    receipt = service._get(PREFIX+'summary?event='+args.fixture_id, time.monotonic()+10)
    document = json.loads(receipt['body']); header = document['header']; comp = header['competitions'][0]
    teams = {c['homeAway']: dict(provider_id=c['team']['id'], official_name=c['team']['displayName'])
             for c in comp['competitors']}
    year = header['season']['year']
    context = dict(league='NBA', season=f'{year-1}/{year}', fixture_id='ESPN:'+args.fixture_id,
        provider_fixture_ids=[args.fixture_id], fixture_start_utc=utc(comp['date']),
        prediction_generated_at_utc=None, model_digest=None, original_snapshot_sha256=None,
        source_probe=True, **teams)
    review = service.review(context)
    print(json.dumps(dict(status=review['status'], record_class=review['record_class'],
        records=len(review['records']), sources=len(review['sources']),
        official_extraction_status=review.get('official_extraction_status'),
        forecast_changed=False, actual_telegram_delivery_verified=False, sha256=digest(review))))


if __name__ == '__main__':
    main()
