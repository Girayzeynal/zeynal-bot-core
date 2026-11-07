"""Bind legacy archive facts to replayed v2 source evidence before modelling.

Legacy/source-clock wrappers do not confer source rights or PIT availability.
Eligibility is always decided by original v2 clocks and the pinned policy.
"""
import time

from prediction_inputs import digest
from faz40_archive import require,replay_game,seal_game,MODES
from faz41_adapters import ESPN_ABBREVIATIONS
from faz41_evidence import REGISTRY,REGISTRY_PIN
from faz42_history import _validated,forecast

FACTS=('quarters_home','quarters_away','overtime_home','overtime_away','regulation_home','regulation_away','final_home','final_away')


def materialize_research_archive(observations,*,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    """New in-memory wrappers, never backdated historical ingestion claims."""
    rows=_validated(observations,int(time.time()),registry,registry_pin);records=[]
    for o,p in rows:
        f=p['fixture'];require(p['data_type']=='OFFICIAL_STAT' and p['provider'] in ('ESPN','EUROLEAGUE_LIVE'),'MODEL_SCORE_ARCHIVE_ADAPTER_REQUIRED')
        teams=list(ESPN_ABBREVIATIONS) if f['league']=='NBA' else [p['raw'][s]['club']['code'] for s in ('local','road')]
        records.append(seal_game(p['raw'],league=f['league'],season_end_year=f['season_end_year'],source_observed_utc=p['observed_at_utc'],
            ingested_utc=int(time.time()),team_ids=teams,usage='SYNTHETIC_TEST' if p['usage']=='SYNTHETIC_TEST' else 'RETROSPECTIVE_RESEARCH'))
    return records


def bind_history(records,observations,*,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    require(type(records) is list and type(observations) is list,'SOURCE_BOUND_HISTORY_LISTS_REQUIRED')
    legacy=[replay_game(r) for r in records];rows=_validated(observations,int(time.time()),registry,registry_pin)
    require(all(p['data_type']=='OFFICIAL_STAT' for o,p in rows),'SOURCE_BOUND_SCORE_EVIDENCE_REQUIRED')
    categories={p['usage']=='SYNTHETIC_TEST' for p in legacy}|{p['usage']=='SYNTHETIC_TEST' for o,p in rows}
    require(len(categories)<=1,'MIXED_SYNTHETIC_REAL_EVIDENCE')
    expected={p['facts']['canonical_id'] for p in legacy};actual={p['fixture']['canonical_id'] for o,p in rows}
    require(expected==actual,'SOURCE_BOUND_HISTORY_UNIVERSE_MISMATCH')
    aliases={(p['provider'],p['provider_fixture_id']):p for o,p in rows}
    for p in legacy:
        f=p['facts'];source=aliases.get((f['provider'],f['fixture_id']))
        require(source is not None and source['fixture']['canonical_id']==f['canonical_id'] and source['source_url']==f['source_url'],'SOURCE_BOUND_HISTORY_ALIAS_MISMATCH')
        require(all(source['claims'][k]==f[k] for k in FACTS),'SOURCE_BOUND_HISTORY_FACT_CONFLICT')
    return dict(schema_version=1,bound_games=len(expected),archive_sha256=sorted({r['sha256'] for r in records}),
        evidence_sha256=sorted({o['sha256'] for o in observations}),registry_sha256=registry_pin,
        legacy_clocks_not_used_for_eligibility=True,availability_policy='FAZ42_STRICT_PUBLISHED_OBSERVED_INGESTED_MATERIALIZED',
        usage='SYNTHETIC_TEST' if categories=={True} else 'REAL_RESEARCH_NOT_PROSPECTIVE_PERFORMANCE')


def bound_projection(records,observations,target,cutoff_utc,*,registry=REGISTRY,registry_pin=REGISTRY_PIN,**options):
    binding=bind_history(records,observations,registry=registry,registry_pin=registry_pin)
    require(set(options)<={'mode','minimum_team_games','simulations','seed','maximum_age_seconds','score_correlation'},'SOURCE_BOUND_RESEARCH_OPTIONS')
    requested=options.pop('mode','INGESTION_TIME');require(requested in MODES,'INVALID_ARCHIVE_CUTOFF_OR_MODE')
    result=forecast(observations,target,cutoff_utc,registry=registry,registry_pin=registry_pin,**options)
    binding['requested_legacy_mode']=requested
    return result,binding
