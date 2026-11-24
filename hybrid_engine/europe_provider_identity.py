"""Current official European identity evidence for native provider names.

No fuzzy match, guessed club membership, changed event clock or forecast edit.
Legal-name exception: season-scoped Beşiktaş J.K./BJK.
Historic sponsor-name exception: exact KK Partizan NIS for official PAR in E2026 only.
"""
from functools import lru_cache
import json
import re
import time

from core.league_identity import normalize_name
from core.team_identity import TeamIdentityRegistry,IdentityRefusal,digest
from providers.season_participants import parse_participants

RULE='EUROPE_OFFICIAL_ALIASES_EXACT_START_V1'


@lru_cache(maxsize=8)
def _registry(encoded,league,year):
    bundle=json.loads(encoded);docs=bundle['documents']
    if digest(docs)!=bundle['sha256']:raise ValueError('EUROPE_ALIAS_CATALOG_PIN')
    snapshot=parse_participants(league,year,docs)
    if snapshot['payload']['participant_count']>64:raise ValueError('EUROPE_ALIAS_CATALOG_BUDGET')
    registry=TeamIdentityRegistry();registry.ingest(snapshot,trusted_sha256=snapshot['sha256'])
    return registry,snapshot


def official_registry(snapshot):
    league=snapshot['league']
    if league not in ('EUROLEAGUE','EUROCUP'):raise ValueError('EUROPE_ALIAS_LEAGUE_REQUIRED')
    season=snapshot['season'];m=re.fullmatch(r'(20[0-9]{2})/(20[0-9]{2})',season)
    if m is None or int(m[2])!=int(m[1])+1:raise ValueError('EUROPE_ALIAS_SEASON_REQUIRED')
    bundle=snapshot['european_team_catalog'];now=int(time.time())
    docs=bundle['documents']
    for r in docs.values():
        if (type(r.get('observed_at_utc')) is not int or type(r.get('ingested_at_utc')) is not int or
            not 0<r['observed_at_utc']<=r['ingested_at_utc']<=now or now-r['observed_at_utc']>300):
            raise ValueError('EUROPE_ALIAS_CATALOG_STALE_OR_FUTURE')
    encoded=json.dumps(bundle,sort_keys=True,allow_nan=False)
    if len(encoded.encode())>512*1024:raise ValueError('EUROPE_ALIAS_CATALOG_SIZE')
    registry,catalog=_registry(encoded,league,int(m[1]))
    for side in ('home','away'):
        team=registry.resolve(league,season,snapshot[side]['official_name'],asof_utc=now)
        if team.provider_ids!=(('EUROLEAGUE_LIVE',str(snapshot[side]['provider_id'])),):
            raise ValueError('EUROPE_ALIAS_TARGET_ID_CONFLICT')
    return registry,catalog,now


def resolve_provider_name(value,snapshot,registry,now):
    try:return registry.resolve(snapshot['league'],snapshot['season'],value,asof_utc=now)
    except IdentityRefusal as exc:
        if str(exc)!='TEAM_ALIAS_NOT_REGISTERED':raise
    # Historical club sponsor naming observed in an actual Odds API event.
    # Public club/ABA evidence:
    # https://partizan.basketball/vesti/aktuelno/3286?lang=en
    # https://www.aba-liga.com/team/22/20/1/0/partizan-nis/
    # This is NOT a fuzzy/sponsor-prefix rule: only one literal historic name,
    # 2026/27 EuroLeague and the current official PAR identity are eligible.
    if normalize_name(value)=='kkpartizannis' and snapshot['league']=='EUROLEAGUE' and snapshot['season']=='2026/2027':
        targets=[side for side in ('home','away') if
                 str(snapshot[side]['provider_id'])=='PAR' and
                 normalize_name(snapshot[side]['official_name'])=='partizanmozzartbetbelgrade']
        if len(targets)!=1:raise IdentityRefusal('HISTORIC_PARTIZAN_TARGET_NOT_VERIFIED')
        team=registry.resolve(snapshot['league'],snapshot['season'],
                              snapshot[targets[0]]['official_name'],asof_utc=now)
        if team.provider_ids!=(('EUROLEAGUE_LIVE','PAR'),):
            raise IdentityRefusal('HISTORIC_PARTIZAN_OFFICIAL_ID_CONFLICT')
        return team
    # A narrowly documented legal-name form, not arbitrary suffix stripping.
    stem=re.sub(r'\s+J\.?\s*K\.?
    if stem==value or normalize_name(stem)!='besiktas':raise IdentityRefusal('TEAM_ALIAS_NOT_REGISTERED')
    team=registry.resolve(snapshot['league'],snapshot['season'],stem,asof_utc=now)
    if (team.provider_ids!=(('EUROLEAGUE_LIVE','BES'),) or
        not any(normalize_name(a[0])=='bjk' for a in team.aliases)):
        raise IdentityRefusal('EUROPE_LEGAL_ALIAS_SOURCE_NOT_CONFIRMED')
    return team


def side_for(value,snapshot):
    registry,catalog,now=official_registry(snapshot)
    team=resolve_provider_name(value,snapshot,registry,now)
    sides=[side for side in ('home','away') if team.provider_ids[0][1]==str(snapshot[side]['provider_id'])]
    return sides[0] if len(sides)==1 else None


def binding_evidence(snapshot):
    _,catalog,_=official_registry(snapshot)
    return dict(rule=RULE,catalog_sha256=snapshot['european_team_catalog']['sha256'],
                participant_snapshot_sha256=catalog['sha256'],league=snapshot['league'],season=snapshot['season'],
                home_team_id=snapshot['home']['provider_id'],away_team_id=snapshot['away']['provider_id'],
                identity_scope='CURRENT_SOURCE_ASSOCIATION_NOT_ORIGINAL_FORECAST_INPUT',
                legal_alias_policy='BESIKTAS_JK_ONLY_WITH_OFFICIAL_BES_AND_BJK',fuzzy_matching=False)
,'',value,flags=re.I)
    if stem==value or normalize_name(stem)!='besiktas':raise IdentityRefusal('TEAM_ALIAS_NOT_REGISTERED')
    team=registry.resolve(snapshot['league'],snapshot['season'],stem,asof_utc=now)
    if (team.provider_ids!=(('EUROLEAGUE_LIVE','BES'),) or
        not any(normalize_name(a[0])=='bjk' for a in team.aliases)):
        raise IdentityRefusal('EUROPE_LEGAL_ALIAS_SOURCE_NOT_CONFIRMED')
    return team


def side_for(value,snapshot):
    registry,catalog,now=official_registry(snapshot)
    team=resolve_provider_name(value,snapshot,registry,now)
    sides=[side for side in ('home','away') if team.provider_ids[0][1]==str(snapshot[side]['provider_id'])]
    return sides[0] if len(sides)==1 else None


def binding_evidence(snapshot):
    _,catalog,_=official_registry(snapshot)
    return dict(rule=RULE,catalog_sha256=snapshot['european_team_catalog']['sha256'],
                participant_snapshot_sha256=catalog['sha256'],league=snapshot['league'],season=snapshot['season'],
                home_team_id=snapshot['home']['provider_id'],away_team_id=snapshot['away']['provider_id'],
                identity_scope='CURRENT_SOURCE_ASSOCIATION_NOT_ORIGINAL_FORECAST_INPUT',
                legal_alias_policy='BESIKTAS_JK_ONLY_WITH_OFFICIAL_BES_AND_BJK',fuzzy_matching=False)
