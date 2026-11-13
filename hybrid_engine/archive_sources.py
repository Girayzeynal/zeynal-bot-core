"""Replay immutable Wikipedia revisions and GitHub-witnessed data blobs.

Retrieval clocks stay current. Only the exact archived fields gain an earlier
availability witness. News, injuries, season totals and unrelated fields never do.
"""
import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

from core.team_identity import digest
from core.league_identity import normalize_name
from hybrid_engine.availability import certify


def utc(value):
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None: raise ValueError('EXPLICIT_ARCHIVE_TIMEZONE_REQUIRED')
    return int(date.timestamp())


def pinned(item):
    from hybrid_engine.data import local_path
    path = local_path(item['path']); raw = path.read_bytes()
    if len(raw) > 8*1024*1024 or hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise ValueError('ARCHIVE_FILE_TRUSTED_PIN_MISMATCH')
    return raw


def github_blob(item):
    """Do not use commit-author dates or release creation dates as file availability."""
    run_receipt = json.loads(pinned(item['witness']))
    file_receipt = json.loads(pinned(item['listing']))
    repo, commit = item['repo'], item['commit']
    run_url = urlparse(run_receipt['source_url']); listing_url = urlparse(file_receipt['source_url'])
    if (run_url.netloc != 'api.github.com' or run_url.path != '/repos/'+repo+'/actions/runs' or
            listing_url.netloc != 'api.github.com' or not listing_url.path.startswith('/repos/'+repo+'/contents/') or
            parse_qs(listing_url.query).get('ref') != [commit]):
        raise ValueError('ARCHIVE_PROVIDER_URI_BINDING_CONFLICT')
    run = next((r for r in run_receipt['document']['workflow_runs'] if r['id'] == item['run_id']), None)
    if (not run or run['head_sha'] != commit or run['head_branch'] != 'main' or run['repository']['full_name'] != repo or
            run['conclusion'] != 'success' or utc(run['created_at']) > run_receipt['retrieved_at_utc']):
        raise ValueError('GITHUB_SERVER_WITNESS_CONFLICT')
    entry = next((r for r in file_receipt['document'] if r['path'] == item['repo_file']), None)
    if not entry or entry['type'] != 'file': raise ValueError('ARCHIVE_BLOB_ENTRY_MISSING')
    raw = pinned(item['data'])
    blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if entry['sha'] != blob or entry['size'] != len(raw): raise ValueError('GIT_NATIVE_BLOB_HASH_MISMATCH')
    return raw, dict(at=utc(run['created_at']), source_sha256=hashlib.sha256(raw).hexdigest(),
        evidence_id=f'https://github.com/{repo}/actions/runs/{run["id"]}', authority='GITHUB_SERVER_RUN_HEAD_COMMIT',
        observed=item['observed_at_utc'], kind=item['kind'], commit=commit, blob=blob)


def wiki_revision(item):
    receipt = json.loads(pinned(item['data'])); uri = urlparse(receipt['source_url'])
    if uri.netloc != 'en.wikipedia.org' or uri.path != '/w/api.php': raise ValueError('WIKI_ARCHIVE_AUTHORITY_REQUIRED')
    pages = list(receipt['document']['query']['pages'].values())
    if len(pages) != 1: raise ValueError('ONE_ARCHIVED_PAGE_REQUIRED')
    page = pages[0]; expected = f'{item["year"]}–{str(item["year"]+1)[-2:]} EuroLeague regular season'
    if page['title'] != expected: raise ValueError('WIKI_SEASON_TITLE_CONFLICT')
    revision = page['revisions'][0]; text = revision['slots']['main']['*']
    if hashlib.sha1(text.encode()).hexdigest() != revision['sha1']: raise ValueError('WIKI_NATIVE_REVISION_HASH_MISMATCH')
    at = utc(revision['timestamp'])
    if at > receipt['observed_at_utc']: raise ValueError('FUTURE_ARCHIVE_REVISION')
    if 'Central European Time' not in text or 'Central European Summer Time' not in text:
        raise ValueError('WIKI_SCHEDULE_TIMEZONE_NOT_DECLARED')
    return text, dict(at=at, source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        evidence_id='https://en.wikipedia.org/w/index.php?oldid='+str(revision['revid']),
        authority='WIKIMEDIA_IMMUTABLE_REVISION', observed=receipt['observed_at_utc'], year=item['year'])


def templates(text):
    """Balanced top-level fields; pipes in flags, references and wikilinks stay nested."""
    for match in re.finditer(r'\{\{basketballbox\b', text, re.I):
        i = match.start()+2; depth = 1; link = 0; start = i; parts = []
        while i < len(text) and depth:
            pair = text[i:i+2]
            if pair == '{{': depth += 1; i += 2; continue
            if pair == '}}':
                depth -= 1
                if depth == 0: parts.append(text[start:i]); break
                i += 2; continue
            if pair == '[[': link += 1; i += 2; continue
            if pair == ']]': link -= 1; i += 2; continue
            if text[i] == '|' and depth == 1 and link == 0:
                parts.append(text[start:i]); start = i+1
            i += 1
        if depth: raise ValueError('UNBALANCED_ARCHIVED_BASKETBALL_TEMPLATE')
        fields = {}
        for part in parts[1:]:
            if '=' not in part: continue
            key, value = part.split('=', 1); key = key.strip().casefold()
            if key in fields: raise ValueError('DUPLICATE_ARCHIVE_TEMPLATE_FIELD')
            fields[key] = value.strip()
        yield fields


def clean(value):
    value = re.sub(r'<ref\b[^>]*>.*?</ref>|<ref\b[^>]*/>', '', value, flags=re.S)
    value = re.sub(r'\{\{[^{}]*\}\}', '', value)
    value = re.sub(r'\[\[([^\]]+)\]\]', lambda m: m.group(1).rsplit('|', 1)[-1], value)
    return html.unescape(value.replace("'", '')).strip()


def wiki_games(text, year):
    for f in templates(text):
        link = re.search(r'https://www\.euroleaguebasketball\.net/[^\s|]*?/E(\d{4})/(\d+)', f.get('report', ''))
        if not link or int(link[1]) != year: continue
        day = clean(f.get('date', '')); clock = clean(f.get('time', ''))
        if not re.fullmatch(r'\d{2}:\d{2}', clock): continue
        try: start = int(datetime.strptime(day+' '+clock, '%d %B %Y %H:%M').replace(tzinfo=ZoneInfo('Europe/Berlin')).timestamp())
        except ValueError: continue
        record = dict(pid=f'E{year}_{int(link[2])}', league='EuroLeague', season=f'{year}/{year+1}',
            fixture_start_utc=start, home_name=clean(f.get('teama', '')), away_name=clean(f.get('teamb', '')), final_scores=None, periods=None)
        if all(re.fullmatch(r'\d{1,3}', clean(f.get(k, ''))) for k in ('scorea', 'scoreb')):
            scores = [int(clean(f[k])) for k in ('scorea', 'scoreb')]; parts = [[], []]
            keys = ['q1','q2','q3','q4']+[k for k in ('ot','ot2','ot3','ot4') if clean(f.get(k, ''))]
            for key in keys:
                pair = re.fullmatch(r'(\d{1,3})\s*[–−-]\s*(\d{1,3})', clean(f.get(key, '')))
                if not pair: break
                for side in range(2): parts[side].append(int(pair[side+1]))
            if len(parts[0]) >= 4 and [sum(v) for v in parts] == scores:
                record.update(final_scores=scores, periods=dict(home=parts[0], away=parts[1]))
        yield record


def count(value, maximum=1000):
    if isinstance(value, bool): raise ValueError('BOOLEAN_IS_NOT_ARCHIVED_COUNT')
    number = float(value)
    if not number.is_integer() or not 0 <= number <= maximum: raise ValueError('INVALID_ARCHIVED_STAT_COUNT')
    return int(number)


def nba_periods(value):
    if not isinstance(value, str) or len(value) > 4000: raise ValueError('ARCHIVED_PERIOD_STRING_REQUIRED')
    # hoopR stored a numpy object-array repr, whose adjacent dictionaries lack commas.
    values = ast.literal_eval(re.sub(r'}\s+{', '},{', value))
    if not isinstance(values, list) or not 4 <= len(values) <= 12: raise ValueError('FOUR_ARCHIVED_PERIODS_REQUIRED')
    return [count(p['value']) for p in values]


def nba_schedule(raw, diagnostics=None):
    import io
    import pandas as pd
    frame = pd.read_parquet(io.BytesIO(raw))
    required = {'season','season_type','id','date','home_id','away_id','status_type_completed','status_type_state','home_score','away_score','home_linescores','away_linescores'}
    if not required <= set(frame): raise ValueError('ARCHIVE_SCHEDULE_COLUMNS_MISSING')
    for row in frame.to_dict('records'):
        if count(row['season'], 2100) != 2027 or count(row['season_type']) != 2: continue
        # NBA Cup placeholder slots have native IDs -1/-2 (TBD), not teams.
        if row['home_id'] in (-1, -2) or row['away_id'] in (-1, -2):
            if diagnostics is not None: diagnostics['NBA_TBD_TEAM_SLOT_EXCLUDED'] += 1
            continue
        record = dict(pid=str(count(row['id'], 10**12)), league='NBA', season='2026/2027', fixture_start_utc=utc(row['date']),
            home_team_id=str(count(row['home_id'])), away_team_id=str(count(row['away_id'])), final_scores=None, periods=None)
        if row['status_type_completed'] is True and row['status_type_state'] == 'post':
            scores = [count(row[s+'_score']) for s in ('home','away')]
            try: parts = {s: nba_periods(row[s+'_linescores']) for s in ('home','away')}
            except (ValueError, SyntaxError): continue
            if [sum(parts[s]) for s in ('home','away')] != scores: raise ValueError('ARCHIVE_PERIOD_FINAL_CONFLICT')
            record.update(final_scores=scores, periods=parts)
        yield record


def nba_boxes(raw, diagnostics=None):
    import io
    import pandas as pd
    from hybrid_engine.boxes import checked_stats
    frame = pd.read_parquet(io.BytesIO(raw)); groups = {}
    for row in frame.to_dict('records'):
        if count(row['season'], 2100) != 2027 or count(row['season_type']) != 2: continue
        pid = str(count(row['game_id'], 10**12)); side = row['team_home_away']
        if side not in ('home','away') or side in groups.setdefault(pid, {}): raise ValueError('ARCHIVE_BOX_SIDE_CONFLICT')
        if count(row['total_turnovers']) != count(row['turnovers'])+count(row['team_turnovers']):
            if diagnostics is not None: diagnostics['NBA_BOX_TOTAL_TURNOVER_CONFLICT:'+pid] += 1
            continue
        stats = dict(fgm2=count(row['field_goals_made'])-count(row['three_point_field_goals_made']),
            fga2=count(row['field_goals_attempted'])-count(row['three_point_field_goals_attempted']),
            fgm3=count(row['three_point_field_goals_made']), fga3=count(row['three_point_field_goals_attempted']),
            ftm=count(row['free_throws_made']), fta=count(row['free_throws_attempted']),
            orb=count(row['offensive_rebounds']), drb=count(row['defensive_rebounds']),
            tov=count(row['total_turnovers']), fouls=count(row['fouls']), points=count(row['team_score']))
        groups[pid][side] = dict(team_id=str(count(row['team_id'])), stats=checked_stats(stats))
    return groups


def euro_public_games(raw, *, competition, year):
    """Read JSON constants only; never execute JS or import its predictions/aggregates."""
    if competition!='U':raise ValueError('PUBLIC_GAME_COMPETITION_NOT_CONFIGURED')
    text=raw.decode('utf-8');values={}
    for line in text.splitlines():
        m=re.fullmatch(r'const (SEASON|GAMES) = (.*);',line)
        if m:
            if m[1] in values:raise ValueError('DUPLICATE_PUBLIC_GAME_CONSTANT')
            values[m[1]]=json.loads(m[2])
    if values.get('SEASON')!=f'{year}-{str(year+1)[-2:]}' or not isinstance(values.get('GAMES'),list):
        raise ValueError('PUBLIC_GAME_SEASON_OR_JSON_REQUIRED')
    if len(values['GAMES'])>5000:raise ValueError('PUBLIC_GAME_COUNT_BUDGET')
    for g in values['GAMES']:
        if not isinstance(g['utc'],str) or not g['utc'].endswith('Z'):raise ValueError('PUBLIC_GAME_EXPLICIT_UTC_REQUIRED')
        if any(not isinstance(g[s],str) or not re.fullmatch(r'[A-Z0-9]{1,8}',g[s]) for s in ('home','away')) or g['home']==g['away']:
            raise ValueError('PUBLIC_GAME_TEAM_ID_REQUIRED')
        record=dict(pid=f'U{year}_{count(g["code"],10000)}',league='EuroCup',season=f'{year}/{year+1}',
            fixture_start_utc=utc(g['utc']),home_team_id=g['home'],away_team_id=g['away'],final_scores=None,periods=None)
        if g.get('score') is not None:
            scores=g['score'];quarters=g.get('quarters')
            if not isinstance(scores,list) or len(scores)!=2 or not isinstance(quarters,list) or len(quarters)!=2:
                raise ValueError('PUBLIC_GAME_FINAL_PERIODS_REQUIRED')
            scores=[count(v) for v in scores]
            parts={s:[count(v) for v in quarters[i]] for i,s in enumerate(('home','away'))}
            if not 4<=len(parts['home'])==len(parts['away'])<=12 or [sum(parts[s]) for s in ('home','away')]!=scores:
                raise ValueError('PUBLIC_GAME_PERIOD_FINAL_CONFLICT')
            if any(sum(parts['home'][:n])!=sum(parts['away'][:n]) for n in range(4,len(parts['home']))):
                raise ValueError('PUBLIC_GAME_OVERTIME_WITHOUT_TIE')
            record.update(final_scores=scores,periods=parts)
        yield record


# Explicit research crosswalk; no fuzzy matching and no production identity changes.
WIKI_ALIASES = {'ULK':['Fenerbahçe Beko'], 'PAN':['Panathinaikos AKTOR'], 'MUN':['Bayern Munich'],
    'PAR':['Partizan Mozzart Bet'], 'RED':['Crvena zvezda Meridianbet'], 'MIL':['EA7 Emporio Armani Milano','Olimpia Milano'],
    'ASV':['ASVEL','LDLC ASVEL'], 'ZAL':['Žalgiris'], 'BAS':['Kosner Baskonia'], 'HTA':['Hapoel IBI Tel Aviv'],
    'BAR':['Barcelona']}


def bind_archives(cohort, provenance, archive_items, team_names):
    """Attach validated temporal versions; preserve current native truth for evaluation."""
    native = {}; counters = Counter(); knowledge = []; exclusions = []; sampled = Counter()
    for group in cohort:
        for row in group: row['_native_truth'] = True
        row = group[0]
        for pid in row['provider_fixture_ids']: native[(row['league'], row['season'], pid)] = group
    decoded = []; schedule = {}; boxes = []
    for item in archive_items:
        if item['kind'] == 'WIKI':
            text, source = wiki_revision(item)
            decoded.append((list(wiki_games(text, item['year'])), source))
        else:
            raw, source = github_blob(item)
            if item['kind'] == 'NBA_SCHEDULE':
                records = list(nba_schedule(raw, counters)); decoded.append((records, source))
                for record in records: schedule[(item['commit'], record['pid'])] = record
            elif item['kind'] == 'NBA_BOX': boxes.append((nba_boxes(raw, counters), source))
            elif item['kind'] == 'EURO_PUBLIC_GAMES':
                if item['repo']!='tomlebedev-cloud/eurocup' or item['repo_file']!='js/data.js':
                    raise ValueError('PUBLIC_GAME_SOURCE_NOT_CONFIGURED')
                decoded.append((list(euro_public_games(raw,competition=item['competition'],year=item['year'])),source))
            elif item['kind'] in ('NBA_QUOTES','EURO_PLAYERS'):
                counters[item['kind']+'_ARCHIVE_VERIFIED_NOT_CORE_CLOCK'] += 1
            else: raise ValueError('UNKNOWN_PUBLIC_ARCHIVE_ADAPTER')
    def reject(reason, record, source, truth=None):
        counters[reason] += 1
        if sampled[reason] < 3:
            exclusions.append(dict(reason=reason, archived=record, evidence_id=source['evidence_id'],
                native=None if truth is None else {k:truth[k] for k in ('fixture_id','fixture_start_utc','home_team_id','away_team_id','final_scores','periods')}))
            sampled[reason] += 1
    def identity(record, source):
        group = native.get((record['league'], record['season'], record['pid']))
        if group is None:
            reject('ARCHIVE_GAME_OUTSIDE_CURRENT_LABEL_COHORT', record, source); return None
        truth = group[0]
        if record['fixture_start_utc'] != truth['fixture_start_utc']:
            reject('ARCHIVED_SCHEDULE_TIME_DIFFERS_FROM_FINAL', record, source, truth); return None
        if 'home_team_id' in record:
            valid = all(record[s+'_team_id'] == truth[s+'_team_id'] for s in ('home','away'))
        else:
            valid = True
            for side in ('home','away'):
                code = truth[side+'_team_id']; names = team_names.get((truth['league'], truth['season'], code), [])+WIKI_ALIASES.get(code, [])
                if normalize_name(record[side+'_name']) not in {normalize_name(n) for n in names}:
                    reject('UNREGISTERED_WIKI_TEAM_ALIAS:'+code+':'+record[side+'_name'], record, source, truth); valid = False
        if not valid:
            reject('ARCHIVE_TEAM_IDENTITY_CONFLICT', record, source, truth); return None
        return group
    def proof(record, scope, source):
        return certify(record, scope=scope, at=source['at'], source_sha256=source['source_sha256'],
            evidence_id=source['evidence_id'], authority=source['authority'])
    now = int(time.time())
    for records, source in decoded:
        for record in records:
            group = identity(record, source)
            if group is None: continue
            truth = group[0]
            base = {k: truth[k] for k in ('league','season','fixture_id','fixture_start_utc','home_team_id','away_team_id')}
            fixture = dict(base, observed_at_utc=source['observed'], ingested_at_utc=now,
                provider='PUBLIC_ARCHIVE', source_catalog_sha256=source['source_sha256'])
            knowledge.append(proof(fixture, 'FIXTURE', source)); counters['ARCHIVED_FIXTURE_VERSIONS'] += 1
            if record['periods'] is None: continue
            if source['at'] <= record['fixture_start_utc']:
                counters['ARCHIVE_FINAL_BEFORE_GAME_START_REJECTED'] += 1; continue
            score_fields = dict(final_scores=record['final_scores'], periods=record['periods'])
            if source['authority'] == 'WIKIMEDIA_IMMUTABLE_REVISION' or source.get('kind')=='EURO_PUBLIC_GAMES':
                # A basketball template has no primary final-status flag. Reject
                # intraday/live revisions and require the archived score/periods to
                # match the adjudicated native final; never copy late values back.
                prefix='WIKI' if source['authority']=='WIKIMEDIA_IMMUTABLE_REVISION' else 'PUBLIC_GAME'
                if source['at']//86400 <= record['fixture_start_utc']//86400:
                    reject(prefix+'_INTRADAY_FINAL_STATUS_UNPROVEN', record, source, truth); continue
                if any(score_fields[k] != truth[k] for k in score_fields):
                    reject(prefix+'_FINAL_NATIVE_RECONCILIATION_CONFLICT', record, source, truth); continue
            if all(score_fields[k] == truth[k] for k in score_fields):
                counters['ARCHIVED_CORE_MATCHES_CURRENT_TRUTH'] += 1
            else:
                counters['ARCHIVED_HISTORICAL_VALUE_REVISION'] += 1
            # Keep A -> B -> A revisions, even when the final value equals an older one.
            # Current adjudicated truth is never given a fabricated old observation time.
            version = dict(base, **score_fields, record_type='HISTORICAL_DATA', provider='PUBLIC_ARCHIVE',
                provider_fixture_ids=truth['provider_fixture_ids'], source_catalog_sha256=source['source_sha256'],
                observed_at_utc=source['observed'], ingested_at_utc=now, _native_truth=False)
            group.append(proof(version, 'CORE', source))
    for groups, source in boxes:
        for pid, sides in groups.items():
            record = schedule.get((source['commit'], pid))
            if record is None or record['periods'] is None or set(sides) != {'home','away'}: continue
            group = identity(record, source)
            if group is None: continue
            truth = group[0]
            if (any(sides[s]['team_id'] != truth[s+'_team_id'] for s in sides) or
                    [sides[s]['stats']['points'] for s in ('home','away')] != record['final_scores']):
                raise ValueError('ARCHIVED_BOX_SCHEDULE_IDENTITY_OR_SCORE_CONFLICT')
            box = {k: truth[k] for k in ('league','season','fixture_id','fixture_start_utc','home_team_id','away_team_id')}
            receipt = dict(provider='ESPN_VIA_GITHUB', observed_at_utc=source['observed'], ingested_at_utc=now,
                source_url=source['evidence_id'], document_sha256=source['source_sha256'])
            box.update(teams={s:sides[s]['stats'] for s in ('home','away')}, source=receipt, source_digest=digest(receipt),
                regulation_eligible=len(record['periods']['home']) == len(record['periods']['away']) == 4,
                scope='FINAL_WITH_OT', missing=['PREMATCH_LINEUP','INJURIES','CONTEXT_TRANSITION_ANNOTATIONS'])
            box = proof(box, 'BOX', source)
            for row in group:
                row.setdefault('box_versions', []).append(box)
                if not row.get('box'): row['box'] = box
            counters['ARCHIVED_BOX_VERSIONS'] += 1
    provenance['fixture_knowledge'].extend(knowledge)
    provenance['archive_binding'] = dict(counters=counters, sampled_exclusions=exclusions, independent_sources=len(archive_items),
        source_time_policy='PUBLIC_ARCHIVE_VERSION_WITNESS_NOT_LOCAL_RETRIEVAL', current_truth_preserved=True)
    return cohort, provenance
