"""Season participant catalogs; never infer membership from sampled fixtures."""
import re
import time
from copy import deepcopy
from urllib.parse import urlsplit

from core.league_identity import resolve_league,normalize_name
from core.team_identity import digest,internal_team_id
from season_archive_collect import fetch_document


class ParticipantSourceError(ValueError):
    pass


def _need(test,reason):
    if not test: raise ParticipantSourceError(reason)


def _variants(row,at):
    result={}
    for key in ('displayName','shortDisplayName','abbreviation','name','abbreviatedName','editorialName',
                'tvCode','sponsor','clubPermanentName','clubPermanentAlias'):
        name=row.get(key)
        if type(name) is str and name.strip():
            result[(normalize_name(name),key)]=dict(name=name.strip(),kind='SOURCE_'+key,language='und',
                valid_from_utc=at,valid_until_utc=None,validity_basis='OBSERVED_FROM_COLLECTION')
            city=row.get('city')
            if type(city) is str and city.strip():
                if name.casefold().endswith(' '+city.casefold()):
                    short=name[:-(len(city)+1)].strip()
                    if short: result[(normalize_name(short),'city_removed')]=dict(name=short,kind='SOURCE_CITY_SUFFIX_REMOVED',
                        language='und',valid_from_utc=at,valid_until_utc=None,validity_basis='OBSERVED_FROM_COLLECTION')
    city=row.get('city')
    if type(city) is str and city.strip():
        for key in ('editorialName','clubPermanentAlias'):
            if type(row.get(key)) is str and row[key].strip():
                value=row[key]+' '+city
                result[(normalize_name(value),'city_added')]=dict(name=value,kind='SOURCE_NAME_WITH_SOURCE_CITY',language='und',
                    valid_from_utc=at,valid_until_utc=None,validity_basis='OBSERVED_FROM_COLLECTION')
    return list(result.values())


def parse_participants(league,year,documents):
    """documents are URL-bound transport receipts with original source clocks."""
    spec=resolve_league(league)
    _need(spec.provider is not None,'PARTICIPANT_ADAPTER_NOT_CONFIGURED')
    _need(type(year) is int and 2000<=year<=2100,'EXPLICIT_SEASON_REQUIRED')
    expected=participant_urls(spec.code,year)
    _need(set(documents)==set(expected),'PARTICIPANT_DOCUMENT_SET_MISMATCH')
    pins={};observed=[];ingested=[]
    for name,url in expected.items():
        r=documents[name]
        _need(r.get('status')=='DOCUMENT_RECEIVED',r.get('status','SOURCE_RECEIPT_MISSING'))
        _need(r.get('source_url')==url and r.get('provider')==spec.provider and r.get('http_status')==200,
              'PARTICIPANT_SOURCE_BINDING_MISMATCH')
        _need(digest(r['document'])==r['document_sha256'],'PARTICIPANT_SOURCE_DIGEST_MISMATCH')
        o,i=r['observed_at_utc'],r['ingested_at_utc']
        _need(type(o) is int and type(i) is int and 0<o<=i<=int(time.time()),'PARTICIPANT_SOURCE_CLOCK_INVALID')
        observed.append(o);ingested.append(i);pins[name]=dict(url=url,document_sha256=r['document_sha256'],observed_at_utc=o,ingested_at_utc=i)
    at=max(ingested)
    if spec.code=='NBA':
        membership=documents['membership']['document'];directory=documents['names']['document']
        _need(type(membership['count']) is int and 0<membership['count']<=100 and
              type(membership['pageCount']) is int and type(membership['pageIndex']) is int and membership['pageCount']==1 and membership['pageIndex']==1 and
              membership['count']==len(membership['items']) and membership['count']>0,'PARTICIPANT_PAGE_INCOMPLETE')
        ids=[]
        for item in membership['items']:
            u=urlsplit(item['$ref']);match=re.fullmatch(r'/v2/sports/basketball/leagues/nba/seasons/'+str(year+1)+r'/teams/([0-9]+)',u.path)
            _need(u.hostname=='sports.core.api.espn.com' and u.scheme in ('http','https') and match is not None,'NBA_SEASON_MEMBERSHIP_REF_INVALID')
            ids.append(match[1])
        node=directory['sports'][0]['leagues'][0]
        season=node.get('season');season_year=season.get('year') if type(season) is dict else season
        _need(node['slug']=='nba' and node['year']==year+1 and season_year==year+1,'NBA_NAME_DIRECTORY_SEASON_MISMATCH')
        names={}
        for r in node['teams']:
            team=r['team'];pid=team['id']
            _need(pid not in names,'DUPLICATE_PARTICIPANT_ID');names[pid]=team
        _need(len(set(ids))==len(ids) and set(ids)<=set(names),'NBA_PARTICIPANT_NAMES_INCOMPLETE')
        rows=[(pid,names[pid],names[pid]['displayName']) for pid in ids]
    else:
        season=documents['season']['document'];payload=documents['clubs']['document'];code=spec.competition_code
        _need(season['code']==code+str(year) and season['competitionCode']==code and type(season['year']) is int and season['year']==year,
              'EURO_COMPETITION_SEASON_MISMATCH')
        _need(type(payload['total']) is int and payload['total']==len(payload['data']) and payload['total']>0,'PARTICIPANT_PAGE_INCOMPLETE')
        rows=[]
        for club in payload['data']:
            _need(type(club['code']) is str and re.fullmatch(r'[A-Z0-9]{1,8}',club['code']) and club['isVirtual'] is False,'CLUB_IDENTITY_INVALID')
            rows.append((club['code'],club,club['name']))
    _need(len({pid for pid,row,name in rows})==len(rows),'DUPLICATE_PARTICIPANT_ID')
    participants=[]
    for pid,row,name in rows:
        normalize_name(name)
        participants.append(dict(internal_id=internal_team_id(spec.identity_namespace,pid),provider=spec.provider,
            provider_id=pid,official_name=name,aliases=_variants(row,at)))
    p=dict(format='SEASON_PARTICIPANTS_V1',league_id=spec.code,year=year,season_id=f'{year}/{year+1}',
        observed_at_utc=max(observed),ingested_at_utc=at,participant_count=len(participants),
        participants=sorted(participants,key=lambda t:t['internal_id']),source_pins=pins,
        membership_basis='SEASON_PARTICIPANT_ENDPOINT_NOT_GAME_SAMPLES',source_attestation='LOCAL_HASH_NOT_INDEPENDENT_ATTESTATION')
    return dict(payload=p,sha256=digest(p))


def participant_urls(league,year):
    spec=resolve_league(league)
    if spec.code=='NBA':
        return dict(membership=f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{year+1}/teams?limit=100',
            names=f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams?limit=100')
    if spec.competition_code in ('E','U'):
        base=f'https://api-live.euroleague.net/v2/competitions/{spec.competition_code}/seasons/{spec.competition_code}{year}'
        return dict(season=base,clubs=base+'/clubs')
    raise ParticipantSourceError('PARTICIPANT_ADAPTER_NOT_CONFIGURED')


def _historical_nba_directory(year,documents,fetcher):
    """Season-specific details, never current names relabelled as old data."""
    membership=documents['membership'];raw=membership['document'];items=raw['items']
    _need(type(raw['count']) is int and 0<raw['count']<=100 and raw['pageCount']==1 and raw['count']==len(items),
          'PARTICIPANT_PAGE_INCOMPLETE')
    pins={'membership':dict(url=membership['source_url'],document_sha256=membership['document_sha256'],
        observed_at_utc=membership['observed_at_utc'],ingested_at_utc=membership['ingested_at_utc'])}
    teams=[];ids=set()
    for item in items:
        ref=urlsplit(item['$ref']);m=re.fullmatch(r'/v2/sports/basketball/leagues/nba/seasons/'+str(year+1)+r'/teams/([0-9]+)',ref.path)
        _need(ref.hostname=='sports.core.api.espn.com' and m is not None,'NBA_SEASON_MEMBERSHIP_REF_INVALID')
        pid=m[1];_need(pid not in ids,'DUPLICATE_PARTICIPANT_ID');ids.add(pid)
        url=f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{year+1}/teams/{pid}'
        r=fetcher('ESPN',url)
        _need(r.get('status')=='DOCUMENT_RECEIVED',r.get('status','SOURCE_RECEIPT_MISSING'))
        _need(r.get('source_url')==url and r.get('provider')=='ESPN' and r.get('http_status')==200 and
              digest(r['document'])==r['document_sha256'],'NBA_SEASON_TEAM_DETAIL_BINDING_MISMATCH')
        t=r['document'];_need(t['id']==pid and t.get('isAllStar') is False,'NBA_SEASON_TEAM_DETAIL_ID_INVALID')
        detail_ref=urlsplit(t['$ref'])
        _need(detail_ref.hostname=='sports.core.api.espn.com' and detail_ref.path==urlsplit(url).path,
              'NBA_SEASON_TEAM_DETAIL_SEASON_MISMATCH')
        o,i=r['observed_at_utc'],r['ingested_at_utc']
        _need(type(o) is int and type(i) is int and 0<o<=i<=int(time.time()),'PARTICIPANT_SOURCE_CLOCK_INVALID')
        pins['team_'+pid]=dict(url=url,document_sha256=r['document_sha256'],observed_at_utc=o,ingested_at_utc=i)
        teams.append((pid,t,i))
    spec=resolve_league('NBA');at=max(p['ingested_at_utc'] for p in pins.values())
    p=dict(format='SEASON_PARTICIPANTS_V1',league_id='NBA',year=year,season_id=f'{year}/{year+1}',
        observed_at_utc=max(p['observed_at_utc'] for p in pins.values()),ingested_at_utc=at,participant_count=len(teams),
        participants=sorted([dict(internal_id=internal_team_id(spec.identity_namespace,pid),provider='ESPN',provider_id=pid,
            official_name=t['displayName'],aliases=_variants(t,i)) for pid,t,i in teams],key=lambda t:t['internal_id']),
        source_pins=pins,membership_basis='SEASON_PARTICIPANT_ENDPOINT_NOT_GAME_SAMPLES',
        source_attestation='LOCAL_HASH_NOT_INDEPENDENT_ATTESTATION')
    return dict(payload=p,sha256=digest(p))


class SeasonParticipantProvider:
    def __init__(self,fetcher=fetch_document):
        self.fetcher=fetcher;self._cache={}

    def load(self,league,year):
        spec=resolve_league(league);key=(spec.code,year);now=int(time.time())
        if key in self._cache and 0<=now-self._cache[key][0]<=300: return deepcopy(self._cache[key][1])
        urls=participant_urls(spec.code,year);documents={}
        for name,url in urls.items():
            r=self.fetcher(spec.provider,url)
            if r.get('status')!='DOCUMENT_RECEIVED': raise ParticipantSourceError(r.get('status','SOURCE_RECEIPT_MISSING'))
            documents[name]=r
        try:
            try: result=parse_participants(spec.code,year,documents)
            except ParticipantSourceError as exc:
                if spec.code!='NBA' or str(exc)!='NBA_NAME_DIRECTORY_SEASON_MISMATCH': raise
                result=_historical_nba_directory(year,documents,self.fetcher)
        except (KeyError,TypeError,AttributeError) as exc: raise ParticipantSourceError('PARTICIPANT_SOURCE_SCHEMA_INVALID') from exc
        self._cache[key]=(int(time.time()),deepcopy(result))
        return result
