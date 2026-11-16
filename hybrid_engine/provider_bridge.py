"""Isolated current-provider evidence, explicitly separate from frozen forecasts.

No refit, probability calibration, player adjustment, settlement-rule invention
or forecast write is performed. A current source never becomes historical PIT
evidence merely because the requested forecast is old.
"""
from datetime import datetime, timezone
import html
import json
import math
import re
import threading
import time

from core.league_identity import normalize_name
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.market_observations import VERSION, fixture_identity, quote_rows, validate
from hybrid_engine.provider_access import ProviderAccess

SPORTS = {'NBA': 'basketball_nba', 'EUROLEAGUE': 'basketball_euroleague'}
# Requests beyond the three featured markets require explicit local opt-in.
CORE_MARKETS = ('h2h', 'spreads', 'totals')
EXTRA_MARKETS = ('alternate_spreads', 'alternate_totals', 'team_totals',
                 'totals_h1', 'totals_h2', 'totals_q1', 'totals_q2', 'totals_q3', 'totals_q4')
ALIASES = {'losangelesclippers': 'laclippers'}


def name(value):
    key = normalize_name(value)
    return ALIASES.get(key, key)


def utc(value):
    if not isinstance(value, str):
        raise ValueError('EXPLICIT_PROVIDER_UTC_REQUIRED')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('EXPLICIT_PROVIDER_UTC_REQUIRED')
    return int(dt.timestamp())


def matches(event, snapshot, *, basketball=False):
    try:
        if basketball:
            h, a = event['teams']['home']['name'], event['teams']['away']['name']
            start = utc(event['date'])
        else:
            h, a = event['home_team'], event['away_team']
            start = utc(event['commence_time'])
        return (name(h) == name(snapshot['home']['official_name']) and
                name(a) == name(snapshot['away']['official_name']) and
                start == snapshot['fixture_start_utc'])
    except (KeyError, ValueError, TypeError):
        return False


def fixture_for(snapshot):
    from hybrid_engine.decision_audit import trace_for
    trace = trace_for(snapshot)
    return fixture_identity({k: trace[k] for k in
                             ('league', 'season', 'fixture_id', 'home_team_id', 'away_team_id', 'tipoff_utc')})


def odds_observations(receipt, snapshot):
    """Match exact teams+tipoff; keep actual books, alternative lines and periods."""
    if digest(receipt['document']) != receipt['document_sha256']:
        raise ValueError('PROVIDER_DOCUMENT_PIN')
    event = receipt['document']
    if not matches(event, snapshot) or event.get('sport_key') != SPORTS.get(snapshot['league']):
        raise ValueError('ODDS_EVENT_IDENTITY_CONFLICT')
    fixture = fixture_for(snapshot)
    result = []
    rejected = 0
    for book in event.get('bookmakers', [])[:6]:
        if not isinstance(book.get('key'), str) or not isinstance(book.get('title'), str):
            rejected += 1
            continue
        for market in book.get('markets', [])[:32]:
            try:
                updated = utc(market.get('last_update') or book.get('last_update'))
                if not 0 <= receipt['observed_at_utc']-updated <= 300:
                    raise ValueError('STALE_OR_FUTURE_NATIVE_ODDS')
                key = market['key']
                period = 'FULL'
                match = re.fullmatch(r'(totals|spreads|h2h|team_totals)_(q[1-4]|h[12])', key)
                if match:
                    key, part = match.groups()
                    period = part[1]+part[0].upper()
                key = key.removeprefix('alternate_')
                if key not in ('totals', 'spreads', 'h2h', 'team_totals'):
                    continue
                grouped = {}
                for outcome in market.get('outcomes', [])[:128]:
                    price = outcome['price']
                    if type(price) not in (int, float) or not math.isfinite(price) or not 1 < price <= 1001:
                        raise ValueError('DECIMAL_PRICE_REQUIRED')
                    if key in ('totals', 'team_totals'):
                        side = {'Under': 'under', 'Over': 'over'}[outcome['name']]
                        kind = 'TOTAL'
                        if key == 'team_totals':
                            target = name(outcome['description'])
                            if target == name(snapshot['home']['official_name']):
                                kind = 'HOME'
                            elif target == name(snapshot['away']['official_name']):
                                kind = 'AWAY'
                            else:
                                raise ValueError('TEAM_TOTAL_IDENTITY')
                        line = outcome['point']
                    else:
                        target = name(outcome['name'])
                        if target == name(snapshot['home']['official_name']):
                            side = 'over'
                        elif target == name(snapshot['away']['official_name']):
                            side = 'under'
                        else:
                            raise ValueError('WINNER_OR_SPREAD_TEAM_IDENTITY')
                        kind = 'WINNER' if key == 'h2h' else 'HOME_HANDICAP'
                        point = 0 if key == 'h2h' else outcome['point']
                        if type(point) not in (int, float) or not math.isfinite(point):
                            raise ValueError('LINE_REQUIRED')
                        line = point if side == 'over' else -point
                    if type(line) not in (int, float) or not math.isfinite(line):
                        raise ValueError('LINE_REQUIRED')
                    prices = grouped.setdefault((kind, float(line)), {})
                    if side in prices:
                        raise ValueError('CONFLICTING_DUPLICATE_SIDE')
                    prices[side] = price
                rows = [dict(period=period, market=kind, line=line, prices=prices)
                        for (kind, line), prices in grouped.items() if set(prices) == {'under', 'over'}]
                if not rows:
                    raise ValueError('BOTH_MATCHING_PRICE_SIDES_REQUIRED')
                for start in range(0, min(len(rows), 64), 32):
                    payload = dict(format=VERSION, fixture=fixture,
                        bookmaker=dict(id=book['key'], name=book['title']),
                        source=dict(provider_id='THE_ODDS_API', provider_name='The Odds API',
                            method='NATIVE_RETRIEVAL', url=receipt['source_url'],
                            captured_at_utc=receipt['observed_at_utc'], published_at_utc=updated,
                            receipt_sha256=digest(receipt), document_sha256=receipt['document_sha256'],
                            native_quote_sha256=digest(dict(bookmaker_id=book['key'], market=market)),
                            attestation='LOCAL_NATIVE_RECEIPT_NOT_PROVIDER_SIGNATURE'),
                        available_at_utc=receipt['ingested_at_utc'],
                        quotes=quote_rows(fixture, book['key'], rows[start:start+32]),
                        settlement_verification='NOT_VERIFIED_BY_OBSERVATION', calibration_status='NOT_CALIBRATED')
                    validate(payload)
                    result.append(dict(payload=payload, sha256=digest(payload)))
                    if len(result) >= 12:
                        return result, rejected
            except (KeyError, TypeError, ValueError):
                rejected += 1
    return result, rejected


class ProviderBridge:
    def __init__(self, access, directory, *, extended=False, clock=time.time):
        self.access = access
        self.root = local_path(directory)
        self.extended = extended
        self.clock = clock
        self.lock = threading.Lock()

    def _save(self, payload):
        root = self.root
        body_bytes = len(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
        if root.exists():
            files = list(root.glob('provider-*.json'))
            if len(files) >= 256 or sum(p.stat().st_size for p in files)+body_bytes > 32*1024*1024:
                raise ValueError('PROVIDER_EVIDENCE_FILE_OR_STORAGE_BUDGET')
        root.mkdir(parents=True, exist_ok=True)
        wrapper = dict(payload=payload, sha256=digest(payload))
        publish_json(root/('provider-'+wrapper['sha256']+'.json'), wrapper)
        return wrapper['sha256']

    def _odds(self, snapshot, deadline):
        access = self.access
        sport = SPORTS.get(snapshot['league'])
        if sport is None:
            return dict(status='LEAGUE_NOT_MAPPED', observations=[])
        sports = access.get('THE_ODDS_API', '/v4/sports/', deadline=deadline, ttl=3600)
        if sports['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=sports['status'], observations=[])
        if not isinstance(sports['document'], list) or not any(
                x.get('key') == sport and x.get('active') is True for x in sports['document'] if isinstance(x, dict)):
            return dict(status='LEAGUE_NOT_AVAILABLE_FROM_PROVIDER', observations=[])
        events = access.get('THE_ODDS_API', f'/v4/sports/{sport}/events', deadline=deadline)
        if events['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=events['status'], observations=[])
        if not isinstance(events['document'], list):
            return dict(status='INVALID_PROVIDER_SCHEMA', observations=[])
        matched = [e for e in events['document'] if matches(e, snapshot)]
        if len(matched) != 1:
            return dict(status='EXACT_FIXTURE_MATCH_REQUIRED', observations=[], matching_events=len(matched))
        event_id = matched[0].get('id')
        if not isinstance(event_id, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}', event_id):
            return dict(status='PROVIDER_EVENT_ID_INVALID', observations=[])
        markets = (*CORE_MARKETS, *EXTRA_MARKETS) if self.extended else CORE_MARKETS
        r = access.get('THE_ODDS_API', f'/v4/sports/{sport}/events/{event_id}/odds',
                       dict(regions='us', markets=','.join(markets), oddsFormat='decimal'), deadline=deadline)
        if r['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=r['status'], observations=[])
        observations, rejected = odds_observations(r, snapshot)
        return dict(status='OBSERVED_RULES_AND_CALIBRATION_PENDING' if observations else 'NO_FRESH_SUPPORTED_PRICES',
                    observations=observations, rejected_markets=rejected, requested_markets=list(markets),
                    quota=r.get('quota', {}), source_pin=self._save(r),
                    provider_fixture_id=event_id, forecast_inputs_changed=False)

    def _basketball(self, snapshot, deadline):
        access = self.access
        league = {'NBA': 'NBA', 'EUROLEAGUE': 'Euroleague', 'EUROCUP': 'Eurocup'}.get(snapshot['league'])
        if league is None:
            return dict(status='LEAGUE_NOT_MAPPED')
        r = access.get('API_BASKETBALL', '/leagues', dict(name=league), deadline=deadline, ttl=3600)
        if r['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=r['status'])
        if r['document'].get('errors'):
            return dict(status='PROVIDER_REPORTED_ERROR')
        leagues = [x for x in r['document'].get('response', []) if name(x.get('name', '')) == name(league)]
        if len(leagues) != 1 or type(leagues[0].get('id')) is not int:
            return dict(status='EXACT_LEAGUE_MAPPING_REQUIRED')
        lid = leagues[0]['id']
        day = datetime.fromtimestamp(snapshot['fixture_start_utc'], timezone.utc).strftime('%Y-%m-%d')
        r = access.get('API_BASKETBALL', '/games',
                       dict(league=lid, date=day, timezone='UTC'), deadline=deadline)
        if r['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=r['status'])
        if r['document'].get('errors'):
            return dict(status='PROVIDER_REPORTED_ERROR')
        games = [x for x in r['document'].get('response', []) if matches(x, snapshot, basketball=True)]
        if len(games) != 1:
            return dict(status='EXACT_FIXTURE_MATCH_REQUIRED', matching_events=len(games))
        g = games[0]
        if (g.get('status', {}).get('short') != 'NS' or g.get('league', {}).get('id') != lid or
                type(g.get('id')) is not int):
            return dict(status='PROVIDER_FIXTURE_NOT_VERIFIED_PREMATCH')
        if int(self.clock()) >= snapshot['fixture_start_utc']:
            return dict(status='TIPOFF_REACHED_DURING_PROVIDER_REVIEW')
        stats = []
        season = snapshot['season'].replace('/', '-')
        # A current season aggregate is an additional observation, not a PIT
        # training row and not proof of measured pace or a confirmed lineup.
        if str(g.get('league', {}).get('season')) == season:
            for side in ('home', 'away'):
                tid = g['teams'][side].get('id')
                if type(tid) is not int:
                    stats.append(dict(side=side, status='PROVIDER_TEAM_ID_MISSING'))
                    continue
                sr = access.get('API_BASKETBALL', '/statistics',
                                dict(league=lid, season=season, team=tid), deadline=deadline, ttl=300)
                state = sr['status']
                if state == 'DOCUMENT_RECEIVED':
                    doc = sr['document']
                    if not isinstance(doc, dict) or doc.get('errors') or not doc.get('response'):
                        state = 'STATISTICS_EMPTY_OR_PROVIDER_ERROR'
                    else:
                        data = doc['response']
                        bound = (isinstance(data, dict) and data.get('team', {}).get('id') == tid and
                                 data.get('league', {}).get('id') == lid and
                                 str(data.get('league', {}).get('season')) == season)
                        if bound:
                            stats.append(dict(side=side, status='CURRENT_STATISTICS_ARCHIVED_NOT_MODEL_INPUT',
                                              source_pin=self._save(sr), available_at_utc=sr['ingested_at_utc']))
                            continue
                        state = 'STATISTICS_TEAM_LEAGUE_SEASON_NOT_VERIFIED'
                stats.append(dict(side=side, status=state))
        else:
            stats.append(dict(status='STATISTICS_SEASON_NOT_VERIFIED'))
        return dict(status='PREMATCH_FIXTURE_CROSSCHECKED', provider_fixture_id=g['id'],
                    source_pin=self._save(r), observed_at_utc=r['observed_at_utc'],
                    # Fixture data cannot certify injuries, lineup or efficiency.
                    injuries_verified=False, lineups_verified=False, pace_verified=False,
                    forecast_inputs_changed=False, statistics=stats)

    def collect(self, snapshot):
        now = int(self.clock())
        config = self.access.configuration()
        report = dict(format='ISOLATED_PROVIDER_REVIEW_V1', fixture_id=snapshot['fixture_id'],
                      prediction_utc=snapshot['prediction_generated_at_utc'], evaluated_at_utc=now,
                      configuration=config, providers={}, forecast_changed=False,
                      calibration_status='NOT_CALIBRATED', confidence_index=None)
        if now >= snapshot['fixture_start_utc']:
            report['status'] = 'POST_TIPOFF_NO_CURRENT_API_BACKFILL'
            return report
        if not self.lock.acquire(blocking=False):
            report['status'] = 'PROVIDER_REVIEW_ALREADY_RUNNING'
            return report
        try:
            deadline = self.clock()+12
            for provider, method in [('THE_ODDS_API', self._odds), ('API_BASKETBALL', self._basketball)]:
                if config[provider] == 'KEY_NOT_AVAILABLE_IN_TEST_PROCESS':
                    report['providers'][provider] = dict(status=config[provider])
                    continue
                try:
                    report['providers'][provider] = method(snapshot, deadline)
                except Exception:
                    report['providers'][provider] = dict(status='PROVIDER_EVIDENCE_VALIDATION_FAILED')
            report['status'] = 'CURRENT_OBSERVATIONS_NOT_HISTORICAL_FORECAST_INPUTS'
            report['source_pin'] = self._save(report)
            return report
        finally:
            self.lock.release()


def render(report):
    lines = ['🔌 <b>VERİ SAĞLAYICI DENETİMİ</b>',
             'Eksik veri / doğrulanmamış kapsam, NO EDGE anlamına gelmez.',
             'Durum: '+html.escape(report['status'])]
    for provider, config in report['configuration'].items():
        row = report['providers'].get(provider, {})
        state = row.get('status', config)
        lines.append(html.escape(provider+': '+state))
        if row.get('quota'):
            lines.append('Kota (sağlayıcı yanıtı): '+html.escape(str(row['quota'])))
        for stat in row.get('statistics', []):
            lines.append(html.escape('İstatistik '+stat.get('side', '')+': '+stat['status']))
    lines.extend(['API gözlemleri mevcut tahminin girdilerini veya geçmiş kaydını değiştirmez.',
                  'Kadro, sakatlık, tempo ve ödeme kapsamı ayrıca doğrulanmalıdır.',
                  'NOT_CALIBRATED · Güven endeksi: yok'])
    return '\n'.join(lines)


def nba_provider_panel(snapshot, service, bridge):
    from hybrid_engine.market_views import replay_nba, assess, render as render_market
    report = bridge.collect(snapshot)
    parts = [render(report)]
    observations = report['providers'].get('THE_ODDS_API', {}).get('observations', [])
    if observations:
        distribution = replay_nba(snapshot, service)
        for observation in observations:
            parts.append(render_market(assess(observation, distribution, asof_utc=int(time.time()))))
    return '\n\n'.join(parts)
