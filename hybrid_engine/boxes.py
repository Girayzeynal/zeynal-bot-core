"""Free native final box-score observations, never backdated roster/pace facts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
import time

from core.team_identity import digest
from hybrid_engine.data import Abstain, local_path
from season_archive_collect import fetch_document

FT_COEFFICIENT = 0.44  # Conventional box-score estimate, not measured possessions.


def publish_json(path, value):
    path = local_path(path)
    body = (json.dumps(value, sort_keys=True, allow_nan=False)+'\n').encode()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.box-', delete=False) as f:
            temporary = Path(f.name); f.write(body); f.flush(); os.fsync(f.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != body:
                raise ValueError('BOX_ARCHIVE_CONTENT_CONFLICT')
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def seconds(value):
    if isinstance(value, bool): raise ValueError('INVALID_PLAYER_SECONDS')
    x = float(value)
    if not math.isfinite(x) or not x.is_integer() or not 0 <= x <= 7200:
        raise ValueError('INVALID_PLAYER_SECONDS')
    return int(x)


def integer(value):
    if isinstance(value, bool):
        raise ValueError('INVALID_BOX_INTEGER')
    x = float(value)
    if not math.isfinite(x) or not x.is_integer() or not 0 <= x <= 1000:
        raise ValueError('INVALID_BOX_INTEGER')
    return int(x)


def pair(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\s*-\s*\d+', value):
        raise ValueError('INVALID_MADE_ATTEMPTED_PAIR')
    made, attempted = (integer(v.strip()) for v in value.split('-'))
    if made > attempted:
        raise ValueError('MADE_EXCEEDS_ATTEMPTED')
    return made, attempted


def url_for(row):
    ids = row['provider_fixture_ids']
    if row['provider'] == 'ESPN':
        if row['league']!='NBA': raise ValueError('NBA_PROVIDER_LEAGUE_REQUIRED')
        if len(ids) != 1 or not re.fullmatch(r'[0-9]+', ids[0]):
            raise ValueError('NBA_BOX_ID_REQUIRED')
        return 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=' + ids[0]
    competition = {'EuroLeague':'E','EuroCup':'U'}.get(row['league'])
    if competition is None: raise ValueError('EURO_COMPETITION_ID_REQUIRED')
    matches = [re.fullmatch(r'('+competition+r')(20[0-9]{2})_([0-9]+)', s) for s in ids]
    matches = [m for m in matches if m]
    if len(matches) != 1 or matches[0][2] != row['season'].split('/')[0]:
        raise ValueError('EUROLEAGUE_BOX_ID_REQUIRED')
    m = matches[0]
    return f'https://api-live.euroleague.net/v2/competitions/{m[1]}/seasons/{m[1]}{m[2]}/games/{m[3]}/stats'


def checked_stats(s):
    names = ('fgm2', 'fga2', 'fgm3', 'fga3', 'ftm', 'fta', 'orb', 'drb', 'tov', 'fouls', 'points')
    x = {k: integer(s[k]) for k in names}
    if any(x[m] > x[a] for m, a in [('fgm2', 'fga2'), ('fgm3', 'fga3'), ('ftm', 'fta')]):
        raise ValueError('MADE_EXCEEDS_ATTEMPTED')
    if 2*x['fgm2'] + 3*x['fgm3'] + x['ftm'] != x['points']:
        raise ValueError('BOX_SCORE_ARITHMETIC_CONFLICT')
    x['possessions_estimate'] = x['fga2'] + x['fga3'] + FT_COEFFICIENT*x['fta'] - x['orb'] + x['tov']
    if x['possessions_estimate'] <= 0:
        raise ValueError('NONPOSITIVE_ESTIMATED_POSSESSIONS')
    return x


def normalize_box(row, receipt):
    url = url_for(row)
    if (receipt.get('status') != 'DOCUMENT_RECEIVED' or receipt.get('http_status') != 200 or
            receipt.get('source_url') != url or receipt.get('provider') != row['provider'] or
            digest(receipt['document']) != receipt.get('document_sha256')):
        raise ValueError('BOX_SOURCE_BINDING_MISMATCH')
    o, i = receipt['observed_at_utc'], receipt['ingested_at_utc']
    if type(o) is not int or type(i) is not int or not 0 < o <= i <= int(time.time()):
        raise ValueError('INVALID_BOX_SOURCE_CLOCK')
    d = receipt['document']; teams = {}; players = []
    if row['provider'] == 'ESPN':
        header = d['header']; c = header['competitions'][0]
        status = c['status']['type']
        if (header['id'] not in row['provider_fixture_ids'] or c['id'] != header['id'] or header['league']['slug'] != 'nba' or
                header['season']['year'] != int(row['season'].split('/')[0])+1 or
                header['season']['type'] != 2 or status.get('completed') is not True or status.get('state') != 'post' or
                int(datetime.fromisoformat(c['date'].replace('Z', '+00:00')).timestamp()) != row['fixture_start_utc']):
            raise ValueError('NBA_BOX_FINAL_IDENTITY_CONFLICT')
        sides = {x['team']['id']: x['homeAway'] for x in c['competitors']}
        if sides != {row['home_team_id']: 'home', row['away_team_id']: 'away'}:
            raise ValueError('BOX_TEAM_IDENTITY_CONFLICT')
        for team in c['competitors']:
            periods = [integer(p.get('value', p.get('displayValue'))) for p in team.get('linescores', [])]
            if row['periods'] is None or periods != row['periods'][team['homeAway']]:
                raise ValueError('BOX_PERIOD_SOURCE_CONFLICT')
        for entry in d['boxscore']['teams']:
            side = sides[entry['team']['id']]
            s = {v['name']: v['displayValue'] for v in entry['statistics']}
            fg, fga = pair(s['fieldGoalsMade-fieldGoalsAttempted'])
            fg3, fga3 = pair(s['threePointFieldGoalsMade-threePointFieldGoalsAttempted'])
            ft, fta = pair(s['freeThrowsMade-freeThrowsAttempted'])
            final = next(x['score'] for x in c['competitors'] if x['homeAway'] == side)
            if 'totalTurnovers' in s:
                turnovers = integer(s['totalTurnovers'])
                if 'teamTurnovers' in s and turnovers != integer(s['turnovers'])+integer(s['teamTurnovers']):
                    raise ValueError('TURNOVER_TOTAL_CONFLICT')
            elif 'teamTurnovers' in s:
                turnovers = integer(s['turnovers'])+integer(s['teamTurnovers'])
            else:
                raise Abstain('TOTAL_TURNOVERS_NOT_VERIFIABLE')
            teams[side] = checked_stats(dict(fgm2=fg-fg3, fga2=fga-fga3, fgm3=fg3, fga3=fga3,
                ftm=ft, fta=fta, orb=s['offensiveRebounds'], drb=s['defensiveRebounds'],
                tov=turnovers, fouls=s['fouls'], points=final))
        for team in d.get('boxscore', {}).get('players', []):
            side = sides[team['team']['id']]
            for group in team.get('statistics', []):
                for p in group.get('athletes', []):
                    stats = dict(zip(group['names'], p.get('stats', [])))
                    players.append(dict(player_id=p['athlete']['id'], team_id=team['team']['id'], side=side,
                        minutes_display=stats.get('MIN'), minute_precision='PROVIDER_DISPLAY_NOT_EXACT_SECONDS',
                        points=None if 'PTS' not in stats else integer(stats['PTS']),
                        historical_starter=p.get('starter'), did_not_play=p.get('didNotPlay'),
                        data_kind='POSTGAME_ACTUAL_NOT_PREMATCH_LINEUP'))
    elif row['provider'] == 'EUROLEAGUE_LIVE':
        for native, side in [('local', 'home'), ('road', 'away')]:
            s = d[native]['total']
            teams[side] = checked_stats(dict(fgm2=s['fieldGoalsMade2'], fga2=s['fieldGoalsAttempted2'],
                fgm3=s['fieldGoalsMade3'], fga3=s['fieldGoalsAttempted3'], ftm=s['freeThrowsMade'],
                fta=s['freeThrowsAttempted'], orb=s['offensiveRebounds'], drb=s['defensiveRebounds'],
                tov=s['turnovers'], fouls=s['foulsCommited'], points=s['points']))
            for p in d[native]['players']:
                code = 'U' if row['league']=='EuroCup' else 'E'
                if p['player']['club']['code'] != row[side+'_team_id'] or p['player']['season']['code'] != code+row['season'].split('/')[0]:
                    raise ValueError('EURO_PLAYER_TEAM_OR_SEASON_CONFLICT')
                players.append(dict(player_id=p['player']['person']['code'], team_id=row[side+'_team_id'], side=side,
                    seconds_played=seconds(p['stats']['timePlayed']),
                    points=integer(p['stats']['points']), historical_starter=p['stats'].get('startFive'),
                    data_kind='POSTGAME_ACTUAL_NOT_PREMATCH_LINEUP'))
    else:
        raise ValueError('BOX_ADAPTER_NOT_AVAILABLE')
    if set(teams) != {'home', 'away'} or [teams[s]['points'] for s in ('home', 'away')] != row['final_scores']:
        raise ValueError('BOX_FINAL_SCORE_CONFLICT')
    source = {k: v for k, v in receipt.items() if k != 'document'}
    return dict(league=row['league'], season=row['season'], fixture_id=row['fixture_id'],
        fixture_start_utc=row['fixture_start_utc'], home_team_id=row['home_team_id'], away_team_id=row['away_team_id'],
        provider_fixture_ids=row['provider_fixture_ids'], teams=teams, players=players,
        source=source, source_digest=digest(source), scope='FINAL_WITH_OT',
        regulation_eligible=len(row['periods']['home']) == len(row['periods']['away']) == 4,
        possession_measurement='BOX_ESTIMATE_FGA_PLUS_0.44FTA_MINUS_ORB_PLUS_TOTAL_TOV',
        pbp_status='NOT_NORMALIZED_IN_THIS_BOX_ADAPTER',
        missing=['PREMATCH_LINEUP', 'INJURIES', 'CONTEXT_TRANSITION_ANNOTATIONS'])


def collect_boxes(cohort, directory, *, fetcher=fetch_document, workers=4, interval=0.0):
    """Explicit offline acquisition. Does not mutate catalogs, predictions or original source clocks."""
    root = local_path(directory); root.mkdir(exist_ok=True)
    raw_root = root/'box-receipts'; raw_root.mkdir(exist_ok=True)
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('BOUNDED_SOURCE_CONCURRENCY_REQUIRED')
    if not math.isfinite(interval) or not 0 <= interval <= 5:
        raise ValueError('BOUNDED_SOURCE_INTERVAL_REQUIRED')
    lock = Lock(); cooldown = {}; last_call = {}
    for p in root.glob('cooldown-*.json'):
        state = json.loads(p.read_text())
        cooldown[state['provider']] = max(cooldown.get(state['provider'], 0), state['until_utc'])
    targets = [versions[0] for versions in cohort]
    def collect(row):
        try:
            url = url_for(row)
            cache = raw_root/(digest(dict(provider=row['provider'], url=url))+'.json')
            if cache.exists():
                receipt = json.loads(cache.read_text())
            else:
                with lock:
                    provider = row['provider']
                    if cooldown.get(provider, 0) > time.time():
                        return None, dict(fixture_id=row['fixture_id'], reason='SOURCE_COOLDOWN_ACTIVE',
                            retry_at_utc=cooldown[provider])
                    delay = max(0., last_call.get(provider, 0)+interval-time.monotonic())
                    if delay: time.sleep(delay)
                    last_call[provider] = time.monotonic()
                receipt = fetcher(row['provider'], url)
                if receipt.get('status') != 'DOCUMENT_RECEIVED':
                    if receipt.get('http_status') in (403, 429):
                        with lock:
                            until = int(time.time())+max(60, receipt.get('retry_after_seconds', 60))
                            cooldown[row['provider']] = max(cooldown.get(row['provider'], 0), until)
                            state = dict(provider=row['provider'], until_utc=cooldown[row['provider']],
                                         http_status=receipt['http_status'])
                            publish_json(root/('cooldown-'+digest(state)+'.json'), state)
                    return None, dict(fixture_id=row['fixture_id'], reason=receipt.get('status', 'SOURCE_ERROR'),
                        http_status=receipt.get('http_status'), retry_after_seconds=receipt.get('retry_after_seconds'))
                # Exclusive publication; an existing observation is never overwritten.
                publish_json(cache, receipt)
            return normalize_box(row, receipt), None
        except (ValueError, KeyError, TypeError, OSError) as exc:
            return None, dict(fixture_id=row['fixture_id'], reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
    games, failures = [], []
    with ThreadPoolExecutor(workers) as pool:
        for index, (game, failure) in enumerate(pool.map(collect, targets), 1):
            if game: games.append(game)
            else: failures.append(failure)
            if index % 50 == 0:
                print(json.dumps(dict(box_progress=index, verified=len(games), failures=len(failures))), flush=True)
    result = dict(format='HYBRID_BOX_ARCHIVE_V1', games=games, failures=failures,
        retrospective=True, live_predictions_created=0, original_catalogs_modified=False,
        source_attestation='LOCAL_HASH_NOT_INDEPENDENT_ATTESTATION')
    path = root/('boxes-'+digest(result)+'.json')
    publish_json(path, result)
    return path, result
