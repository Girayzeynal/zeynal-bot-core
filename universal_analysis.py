"""Provider-specific identity/fixture preflight; never writes a prediction.

NBA may continue to the existing reference model. Other competitions fail closed
after diagnostics until model inputs and a prospective archive are configured.
"""
import asyncio
from datetime import datetime,timedelta,timezone
from statistics import mean
import time
from zoneinfo import ZoneInfo

from core.league_identity import resolve_league,league_catalog
from core.team_identity import TeamIdentityRegistry,IdentityRefusal,digest
from providers.season_participants import SeasonParticipantProvider,ParticipantSourceError
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog


ISTANBUL=ZoneInfo('Europe/Istanbul')


def require_fresh_source(pin):
    """A current command cannot promote an old or future receipt to live data."""
    observed,ingested=pin['observed_at_utc'],pin['ingested_at_utc']
    now=int(time.time())
    if (type(observed) is not int or type(ingested) is not int or
            not 0<observed<=ingested<=now):
        raise ParticipantSourceError('SOURCE_CLOCK_INVALID')
    if now-observed>300:
        raise ParticipantSourceError('SOURCE_STALE_FOR_CURRENT_ANALYSIS')


class UniversalAnalyzeService:
    def __init__(self,participants=None,fetcher=fetch_document):
        self.participants=participants or SeasonParticipantProvider(fetcher)
        self.fetcher=fetcher;self.registry=TeamIdentityRegistry()

    async def preflight(self,league,day,home,away):
        stage='LEAGUE';spec=None
        report=dict(status='ABSTAIN',stage=stage,provider=None,prediction=None,prospective_records_created=0)
        try:
            spec=resolve_league(league);report.update(league=spec.code,provider=spec.provider)
            if not spec.provider: return dict(report,stage='PROVIDER',participant_count=None,reason='PARTICIPANT_ADAPTER_NOT_CONFIGURED')
            requested=datetime.strptime(day,'%Y-%m-%d').date()
            if requested<datetime.fromtimestamp(time.time(),ISTANBUL).date():
                return dict(report,stage='TIME',reason='HISTORICAL_PIT_SNAPSHOT_REQUIRED')
            year=requested.year if requested.month>=7 else requested.year-1
            stage='SEASON_PARTICIPANTS';report['season_id']=f'{year}/{year+1}'
            snapshot=await asyncio.to_thread(self.participants.load,spec.code,year)
            for pin in snapshot['payload']['source_pins'].values(): require_fresh_source(pin)
            self.registry.ingest(snapshot,trusted_sha256=snapshot['sha256'])
            report.update(participant_count=snapshot['payload']['participant_count'],participant_snapshot_sha256=snapshot['sha256'])
            stage='TEAM_IDENTITY';cutoff=int(time.time())
            h=self.registry.resolve(spec.code,report['season_id'],home,asof_utc=cutoff)
            a=self.registry.resolve(spec.code,report['season_id'],away,asof_utc=cutoff)
            if h.internal_id==a.internal_id: raise IdentityRefusal('SAME_TEAM_BOTH_SIDES')
            report.update(home=dict(internal_id=h.internal_id,official_name=h.official_name,provider_id=h.provider_ids[0][1]),
                          away=dict(internal_id=a.internal_id,official_name=a.official_name,provider_id=a.provider_ids[0][1]))
            stage='FIXTURE';catalogs=[]
            if spec.code=='NBA':
                dates=[requested-timedelta(days=1),requested]
                urls=['https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+d.strftime('%Y%m%d')+'&limit=1000' for d in dates]
            else:
                urls=[f'https://api-live.euroleague.net/v2/competitions/{spec.competition_code}/seasons/{spec.competition_code}{year}/games']
            for url in urls:
                r=await asyncio.to_thread(self.fetcher,spec.provider,url)
                if r.get('status')!='DOCUMENT_RECEIVED': raise ParticipantSourceError(r.get('status','SOURCE_RECEIPT_MISSING'))
                if r.get('source_url')!=url or r.get('provider')!=spec.provider or r.get('http_status')!=200 or digest(r['document'])!=r['document_sha256']:
                    raise ParticipantSourceError('FIXTURE_SOURCE_BINDING_MISMATCH')
                require_fresh_source(r)
                catalogs.append(archive_catalog(r['document'],provider=spec.provider,season_start_year=year,
                    competition_code='U' if spec.code=='EUROCUP' else None,
                    observed_at_utc=r['observed_at_utc'],ingested_at_utc=r['ingested_at_utc']))
            members={t.provider_ids[0][1] for t in self.registry.participants(spec.code,report['season_id'],asof_utc=int(time.time()))}
            games={}
            for catalog in catalogs:
                for g in catalog['payload']['fixtures']:
                    if not {g['home_team_id'],g['away_team_id']}<=members:
                        raise ParticipantSourceError('PARTICIPANT_FIXTURE_ID_CONFLICT')
                    cid=g['canonical_id']
                    if cid in games and games[cid]!=g: raise ParticipantSourceError('CONFLICTING_FIXTURE_SOURCES')
                    games[cid]=g
            targets=[g for g in games.values() if g['home_team_id']==h.provider_ids[0][1] and
                g['away_team_id']==a.provider_ids[0][1] and datetime.fromtimestamp(g['start_ts_utc'],ISTANBUL).date()==requested]
            if len(targets)!=1: return dict(report,stage=stage,reason='FIXTURE_NOT_UNIQUELY_VERIFIED')
            fixture=targets[0];report.update(fixture=fixture,source_catalog_sha256=[c['sha256'] for c in catalogs])
            if fixture['completed'] or fixture['start_ts_utc']<=int(time.time()):
                return dict(report,stage='TIME',reason='FIXTURE_ALREADY_STARTED_OR_COMPLETED')
            # A scheduled status must be explicit; NBA postponed/delayed entries
            # cannot be promoted just because the start clock is in the future.
            if spec.code=='NBA':
                statuses=[e['competitions'][0]['status']['type']['name'] for c in catalogs for e in c['payload']['raw']['events']
                          if e['id'] in fixture['provider_fixture_ids']]
                if not statuses or any(s!='STATUS_SCHEDULED' for s in statuses):
                    return dict(report,stage='TIME',reason='FIXTURE_NOT_SCHEDULED')
                return dict(report,status='VERIFIED_NBA_FIXTURE',stage='FIXTURE',reason=None)
            stage='HISTORY';history={}
            for side,team in [('home',h),('away',a)]:
                pid=team.provider_ids[0][1]
                rows=[g for g in games.values() if g['completed'] and g['periods'] is not None and
                      g['start_ts_utc']<int(time.time()) and pid in (g['home_team_id'],g['away_team_id'])]
                rows=sorted(rows,key=lambda g:(g['start_ts_utc'],g['canonical_id']))[-10:]
                pts=[sum(g['periods']['home' if g['home_team_id']==pid else 'away'][:4]) for g in rows]
                against=[sum(g['periods']['away' if g['home_team_id']==pid else 'home'][:4]) for g in rows]
                history[side]=dict(n_games=len(rows),game_ids=[g['canonical_id'] for g in rows],scope='REGULATION_ONLY',
                    points_for=mean(pts) if pts else None,points_against=mean(against) if against else None,
                    pace=None,injuries=None,rotation=None,player_minutes=None)
            report['history']=history
            if fixture['start_ts_utc']<=int(time.time()): return dict(report,stage='TIME',reason='TIPOFF_DURING_PREFLIGHT')
            if min(r['n_games'] for r in history.values())<6:
                return dict(report,stage=stage,reason='INSUFFICIENT_VERIFIED_HISTORY')
            return dict(report,stage='MODEL_INPUTS',reason='VERIFIED_PACE_AND_PROSPECTIVE_MODEL_ARCHIVE_NOT_CONFIGURED')
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            reason=str(exc) if isinstance(exc,ValueError) else 'SOURCE_SCHEMA_INVALID'
            return dict(report,stage=stage,reason=reason)
        except OSError:
            return dict(report,stage=stage,reason='SOURCE_NETWORK_ERROR')


def render_preflight(report):
    # Structured internal errors stay distinct from genuine missing team data.
    provider=report.get('provider') or 'yapılandırılmamış'
    lines=['Analiz durduruldu: '+report.get('reason','DOĞRULANAMADI'),
           'Aşama: '+report['stage'],'Kaynak: '+provider]
    if 'participant_count' in report: lines.append('Sezon katılımcısı: '+str(report['participant_count']))
    if 'history' in report:
        lines.append('Doğrulanmış geçmiş: Ev '+str(report['history']['home']['n_games'])+' / Dep '+str(report['history']['away']['n_games']))
    lines.append('Tahmin üretilmedi; mevcut tahmin kayıtları değiştirilmedi.')
    return '\n'.join(lines)
