"""FAZ41 v2 evidence metadata. Local hashes are not source or licence attestation.

Legacy v1 observations cannot enter this contract. All model consumption requires
an explicitly pinned permission policy; default official policies remain UNKNOWN.
"""
from copy import deepcopy
import time
from urllib.parse import urlsplit

from prediction_inputs import digest
from faz40_archive import require, LEAGUES

TYPES = {'OFFICIAL_STAT', 'OFFICIAL_LINEUP', 'INJURY_REPORT', 'NEWS_CLAIM',
         'ANALYST_OPINION', 'PLAYER_MINUTES', 'ROSTER', 'ROTATION'}
REGISTRY = {
    'ESPN': dict(owner='ESPN', host='site.api.espn.com', paths=['/apis/site/v2/sports/basketball/nba/'],
                 types=['OFFICIAL_STAT','PLAYER_MINUTES','ROSTER'], level='SECONDARY',
                 usage='UNKNOWN', permission_ref=None, reviewed_at_utc=None, expires_at_utc=None),
    'NBA': dict(owner='NBA', host='cdn.nba.com', paths=['/static/json/'],
                types=['OFFICIAL_STAT','PLAYER_MINUTES','ROSTER','OFFICIAL_LINEUP'], level='OFFICIAL',
                usage='UNKNOWN', permission_ref=None, reviewed_at_utc=None, expires_at_utc=None),
    'EUROLEAGUE_LIVE': dict(owner='EUROLEAGUE_BASKETBALL', host='api-live.euroleague.net', paths=['/v2/competitions/'],
                types=['OFFICIAL_STAT','PLAYER_MINUTES','ROSTER','OFFICIAL_LINEUP'], level='OFFICIAL',
                usage='UNKNOWN', permission_ref=None, reviewed_at_utc=None, expires_at_utc=None),
}
REGISTRY_PIN = digest(REGISTRY)


def fixture_identity(*, league, season_end_year, start_utc, home_team_id, away_team_id):
    require(league in LEAGUES and type(season_end_year) is int and 2001<=season_end_year<=2100,
            'INVALID_FIXTURE_PARTITION')
    require(type(start_utc) is int and start_utc>0 and
            all(type(t) is str and t and t==t.strip() for t in (home_team_id,away_team_id)) and
            home_team_id!=away_team_id, 'INVALID_FIXTURE_IDENTITY')
    f=dict(league=league,season_end_year=season_end_year,start_utc=start_utc,
           home_team_id=home_team_id,away_team_id=away_team_id)
    return dict(f,canonical_id=digest(f))


def _fixture(f):
    require(type(f) is dict and set(f)==set('league season_end_year start_utc home_team_id away_team_id canonical_id'.split()),
            'FIXTURE_SCHEMA')
    require(f==fixture_identity(**{k:v for k,v in f.items() if k!='canonical_id'}), 'FIXTURE_DIGEST_MISMATCH')


def _policy(provider, source_url, data_type, registry, registry_pin):
    require(type(registry) is dict and digest(registry)==registry_pin, 'TRUSTED_REGISTRY_PIN_MISMATCH')
    require(provider in registry, 'UNREGISTERED_PROVIDER')
    p=registry[provider]
    require(set(p)==set('owner host paths types level usage permission_ref reviewed_at_utc expires_at_utc'.split()),
            'POLICY_SCHEMA')
    require(type(p['owner']) is str and p['owner'].strip() and p['level'] in ('OFFICIAL','SECONDARY','COMMENTARY') and
            p['usage'] in ('UNKNOWN','RESTRICTED','PERMITTED'), 'POLICY_CLASSIFICATION')
    url=urlsplit(source_url)
    require(url.scheme=='https' and url.hostname==p['host'] and not url.username and not url.password and
            url.port in (None,443) and not url.fragment and type(p['paths']) is list and
            any(type(prefix) is str and prefix.startswith('/') and prefix.endswith('/') and
                url.path.startswith(prefix) for prefix in p['paths']), 'SOURCE_ORIGIN_NOT_ALLOWED')
    require(data_type in TYPES and data_type in p['types'], 'SOURCE_TYPE_NOT_ALLOWED')
    require(data_type!='ANALYST_OPINION' or p['level']=='COMMENTARY', 'OPINION_CANNOT_BE_OFFICIAL')
    require(data_type!='OFFICIAL_LINEUP' or p['level']=='OFFICIAL', 'OFFICIAL_LINEUP_REQUIRED')
    if p['usage']=='PERMITTED':
        ref=urlsplit(p['permission_ref'] or '')
        require(ref.scheme=='https' and ref.hostname and not ref.username and not ref.password and
                all(type(p[k]) is int and p[k]>0 for k in ('reviewed_at_utc','expires_at_utc')) and
                p['reviewed_at_utc']<p['expires_at_utc'], 'PERMISSION_PROOF_REQUIRED')
    return p


def seal_observation(*, fixture, provider, provider_fixture_id, source_url, data_type,
                     raw, claims, observed_at_utc, ingested_at_utc, published_at_utc=None,
                     scope='NOT_APPLICABLE', usage='RETROSPECTIVE_RESEARCH',
                     registry=REGISTRY, registry_pin=REGISTRY_PIN):
    _fixture(fixture)
    require(type(provider_fixture_id) is str and provider_fixture_id and provider_fixture_id==provider_fixture_id.strip(),
            'PROVIDER_FIXTURE_REQUIRED')
    policy=_policy(provider,source_url,data_type,registry,registry_pin)
    now=int(time.time())
    require(all(type(t) is int for t in (observed_at_utc,ingested_at_utc)) and
            0<observed_at_utc<=ingested_at_utc<=now, 'OBSERVATION_CHRONOLOGY')
    require(published_at_utc is None or type(published_at_utc) is int and
            0<published_at_utc<=observed_at_utc, 'PUBLICATION_CHRONOLOGY')
    require(data_type not in ('NEWS_CLAIM','ANALYST_OPINION','INJURY_REPORT') or published_at_utc is not None,
            'PUBLICATION_TIME_REQUIRED')
    require(scope in ('NOT_APPLICABLE','REGULATION_ONLY','FINAL_WITH_OT') and
            usage in ('SYNTHETIC_TEST','RETROSPECTIVE_RESEARCH','PROSPECTIVE_EVIDENCE'), 'EVIDENCE_CLASSIFICATION')
    require(usage!='PROSPECTIVE_EVIDENCE' or now<fixture['start_utc'], 'PROSPECTIVE_MUST_BE_PRESTART')
    require(type(raw) is dict and type(claims) is dict and claims and
            all(type(k) is str and k.strip() for k in claims), 'RAW_AND_CLAIMS_REQUIRED')
    payload=dict(schema_version=2,fixture=deepcopy(fixture),provider=provider,provider_fixture_id=provider_fixture_id,
        source_url=source_url,data_type=data_type,evidence_level=policy['level'],owner=policy['owner'],
        usage_status=policy['usage'],registry_sha256=registry_pin,published_at_utc=published_at_utc,
        observed_at_utc=observed_at_utc,ingested_at_utc=ingested_at_utc,materialized_at_utc=now,
        scope=scope,usage=usage,raw=deepcopy(raw),raw_sha256=digest(raw),claims=deepcopy(claims),
        provenance='LOCAL_HASH_NOT_INDEPENDENT_SOURCE_ATTESTATION')
    return dict(payload=payload,sha256=digest(payload))


def validate_observation(sealed, *, fixture, cutoff_utc, maximum_age_seconds,
                         registry=REGISTRY, registry_pin=REGISTRY_PIN, require_permitted=True):
    try:
        _fixture(fixture)
        require(type(cutoff_utc) is int and 0<cutoff_utc<=int(time.time()) and
                type(maximum_age_seconds) is int and maximum_age_seconds>0, 'INVALID_EVIDENCE_CUTOFF')
        require(type(require_permitted) is bool, 'INVALID_PERMISSION_MODE')
        require(type(sealed) is dict and set(sealed)=={'payload','sha256'}, 'EVIDENCE_ENVELOPE_SCHEMA')
        p=sealed['payload']
        fields=set('schema_version fixture provider provider_fixture_id source_url data_type evidence_level owner usage_status '
                   'registry_sha256 published_at_utc observed_at_utc ingested_at_utc materialized_at_utc scope usage raw '
                   'raw_sha256 claims provenance'.split())
        require(type(p) is dict and set(p)==fields and type(p['schema_version']) is int and p['schema_version']==2,
                'EVIDENCE_V2_REQUIRED')
        require(digest(p)==sealed['sha256'] and digest(p['raw'])==p['raw_sha256'], 'EVIDENCE_DIGEST_MISMATCH')
        require(p['fixture']==fixture and p['registry_sha256']==registry_pin, 'FIXTURE_OR_POLICY_BINDING_MISMATCH')
        require(type(p['materialized_at_utc']) is int and
                0<p['ingested_at_utc']<=p['materialized_at_utc']<cutoff_utc, 'EVIDENCE_NOT_AVAILABLE_AT_CUTOFF')
        require(p['usage']!='PROSPECTIVE_EVIDENCE' or p['materialized_at_utc']<fixture['start_utc'],
                'PROSPECTIVE_MUST_BE_PRESTART')
        fields={k:p[k] for k in ('fixture','provider','provider_fixture_id','source_url','data_type',
            'raw','claims','observed_at_utc','ingested_at_utc','published_at_utc','scope','usage')}
        # Replaying an original prematch record after tipoff is legitimate; the
        # stored creation clock, not today's replay clock, defines its usage.
        if fields['usage']=='PROSPECTIVE_EVIDENCE':fields['usage']='RETROSPECTIVE_RESEARCH'
        rebuilt=seal_observation(**fields,registry=registry,registry_pin=registry_pin)['payload']
        rebuilt['usage']=p['usage'];rebuilt['materialized_at_utc']=p['materialized_at_utc']
        require(rebuilt==p, 'EVIDENCE_SEMANTIC_MISMATCH')
        policy=registry[p['provider']]
        require(cutoff_utc-p['observed_at_utc']<=maximum_age_seconds, 'STALE_OBSERVATION')
        if p['data_type'] in ('NEWS_CLAIM','ANALYST_OPINION','INJURY_REPORT'):
            require(cutoff_utc-p['published_at_utc']<=maximum_age_seconds, 'STALE_PUBLICATION')
        if require_permitted:
            require(policy['usage']=='PERMITTED', 'SOURCE_USAGE_NOT_ESTABLISHED')
            require(policy['reviewed_at_utc']<cutoff_utc<=policy['expires_at_utc'], 'PERMISSION_NOT_VALID_AT_CUTOFF')
        return deepcopy(p)
    except (KeyError,TypeError,AttributeError,OverflowError) as exc:
        raise ValueError('MALFORMED_SOURCE_OBSERVATION') from exc


def compare_observations(observations, **validation):
    """Ownership-aware agreement is not a verified truth or legal attestation."""
    require(type(observations) is list and observations, 'OBSERVATIONS_REQUIRED')
    rows=[validate_observation(o,**validation) for o in observations]
    require(len({r['usage'] for r in rows})==1, 'MIXED_SYNTHETIC_REAL_EVIDENCE')
    groups={}
    for row in rows:
        for name,value in row['claims'].items():
            groups.setdefault((name,row['data_type'],row['scope']),[]).append((row,digest(value)))
    return [dict(claim_key=name,data_type=kind,scope=scope,owners=sorted({r['owner'] for r,v in values}),
                 evidence_levels=sorted({r['evidence_level'] for r,v in values}),
                 usage_statuses=sorted({r['usage_status'] for r,v in values}),
                 status='CONFLICT' if len({v for r,v in values})>1 else
                        'INDEPENDENT_OWNER_AGREEMENT' if len({r['owner'] for r,v in values})>1 else 'SINGLE_OWNER',
                 independently_attested=False)
            for (name,kind,scope),values in sorted(groups.items())]
