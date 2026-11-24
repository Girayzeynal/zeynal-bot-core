"""Current official European identity evidence for native provider names.

No fuzzy match, guessed club membership, changed event clock or forecast edit.
Legal-name exception: Beşiktaş J.K./BJK; exact historic Partizan NIS label only for E2026 PAR.
"""
from functools import lru_cache
import json
import re
import time

from core.league_identity import normalize_name
from core.team_identity import TeamIdentityRegistry,IdentityRefusal,digest
from providers.season_participants import parse_participants

RULE='EUROPE_OFFICIAL_ALIASES_EXACT_START_V1'
# Exact names observed in the 24 Nov Telegram provider event list.
OBSERVED_LABELS={
    'kkcrvenazvezda':('RED','crvenazvezdameridianbetbelgrade'),
    'virtussegafredobologna':('VIR','virtusbologna'),
    # User's real E2026_133 roster and event discovery, exact club IDs.
    'fcbarcelonabasquet':('BAR','fcbarcelona'),
    'fenerbahcesk':('ULK','fenerbahcetarfinistanbul'),
}


# Exact provider labels shown in the 24 November Telegram discovery
# lists, with anchors from official_all_82_club_urls_2026_27.json.
# No guessed provider IDs: the current official participant catalog must
# resolve the anchor uniquely, and the fixture must match that club ID.
CATALOG_OBSERVED_LABELS={
    'fcbayernmunchen':'FC Bayern Munich',
    'asvellyonvilleurbanne':'LDLC ASVEL Villeurbanne',
    'pallacanestroolimpiamilano':'EA7 Emporio Armani Milan',
}

def observed_catalog_anchor(value,snapshot,registry,now):
    key=normalize_name(value)
    if (snapshot['league']!='EUROLEAGUE' or snapshot['season']!='2026/2027'
            or key not in CATALOG_OBSERVED_LABELS):
        raise IdentityRefusal('TEAM_ALIAS_NOT_REGISTERED')
    return registry.resolve(snapshot['league'],snapshot['season'],
                            CATALOG_OBSERVED_LABELS[key],asof_utc=now)


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
    key=normalize_name(value)
    if key in CATALOG_OBSERVED_LABELS and snapshot['league']=='EUROLEAGUE' and snapshot['season']=='2026/2027':
        team=observed_catalog_anchor(value,snapshot,registry,now)
        if (len(team.provider_ids)!=1 or team.provider_ids[0][0]!='EUROLEAGUE_LIVE'
                or sum(str(snapshot[side]['provider_id'])==team.provider_ids[0][1]
                       for side in ('home','away'))!=1):
            raise IdentityRefusal('OBSERVED_CATALOG_ALIAS_TARGET_NOT_VERIFIED')
        return team
    if key in OBSERVED_LABELS and snapshot['league']=='EUROLEAGUE' and snapshot['season']=='2026/2027':
        pid,anchor=OBSERVED_LABELS[key]
        targets=[side for side in ('home','away') if
            str(snapshot[side]['provider_id'])==pid and
            normalize_name(snapshot[side]['official_name'])==anchor]
        if len(targets)!=1:raise IdentityRefusal('OBSERVED_PROVIDER_ALIAS_TARGET_NOT_VERIFIED')
        team=registry.resolve(snapshot['league'],snapshot['season'],
                              snapshot[targets[0]]['official_name'],asof_utc=now)
        if team.provider_ids!=(('EUROLEAGUE_LIVE',pid),):
            raise IdentityRefusal('OBSERVED_PROVIDER_ALIAS_OFFICIAL_ID_CONFLICT')
        return team
    # A documented historical sponsor name, limited to official E2026 PAR.
    # https://partizan.basketball/vesti/aktuelno/3286?lang=en
    # https://www.aba-liga.com/team/22/20/1/0/partizan-nis/
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
    stem=re.sub(r'\s+J\.?\s*K\.?\Z','',value,flags=re.I)
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


def audit_slate(receipt,snapshot):
    """Read-only coverage of the actual native event listing, not all-season proof."""
    from hybrid_engine.provider_bridge import SPORTS
    registry,catalog,now=official_registry(snapshot)
    sport=SPORTS[snapshot['league']]
    if (receipt.get('provider')!='THE_ODDS_API' or receipt.get('status')!='DOCUMENT_RECEIVED'
            or receipt.get('http_status')!=200
            or receipt.get('source_url')!='https://api.the-odds-api.com/v4/sports/'+sport+'/events'
            or digest(receipt.get('document'))!=receipt.get('document_sha256')
            or type(receipt.get('observed_at_utc')) is not int
            or type(receipt.get('ingested_at_utc')) is not int
            or not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now
            or now-receipt['observed_at_utc']>120
            or not isinstance(receipt['document'],list) or len(receipt['document'])>1000):
        raise ValueError('SLATE_NATIVE_DISCOVERY_REQUIRED')
    league,season=snapshot['league'],snapshot['season']
    participants=registry.participants(league,season,asof_utc=now)
    labels=set();invalid=0
    for e in receipt['document']:
        if not isinstance(e,dict) or e.get('sport_key')!=sport:
            invalid+=1;continue
        for field in ('home_team','away_team'):
            label=e.get(field)
            if isinstance(label,str) and 0<len(label)<=120 and label.strip():
                labels.add(label)
            else:invalid+=1
    if len(labels)>128:raise ValueError('SLATE_LABEL_BUDGET')
    accepted=[];unresolved=[]
    for label in sorted(labels):
        try:
            try:team=registry.resolve(league,season,label,asof_utc=now)
            except IdentityRefusal as exc:
                if str(exc)!='TEAM_ALIAS_NOT_REGISTERED':raise
                key=normalize_name(label)
                if league=='EUROLEAGUE' and season=='2026/2027' and key in OBSERVED_LABELS:
                    pid,anchor=OBSERVED_LABELS[key]
                    matches=[t for t in participants if t.provider_ids==(('EUROLEAGUE_LIVE',pid),)
                             and normalize_name(t.official_name)==anchor]
                    if len(matches)!=1:raise IdentityRefusal('OBSERVED_PROVIDER_ALIAS_TARGET_NOT_VERIFIED')
                    team=registry.resolve(league,season,matches[0].official_name,asof_utc=now)
                elif league=='EUROLEAGUE' and season=='2026/2027' and key=='kkpartizannis':
                    team=registry.resolve(league,season,'Partizan Mozzart Bet Belgrade',asof_utc=now)
                    if team.provider_ids!=(('EUROLEAGUE_LIVE','PAR'),):
                        raise IdentityRefusal('HISTORIC_PARTIZAN_OFFICIAL_ID_CONFLICT')
                elif key=='besiktasjk':
                    team=registry.resolve(league,season,'Besiktas',asof_utc=now)
                    if (team.provider_ids!=(('EUROLEAGUE_LIVE','BES'),)
                        or not any(normalize_name(a[0])=='bjk' for a in team.aliases)):
                        raise IdentityRefusal('EUROPE_LEGAL_ALIAS_SOURCE_NOT_CONFIRMED')
                else:team=observed_catalog_anchor(label,snapshot,registry,now)
            accepted.append(dict(label=label,official_name=team.official_name,
                                 official_id=team.provider_ids[0][1]))
        except (ValueError,KeyError,TypeError) as exc:
            reason=str(exc)
            unresolved.append(dict(label=label,reason=reason if reason in (
                'TEAM_ALIAS_NOT_REGISTERED','AMBIGUOUS_TEAM_ALIAS','OBSERVED_PROVIDER_ALIAS_TARGET_NOT_VERIFIED',
                'HISTORIC_PARTIZAN_OFFICIAL_ID_CONFLICT','EUROPE_LEGAL_ALIAS_SOURCE_NOT_CONFIRMED'
            ) else 'CATALOG_LABEL_REFUSED'))
    ids=sorted({r['official_id'] for r in accepted})
    missing=sorted(t.provider_ids[0][1] for t in participants if t.provider_ids[0][1] not in ids)
    return dict(status='OBSERVED_SLATE_IDENTITY_AUDIT_ONLY',league=league,season=season,
        official_participant_count=len(participants),observed_label_count=len(labels),
        resolved_label_count=len(accepted),observed_official_ids=ids,not_observed_official_ids=missing,
        invalid_entries=invalid,unresolved=unresolved,resolved=accepted,
        catalog_sha256=catalog['sha256'],discovery_receipt_sha256=digest(receipt),
        full_season_provider_coverage_verified=False,fixture_binding_verified_by_audit=False,
        model_input=False,additional_network_requests=0)
