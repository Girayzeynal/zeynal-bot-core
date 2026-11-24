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

SPORTS = {'NBA': 'basketball_nba', 'EUROLEAGUE': 'basketball_euroleague', 'EUROCUP': 'basketball_eurocup'}
# Requests beyond the three featured markets require explicit local opt-in.
CORE_MARKETS = ('h2h', 'spreads', 'totals')
EXTRA_MARKETS = ('alternate_spreads', 'alternate_totals', 'team_totals',
                 'totals_h1', 'totals_h2', 'totals_q1', 'totals_q2', 'totals_q3', 'totals_q4')
ALIASES = {'losangelesclippers': 'laclippers'}


class EvidenceCapacityError(ValueError):
    pass


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


def team_side(value,snapshot):
    if snapshot.get('league') in ('EUROLEAGUE','EUROCUP') and snapshot.get('european_team_catalog') is not None:
        from hybrid_engine.europe_provider_identity import side_for
        return side_for(value,snapshot)
    sides=[side for side in ('home','away') if name(value)==name(snapshot[side]['official_name'])]
    return sides[0] if len(sides)==1 else None


def matches(event, snapshot, *, basketball=False):
    try:
        if basketball:
            h, a = event['teams']['home']['name'], event['teams']['away']['name']
            start = utc(event['date'])
        else:
            h, a = event['home_team'], event['away_team']
            start = utc(event['commence_time'])
        return (team_side(h,snapshot)=='home' and
                team_side(a,snapshot)=='away' and
                start == snapshot['fixture_start_utc'])
    except (KeyError, ValueError, TypeError):
        return False


def fixture_for(snapshot):
    from hybrid_engine.decision_audit import trace_for
    trace = trace_for(snapshot)
    return fixture_identity({k: trace[k] for k in
                             ('league', 'season', 'fixture_id', 'home_team_id', 'away_team_id', 'tipoff_utc')})


def odds_observations(receipt, snapshot, *, discovery=None):
    """Match exact teams+tipoff; keep actual books, alternative lines and periods."""
    if digest(receipt['document']) != receipt['document_sha256']:
        raise ValueError('PROVIDER_DOCUMENT_PIN')
    event = receipt['document']
    binding=None
    if discovery is not None:
        from hybrid_engine.provider_identity import verify_detail
        binding=verify_detail(discovery,receipt,snapshot)
    elif not matches(event, snapshot) or event.get('sport_key') != SPORTS.get(snapshot['league']):
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
                            target = team_side(outcome['description'],snapshot)
                            if target == 'home':
                                kind = 'HOME'
                            elif target == 'away':
                                kind = 'AWAY'
                            else:
                                raise ValueError('TEAM_TOTAL_IDENTITY')
                        line = outcome['point']
                    else:
                        target = team_side(outcome['name'],snapshot)
                        if target == 'home':
                            side = 'over'
                        elif target == 'away':
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
                    if binding is not None:payload['source']['event_clock_binding']=binding
                    result.append(dict(payload=payload, sha256=digest(payload)))
                    if len(result) >= 12:
                        return result, rejected
            except (KeyError, TypeError, ValueError):
                rejected += 1
    return result, rejected


class ProviderBridge:
    def __init__(self, access, directory, *, extended=False, clock=time.time, diagnostic_only=False, rule_book=None):
        self.access = access
        self.root = local_path(directory)
        self.extended = extended
        self.diagnostic_only = diagnostic_only
        self.clock = clock
        self.lock = threading.Lock()
        self.coverage_blocks = {}
        from hybrid_engine.settlement_rules import RuleBook
        self.rule_book=rule_book if rule_book is not None else RuleBook.configured()
        self.assessments=None

    def _receipt_paths(self, pin):
        """Keep legacy root pins readable; new evidence is SHA-prefix sharded.

        Never relocate or rewrite old native receipts; no destructive rotation.
        Exact canonical filenames and local_path reject traversal and symlinks.
        """
        filename='provider-'+pin+'.json'
        return (local_path(self.root/filename),
                local_path(self.root/'segments'/pin[:2]/filename))

    def storage_status(self):
        legacy=list(self.root.glob('provider-*.json')) if self.root.exists() else []
        segmented=list(self.root.glob('segments/??/provider-*.json')) if self.root.exists() else []
        files=legacy+segmented
        size=sum(local_path(p).stat().st_size for p in files)
        # Legacy root is immutable; its full 256-file limit no longer blocks
        # new evidence. An individual segment still fails closed if full.
        segment_sizes={}
        for p in segmented:
            name=p.parent.name
            n,b=segment_sizes.get(name,(0,0))
            segment_sizes[name]=(n+1,b+local_path(p).stat().st_size)
        saturated=sum(n>=256 or b>=32*1024*1024 for n,b in segment_sizes.values())
        return dict(files=len(files),bytes=size,legacy_files=len(legacy),
                    segmented_files=len(segmented),segments=len(segment_sizes),
                    legacy_at_capacity=len(legacy)>=256,
                    segment_maximum_files=256,segment_maximum_bytes=32*1024*1024,
                    status=('LOCAL_EVIDENCE_STORAGE_FULL' if saturated==256 else 'AVAILABLE'))

    def _save(self, payload):
        pin=digest(payload)
        legacy,target=self._receipt_paths(pin)
        if legacy.exists() or target.exists():
            self.read_receipt(pin)  # authenticate either historic or sharded receipt
            return pin
        wrapper=dict(payload=payload,sha256=pin)
        body_bytes=len((json.dumps(wrapper,sort_keys=True,allow_nan=False)+'\n').encode())
        if body_bytes>3*1024*1024:
            raise EvidenceCapacityError('PROVIDER_RECEIPT_SIZE_LIMIT')
        if target.parent.exists():
            files=list(target.parent.glob('provider-*.json'))
            if (len(files)>=256 or
                sum(local_path(p).stat().st_size for p in files)+body_bytes>32*1024*1024):
                raise EvidenceCapacityError('PROVIDER_EVIDENCE_FILE_OR_STORAGE_BUDGET')
        target.parent.mkdir(parents=True,exist_ok=True)
        publish_json(target,wrapper)
        return pin

    def read_receipt(self, pin):
        """Authenticate immutable legacy or SHA-prefix segment native evidence."""
        if not isinstance(pin,str) or re.fullmatch('[0-9a-f]{64}',pin) is None:
            raise ValueError('PROVIDER_RECEIPT_PIN_REQUIRED')
        legacy,target=self._receipt_paths(pin)
        path=legacy if legacy.exists() or legacy.is_symlink() else target
        if path.stat().st_size>3*1024*1024:raise ValueError('PROVIDER_RECEIPT_SIZE_LIMIT')
        body=json.loads(path.read_text())
        if not isinstance(body,dict) or body.get('sha256')!=pin or 'payload' not in body or digest(body['payload'])!=pin:
            raise ValueError('PROVIDER_RECEIPT_PIN_CONFLICT')
        return body['payload']

    def _odds(self, snapshot, deadline):
        access = self.access
        sport = SPORTS.get(snapshot['league'])
        if sport is None:
            return dict(status='LEAGUE_NOT_MAPPED', observations=[])
        sports = access.get('THE_ODDS_API', '/v4/sports/', deadline=deadline, ttl=3600)
        if sports['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=sports['status'], observations=[])
        if not isinstance(sports['document'], list):
            return dict(status='INVALID_PROVIDER_SCHEMA', observations=[], catalog_source_pin=self._save(sports))
        if not any(
                x.get('key') == sport and x.get('active') is True for x in sports['document'] if isinstance(x, dict)):
            candidates=[dict(key=x['key'],title=str(x.get('title',''))[:120]) for x in sports.get('document',[])
                        if isinstance(x,dict) and isinstance(x.get('key'),str) and
                        re.fullmatch(r'basketball_[a-z0-9_]{1,60}',x['key']) and x.get('active') is True] if isinstance(sports.get('document'),list) else []
            return dict(status='LEAGUE_NOT_AVAILABLE_FROM_PROVIDER', observations=[],expected_sport_key=sport,
                        active_basketball_sports=candidates[:12],catalog_source_pin=self._save(sports))
        events = access.get('THE_ODDS_API', f'/v4/sports/{sport}/events', deadline=deadline)
        if events['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=events['status'], observations=[])
        if not isinstance(events['document'], list):
            return dict(status='INVALID_PROVIDER_SCHEMA', observations=[])
        from hybrid_engine.provider_identity import bind
        try:
            event,binding=bind(events,snapshot,asof_utc=int(self.clock()))
        except (ValueError,KeyError,TypeError) as exc:
            from hybrid_engine.provider_diagnostics import fixture_diagnostic
            code=str(exc)
            codes={'NATIVE_EVENT_DISCOVERY_PROOF_REQUIRED','FRESH_EVENT_DISCOVERY_CLOCK_REQUIRED',
                'AMBIGUOUS_NATIVE_EVENT_DISCOVERY','EXACT_OR_UNIQUE_NBA_PLUS600_MATCH_REQUIRED',
                'EXPLICIT_NBA_PLUS600_ONLY','REVERSED_NATIVE_EVENT_CONFLICT',
                'NATIVE_EVENT_ID_OR_COMPETITION_CONFLICT','EARLIEST_NATIVE_START_ALREADY_REACHED',
                'OFFICIAL_TEAM_ALIAS_OR_EXACT_START_REQUIRED'}
            return dict(status='EXACT_FIXTURE_MATCH_REQUIRED', observations=[],
                        matching_events=sum(matches(e,snapshot) for e in events['document']),
                        error_codes=[code if code in codes else 'NATIVE_EVENT_BINDING_REFUSED'],
                        operation='EVENT_DISCOVERY',fixture_diagnostic=fixture_diagnostic(events['document'],snapshot),
                        source_pin=self._save(events))
        event_id = event.get('id')
        if not isinstance(event_id, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}', event_id):
            return dict(status='PROVIDER_EVENT_ID_INVALID', observations=[])
        discovery_pin=self._save(events)
        if self.diagnostic_only:
            return dict(status='EXACT_FIXTURE_MATCH_CONFIRMED' if binding['payload']['delta_seconds']==0 else 'NBA_PROVIDER_OFFSET_BOUND',
                        observations=[],provider_fixture_id=event_id,event_clock_binding=binding,
                        odds_requests_made=0,source_pin=discovery_pin)
        markets = (*CORE_MARKETS, *EXTRA_MARKETS) if self.extended else CORE_MARKETS
        r = access.get('THE_ODDS_API', f'/v4/sports/{sport}/events/{event_id}/odds',
                       dict(regions='us', markets=','.join(markets), oddsFormat='decimal'), deadline=deadline)
        if r['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=r['status'], observations=[])
        try:
            observations, rejected = odds_observations(r, snapshot,discovery=events)
        except (ValueError,KeyError,TypeError) as exc:
            code=str(exc)
            codes={'NATIVE_ODDS_DETAIL_PROOF_REQUIRED','DISCOVERY_AND_ODDS_DETAIL_IDENTITY_CONFLICT',
                'ODDS_DETAIL_AFTER_EARLIEST_START_OR_INVALID_CLOCK','FRESH_EVENT_DISCOVERY_CLOCK_REQUIRED',
                'EARLIEST_NATIVE_START_ALREADY_REACHED'}
            return dict(status='ODDS_DETAIL_REJECTED',operation='ODDS_DETAIL_PARSING',observations=[],
                        error_codes=[code if code in codes else 'NATIVE_ODDS_DETAIL_VALIDATION_FAILED'],
                        event_clock_binding=binding,source_pin=self._save(r),discovery_source_pin=discovery_pin)
        return dict(status='OBSERVED_RULES_AND_CALIBRATION_PENDING' if observations else 'NO_FRESH_SUPPORTED_PRICES',
                    observations=observations, rejected_markets=rejected, requested_markets=list(markets),
                    quota=r.get('quota', {}), source_pin=self._save(r),
                    provider_fixture_id=event_id, event_clock_binding=binding,
                    discovery_source_pin=discovery_pin,forecast_inputs_changed=False)

    def _basketball(self, snapshot, deadline):
        access = self.access
        coverage_key=(snapshot['league'],snapshot['season'])
        old=self.coverage_blocks.get(coverage_key)
        if old is not None and int(self.clock())<old['coverage_block_until_utc']:
            return dict(old,coverage_cache='UNCHANGED_SEASON_RESTRICTION_REUSED')
        def blocked(receipt,operation,selection=None):
            from hybrid_engine.provider_diagnostics import failure
            row=dict(failure(receipt,operation),source_pin=self._save(receipt))
            if selection is not None:row.update(season_selection=selection,requested_season=selection['season_value'])
            codes=row['error_codes']
            if 'PLAN_OR_SUBSCRIPTION_RESTRICTION_REPORTED' in codes and 'SEASON_ERROR_REPORTED' in codes:
                row['coverage_block_until_utc']=int(self.clock())+3600
                self.coverage_blocks[coverage_key]=dict(row)
            return row
        league = {'NBA': 'NBA', 'EUROLEAGUE': 'Euroleague', 'EUROCUP': 'Eurocup'}.get(snapshot['league'])
        if league is None:
            return dict(status='LEAGUE_NOT_MAPPED')
        r = access.get('API_BASKETBALL', '/leagues', dict(name=league), deadline=deadline, ttl=3600)
        if r['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=r['status'])
        if r['document'].get('errors'):
            return blocked(r,'LEAGUE_DISCOVERY')
        leagues = [x for x in r['document'].get('response', []) if name(x.get('name', '')) == name(league)]
        if len(leagues) != 1 or type(leagues[0].get('id')) is not int:
            return dict(status='EXACT_LEAGUE_MAPPING_REQUIRED')
        lid = leagues[0]['id']
        day = datetime.fromtimestamp(snapshot['fixture_start_utc'], timezone.utc).strftime('%Y-%m-%d')
        season = snapshot['season'].replace('/', '-')
        selection=None;season_info={}
        if snapshot['league'] in ('EUROLEAGUE','EUROCUP'):
            from hybrid_engine.provider_seasons import select_season
            selection=select_season(leagues[0],snapshot)
            selection['catalog_source_pin']=self._save(r)
            if selection['status']!='VERIFIED_PROVIDER_SEASON':
                return dict(status=selection['status'],operation='SEASON_DISCOVERY',season_selection=selection)
            season=selection['season_value']
            season_info=dict(season_selection=selection,requested_season=season)
        r = access.get('API_BASKETBALL', '/games',
                       dict(league=lid, season=season, date=day, timezone='UTC'), deadline=deadline)
        if r['status'] != 'DOCUMENT_RECEIVED':
            return dict(status=r['status'],**season_info)
        if r['document'].get('errors'):
            return blocked(r,'FIXTURE_QUERY',selection=selection)
        games = [x for x in r['document'].get('response', []) if matches(x, snapshot, basketball=True)]
        if len(games) != 1:
            from hybrid_engine.provider_diagnostics import fixture_diagnostic
            return dict(status='EXACT_FIXTURE_MATCH_REQUIRED', matching_events=len(games),operation='FIXTURE_QUERY',
                        fixture_diagnostic=fixture_diagnostic(r['document'].get('response',[]),snapshot,basketball=True),
                        source_pin=self._save(r),**season_info)
        g = games[0]
        if (g.get('status', {}).get('short') != 'NS' or g.get('league', {}).get('id') != lid or
                type(g.get('id')) is not int):
            return dict(status='PROVIDER_FIXTURE_NOT_VERIFIED_PREMATCH',**season_info)
        if int(self.clock()) >= snapshot['fixture_start_utc']:
            return dict(status='TIPOFF_REACHED_DURING_PROVIDER_REVIEW',**season_info)
        if self.diagnostic_only:
            return dict(status='PREMATCH_FIXTURE_CROSSCHECKED',provider_fixture_id=g['id'],
                        statistics_requests_made=0,source_pin=self._save(r),**season_info)
        stats = []
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
                    forecast_inputs_changed=False, statistics=stats,**season_info)

    def collect(self, snapshot):
        now = int(self.clock())
        config = self.access.configuration()
        report = dict(format='ISOLATED_PROVIDER_REVIEW_V1', fixture_id=snapshot['fixture_id'],
                      prediction_utc=snapshot['prediction_generated_at_utc'], evaluated_at_utc=now,
                      configuration=config, providers={}, forecast_changed=False,
                      calibration_status='NOT_CALIBRATED', confidence_index=None,diagnostic_only=self.diagnostic_only)
        if snapshot.get('current_team_identity'):report['current_team_identity']=snapshot['current_team_identity']
        if now >= snapshot['fixture_start_utc']:
            report['status'] = 'POST_TIPOFF_NO_CURRENT_API_BACKFILL'
            return report
        if not self.lock.acquire(blocking=False):
            report['status'] = 'PROVIDER_REVIEW_ALREADY_RUNNING'
            return report
        try:
            usage=self.storage_status()
            if usage['status']=='LOCAL_EVIDENCE_STORAGE_FULL':
                report.update(status='LOCAL_EVIDENCE_STORAGE_FULL',source_pin=None,storage=usage,
                              persistence='NOT_PERSISTED_LOCAL_CAPACITY_LIMIT')
                report['providers']={p:dict(status='LOCAL_EVIDENCE_STORAGE_FULL' if
                    state!='KEY_NOT_AVAILABLE_IN_TEST_PROCESS' else state,observations=[]) for p,state in config.items()}
                return report
            deadline = self.clock()+12
            for provider, method in [('THE_ODDS_API', self._odds), ('API_BASKETBALL', self._basketball)]:
                if config[provider] == 'KEY_NOT_AVAILABLE_IN_TEST_PROCESS':
                    report['providers'][provider] = dict(status=config[provider])
                    continue
                try:
                    report['providers'][provider] = method(snapshot, deadline)
                except EvidenceCapacityError:
                    report['providers'][provider] = dict(status='LOCAL_EVIDENCE_STORAGE_FULL',observations=[])
                except Exception:
                    report['providers'][provider] = dict(status='PROVIDER_EVIDENCE_VALIDATION_FAILED')
            report['status'] = 'CURRENT_OBSERVATIONS_NOT_HISTORICAL_FORECAST_INPUTS'
            try:
                report['source_pin'] = self._save(report)
            except EvidenceCapacityError:
                report.update(status='LOCAL_EVIDENCE_STORAGE_FULL',source_pin=None,
                              persistence='NOT_PERSISTED_LOCAL_CAPACITY_LIMIT')
            return report
        finally:
            self.lock.release()


def render(report):
    from hybrid_engine.market_turkish import message
    lines = ['🔌 <b>VERİ SAĞLAYICI DENETİMİ</b>',
             'Eksik veri / doğrulanmamış kapsam, NO EDGE anlamına gelmez.',
             'Durum: '+html.escape(message(report['status']))]
    if report['status']=='LOCAL_EVIDENCE_STORAGE_FULL':
        lines.append('Yerel kanıt deposunun sınırına ulaşıldı; bu bir API erişim veya abonelik hatası değildir. Eski belgeler silinmedi.')
    if report.get('current_team_identity'):
        identity=report['current_team_identity']
        lines.append('Takım kimliği: '+html.escape(message(identity['status'])))
        if identity.get('catalog_sha256'):
            lines.append('Güncel resmî takım kataloğu SHA: '+identity['catalog_sha256'])
            lines.append('Bu kanıt güncel kaynak eşleştirmesidir; ilk tahmin girdisi değildir.')
    for provider, config in report['configuration'].items():
        row = report['providers'].get(provider, {})
        state = row.get('status', config)
        title={'THE_ODDS_API':'The Odds API','API_BASKETBALL':'API-Basketball'}.get(provider,provider)
        lines.append(html.escape(title+': '+message(state)))
        if row.get('operation'):lines.append('Aşama: '+html.escape(message(row['operation'])))
        if row.get('error_codes'):lines.append('Kaynak hata sınıfı: '+html.escape('; '.join(message(c) for c in row['error_codes'])))
        if ('PLAN_OR_SUBSCRIPTION_RESTRICTION_REPORTED' in row.get('error_codes',[]) and
                'SEASON_ERROR_REPORTED' in row.get('error_codes',[])):
            if row.get('season_selection',{}).get('status')=='VERIFIED_PROVIDER_SEASON':
                lines.append('İstek sezonu sağlayıcı kataloğundan doğrulandı; buna rağmen plan/sezon hatası bildirildi.')
            else:
                lines.append('Plan veya sezon hatası bildirildi; kesin neden ayrıca doğrulanmalı. Tahmin verisi uydurulmadı.')
        if row.get('expected_sport_key'):
            lines.append('Beklenen lig kodu: '+html.escape(row['expected_sport_key']))
            active=row.get('active_basketball_sports',[])
            if active:lines.append('Aktif basketbol kodları: '+html.escape(', '.join(x['key'] for x in active)))
        selected=row.get('season_selection')
        if selected:
            lines.append('Sezon denetimi: '+html.escape(message(selected['status'])))
            if selected.get('season_value'):lines.append('Sağlayıcı sezon değeri: '+html.escape(selected['season_value']))
            if selected.get('available_seasons'):lines.append('Katalogdaki sezonlar: '+html.escape(', '.join(selected['available_seasons'])))
        if row.get('coverage_cache'):lines.append('Aynı sezon erişim reddi korunuyor; tekrar sorgulanmadı.')
        if row.get('event_clock_binding'):
            from hybrid_engine.provider_identity import clock_text
            lines.append('Saat bağı: '+html.escape(message(row['event_clock_binding']['payload']['mode'])))
            lines.append(html.escape(clock_text(row['event_clock_binding'])))
        detail=row.get('fixture_diagnostic')
        if detail:
            lines.append('Eşleşme nedeni: '+html.escape(message(detail['reason'])))
            lines.append('Arşiv UTC başlangıcı: '+html.escape(detail['target']['start_utc']))
            for candidate in detail['candidates'][:3]:
                lines.append(html.escape(candidate['home']+' – '+candidate['away']+' | '+candidate['start_utc']+
                                         ' | Saat farkı (sn): '+str(candidate['delta_seconds'])))
        if row.get('quota'):
            lines.append('Kota (sağlayıcı yanıtı): '+html.escape(str(row['quota'])))
        for stat in row.get('statistics', []):
            side={'home':'ev sahibi','away':'deplasman'}.get(stat.get('side'),'takım')
            lines.append(html.escape('İstatistik '+side+': '+message(stat['status'])))
    lines.extend(['API gözlemleri mevcut tahminin girdilerini veya geçmiş kaydını değiştirmez.',
                  'Kadro, sakatlık, tempo ve ödeme kapsamı ayrıca doğrulanmalıdır.',
                  'NOT_CALIBRATED · Güven endeksi: yok'])
    return '\n'.join(lines)


def nba_provider_panel(snapshot, service, bridge, *, structured=False):
    from hybrid_engine.market_views import replay_nba
    from hybrid_engine.current_market_review import admit_odds,evaluate,CurrentReviewJournal
    from hybrid_engine.current_market_render import render_batch
    from hybrid_engine.market_turkish import message
    report = bridge.collect(snapshot)
    parts = [render(report)]
    direction_cards=[]
    # Exact source/model context used to evaluate returned direction cards.
    # Expose only an authenticated current-assessment snapshot, never the old first-model pin.
    market_candidate_snapshot=None
    observations = report['providers'].get('THE_ODDS_API', {}).get('observations', [])
    if observations:
        assessment=None
        # A broken/missing V3 context must not take the existing, independently
        # verified V1 price review down with it. The fallback uses only V1 paths
        # and its own original model/clock, never a relabelled V3 direction.
        if getattr(bridge,'assessments',None):
            try:
                assessment=bridge.assessments.available_market_context(snapshot)
            except (OSError,ValueError,KeyError,TypeError,TimeoutError):
                parts.append('V3 fiyat bağlamı doğrulanamadı: V3_MARKET_CONTEXT_UNAVAILABLE. '
                             'İlk modelin bağımsız fiyat incelemesi korunuyor.')
        if getattr(bridge,'assessments',None) and assessment is None:
            parts.append('Güncel değerlendirme yolları hazır/güncel değil; piyasa ilk tahminin dağılımıyla ayrı referans olarak gösteriliyor.')
        evaluation_snapshot,distribution=assessment if assessment else (snapshot,replay_nba(snapshot,service))
        if assessment is not None:
            market_candidate_snapshot=evaluation_snapshot
        row=report['providers']['THE_ODDS_API']
        try:
            discovery=bridge.read_receipt(row['discovery_source_pin'])
            detail=bridge.read_receipt(row['source_pin'])
            quotes=[admit_odds(o,snapshot,discovery,detail) for o in observations]
        except (OSError,ValueError,KeyError,TypeError):
            parts.append(message('NATIVE_PRICE_ADMISSION_FAILED'))
        else:
            # The old prediction time is immutable; later quotes use a new
            # actual decision clock and never enter original forecast metrics.
            decision_utc=int(time.time())
            from hybrid_engine.settlement_rules import evaluate_bound
            reviews=[evaluate_bound(bridge,o,distribution,evaluation_snapshot,asof_utc=decision_utc,native_quotes=q)
                     for o,q in zip(observations,quotes)]
            try:
                batch=CurrentReviewJournal(bridge.root.parent/'current-market-reviews').record(
                    evaluation_snapshot,distribution,reviews,decision_utc=decision_utc)
            except (OSError,ValueError,KeyError,TypeError):
                parts.append(message('CURRENT_REVIEW_ARCHIVE_FAILED'))
            else:
                parts.append(render_batch(batch))
                from hybrid_engine.market_direction_ui import cards
                for review in reviews:
                    direction_cards.extend(cards(review,distribution.forecast,
                        tipoff_utc=snapshot['fixture_start_utc'],fixture_id=snapshot['fixture_id'],batch=batch))
    full='\n\n'.join(parts)
    source_state=(report.get('providers',{}).get('THE_ODDS_API') or {}).get('status') or report.get('status','UNKNOWN')
    return (dict(html=full,cards=direction_cards,market_candidate_snapshot=market_candidate_snapshot,
                 market_source_status=source_state,market_native_observations=len(observations))
            if structured else full)
