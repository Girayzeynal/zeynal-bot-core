"""FAZ42 track A: inventory and strict four-clock research, reusing FAZ40/41.

No downloads, training, coefficient updates, live claims or database writes.
"""
from collections import Counter
from statistics import fmean
import math
import time

from prediction_inputs import digest
from faz40_archive import require,seal_game,select_games,LEAGUES
from faz40_research import project,metrics,MODEL
from faz41_evidence import REGISTRY,REGISTRY_PIN,_fixture
from faz41_adapters import replay,ESPN_ABBREVIATIONS

LEAGUE_INVENTORY=('NBA','EUROLEAGUE','EUROCUP','TBL','CBA','JAPAN','LEGA')
PERIODS=('1Q','2Q','3Q','4Q','1H','2H','FULL')


def _validated(observations,asof_utc,registry,registry_pin):
    require(type(observations) is list and type(asof_utc) is int and 0<asof_utc<=int(time.time()),'INVALID_HISTORY_AUDIT')
    require(digest(registry)==registry_pin,'TRUSTED_REGISTRY_PIN_MISMATCH')
    rows=[];usages=set();identity={};slots={};games={}
    for o in observations:
        p=o['payload'];f=p['fixture']
        row=replay(o,fixture=f,cutoff_utc=asof_utc,maximum_age_seconds=100*366*86400,
                   registry=registry,registry_pin=registry_pin,require_permitted=False)
        usages.add('SYNTHETIC_TEST' if row['usage']=='SYNTHETIC_TEST' else 'REAL');require(len(usages)==1,'MIXED_SYNTHETIC_REAL_HISTORY')
        alias=(row['provider'],row['provider_fixture_id']);cid=f['canonical_id']
        require(alias not in identity or identity[alias]==cid,'PROVIDER_FIXTURE_IDENTITY_CONFLICT');identity[alias]=cid
        for side in ('home','away'):
            slot=(f['league'],f[side+'_team_id'],f['start_utc'])
            require(slot not in slots or slots[slot]==cid,'SAME_TEAM_START_CONFLICT');slots[slot]=cid
        if row['data_type']=='OFFICIAL_STAT':
            require(cid not in games or games[cid]==row['claims'],'CONFLICTING_FINAL_OBSERVATIONS');games[cid]=row['claims']
        rows.append((o,row))
    return rows


def inventory(observations,*,asof_utc,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    rows=_validated(observations,asof_utc,registry,registry_pin);partitions={}
    for league in LEAGUE_INVENTORY:
        seasons=sorted({p['fixture']['season_end_year'] for o,p in rows if p['fixture']['league']==league})
        for season in seasons or [None]:
            selected=[(o,p) for o,p in rows if p['fixture']['league']==league and p['fixture']['season_end_year']==season]
            stats=[p for o,p in selected if p['data_type']=='OFFICIAL_STAT'];players=[p for o,p in selected if p['data_type']=='PLAYER_MINUTES']
            ids={p['fixture']['canonical_id'] for o,p in selected};statids={p['fixture']['canonical_id'] for p in stats}
            minuteids={p['fixture']['canonical_id'] for p in players};player_rows={}
            for p in players:
                cid=p['fixture']['canonical_id']
                for team,entries in p['claims']['teams'].items():
                    for r in entries:player_rows[(cid,team,r['player_id'])]=r
            usable=set()
            for o,p in selected:
                try:replay(o,fixture=p['fixture'],cutoff_utc=asof_utc,maximum_age_seconds=100*366*86400,registry=registry,registry_pin=registry_pin)
                except ValueError:continue
                if p['data_type']=='OFFICIAL_STAT':usable.add(p['fixture']['canonical_id'])
            partitions[f'{league}:{season}']=dict(league=league,season_end_year=season,adapter_supported=league in LEAGUES,
                status='SOURCE_INVENTORY_ONLY' if selected else 'ABSTAIN_NO_ARCHIVE' if league in LEAGUES else 'ABSTAIN_NO_VERIFIED_ADAPTER',
                observations=len(selected),distinct_observation_digests=len({o['sha256'] for o,p in selected}),
                unique_games=len(ids),period_games=len(statids),player_minutes_games=len(minuteids),
                missing_period_games=len(ids-statids),missing_player_minutes_games=len(ids-minuteids),
                player_rows=len(player_rows),reported_minutes_rows=sum(p.get('minutes') is not None for p in player_rows.values()),
                verified_play_by_play_games=0,verified_lineup_stint_games=0,verified_prematch_roster_games=0,
                usable_permission_games=len(usable),source_owners=sorted({p['owner'] for o,p in selected}),
                permissions=dict(Counter(p['usage_status'] for o,p in selected)),
                fixture_aliases=sorted({p['provider']+':'+p['provider_fixture_id'] for o,p in selected}),
                sources=[dict(observation_sha256=o['sha256'],provider=p['provider'],fixture_id=p['provider_fixture_id'],
                    source_url=p['source_url'],published_at_utc=p['published_at_utc'],observed_at_utc=p['observed_at_utc'],
                    ingested_at_utc=p['ingested_at_utc'],materialized_at_utc=p['materialized_at_utc']) for o,p in selected])
    return dict(status='INVENTORY_COMPLETE_NOT_MODEL_ACCURACY',asof_utc=asof_utc,partitions=partitions,
                registry_sha256=registry_pin,prospective_records_created=0,source_attestation='NOT_INDEPENDENTLY_VERIFIED')


def forecast(observations,target,cutoff_utc,*,registry=REGISTRY,registry_pin=REGISTRY_PIN,
             minimum_team_games=5,simulations=10000,seed=20261106,maximum_age_seconds=90*86400,score_correlation=0.0):
    _fixture(target)
    require(type(cutoff_utc) is int and 0<cutoff_utc<=int(time.time()) and cutoff_utc<target['start_utc'],'PREMATCH_CUTOFF_REQUIRED')
    require(type(simulations) is int and simulations>=10000 and type(minimum_team_games) is int and minimum_team_games>=2 and
            type(seed) is int and type(maximum_age_seconds) is int and maximum_age_seconds>0,
            'INVALID_FORECAST_CONFIGURATION')
    require(type(score_correlation) in (int,float) and math.isfinite(score_correlation) and -1<score_correlation<1,'INVALID_SCORE_CORRELATION')
    rows=_validated(observations,int(time.time()),registry,registry_pin);records=[];refs=[];excluded=Counter()
    for o,p in rows:
        f=p['fixture']
        if p['data_type']!='OFFICIAL_STAT' or f['league']!=target['league'] or f['season_end_year']!=target['season_end_year']:continue
        if f['start_utc']>=cutoff_utc:excluded['SELF_OR_FUTURE_MATCH']+=1;continue
        if p['materialized_at_utc']>=cutoff_utc:excluded['UNAVAILABLE_AT_CUTOFF']+=1;continue
        try:replay(o,fixture=f,cutoff_utc=cutoff_utc,maximum_age_seconds=maximum_age_seconds,registry=registry,registry_pin=registry_pin)
        except ValueError as ex:excluded[str(ex)]+=1;continue
        if p['provider']=='NBA':excluded['MODEL_ARCHIVE_ADAPTER_UNAVAILABLE']+=1;continue
        # Strict v2 prefilter checks all four original clocks. The new FAZ40
        # wrapper is created today, so source-clock selection is research only.
        r=seal_game(p['raw'],league=f['league'],season_end_year=f['season_end_year'],source_observed_utc=p['observed_at_utc'],
            ingested_utc=int(time.time()),team_ids=list(ESPN_ABBREVIATIONS) if f['league']=='NBA' else
            [p['raw'][s]['club']['code'] for s in ('local','road')],usage='SYNTHETIC_TEST' if p['usage']=='SYNTHETIC_TEST' else 'RETROSPECTIVE_RESEARCH')
        records.append(r);refs.append(o['sha256'])
    out=project(records,target,cutoff_utc,mode='ARCHIVED_SOURCE_CLOCK',minimum_team_games=minimum_team_games,simulations=simulations,seed=seed,score_correlation=score_correlation)
    # An empty eligible set must not turn a synthetic source universe into a
    # real research cohort merely because project([]) has no usage to inherit.
    if rows and all(p['usage']=='SYNTHETIC_TEST' for o,p in rows):out['usage']='SYNTHETIC_TEST'
    out.update(availability_policy='FAZ42_STRICT_PUBLISHED_OBSERVED_INGESTED_MATERIALIZED',
               evidence_sha256=sorted(set(refs)),excluded=dict(excluded),prospective_records_created=0)
    if out['prediction'] is None:out['status']='ABSTAIN';out['abstain_reason']='INSUFFICIENT_PERMITTED_PIT_HISTORY'
    return out


def period_errors(prediction,actual):
    result={}
    for i,name in enumerate(PERIODS):
        def value(side):
            q=prediction[side]['quarters'];a=actual['quarters_'+side]
            if i<4:return q[i],a[i]
            indexes=(0,1) if name=='1H' else (2,3) if name=='2H' else (0,1,2,3)
            return sum(q[j] for j in indexes),sum(a[j] for j in indexes)
        ph,ah=value('home');pa,aa=value('away')
        result[name]=dict(home=ph-ah,away=pa-aa,total=ph+pa-ah-aa,margin=ph-pa-ah+aa)
    return result


def evaluate(observations,*,league,season_end_year,train_end_utc,validation_end_utc,
             asof_utc,registry=REGISTRY,registry_pin=REGISTRY_PIN,minimum_team_games=5,
             minimum_evaluation_games=30,simulations=10000):
    require(type(season_end_year) is int and 2001<=season_end_year<=2100 and type(asof_utc) is int, 'INVALID_RESEARCH_PARTITION')
    require(type(train_end_utc) is int and type(validation_end_utc) is int and
            0<train_end_utc<validation_end_utc<asof_utc,'CHRONOLOGICAL_SPLIT_REQUIRED')
    require(type(minimum_evaluation_games) is int and minimum_evaluation_games>=2 and
            type(simulations) is int and simulations>=10000 and type(minimum_team_games) is int and minimum_team_games>=2,
            'INVALID_EVALUATION_CONFIGURATION')
    if league not in LEAGUES:return dict(status='ABSTAIN_NO_VERIFIED_ADAPTER',folds=[],metrics=None)
    rows=_validated(observations,asof_utc,registry,registry_pin);labels={}
    for o,p in rows:
        f=p['fixture']
        if p['data_type']=='OFFICIAL_STAT' and f['league']==league and f['season_end_year']==season_end_year:
            cid=f['canonical_id']
            if cid not in labels or (p['materialized_at_utc'],o['sha256'])<(labels[cid][1]['materialized_at_utc'],labels[cid][0]['sha256']):labels[cid]=(o,p)
    folds=[];cohorts={'VALIDATION':[],'TEST':[]};errors={'VALIDATION':[],'TEST':[]}
    for o,p in sorted(labels.values(),key=lambda item:(item[1]['fixture']['start_utc'],item[1]['fixture']['canonical_id'])):
        f=p['fixture'];start=f['start_utc'];role='TRAIN_HISTORY' if start<train_end_utc else 'VALIDATION' if start<validation_end_utc else 'TEST'
        if role=='TRAIN_HISTORY':continue
        out=forecast(observations,f,start-1,registry=registry,registry_pin=registry_pin,minimum_team_games=minimum_team_games,simulations=simulations)
        fold=dict(target=f,role=role,cutoff_utc=start-1,status=out['status'],evidence_sha256=out['evidence_sha256'],excluded=out['excluded'])
        try:replay(o,fixture=f,cutoff_utc=asof_utc,maximum_age_seconds=100*366*86400,registry=registry,registry_pin=registry_pin)
        except ValueError as ex:fold.update(status='ABSTAIN',abstain_reason=str(ex));folds.append(fold);continue
        if out['prediction'] is not None:
            q=out['prediction'];actual=p['claims'];pe=period_errors(q,actual)
            row=dict(canonical_id=f['canonical_id'],league=league,season_end_year=season_end_year,scope='REGULATION_ONLY',
                model=MODEL,usage='SYNTHETIC_TEST' if p['usage']=='SYNTHETIC_TEST' else 'RETROSPECTIVE_RESEARCH',
                expected_home=q['home']['total'],expected_away=q['away']['total'],actual_home=actual['regulation_home'],
                actual_away=actual['regulation_away'],probabilities=out['simulation']['probabilities'],cutoff_utc=start-1,
                start_utc=start,result_observed_utc=p['observed_at_utc'])
            cohorts[role].append(row);errors[role].append(pe);fold.update(prediction=q,period_errors=pe,simulation=out['simulation'],result_sha256=o['sha256'])
        else:fold['abstain_reason']=out['abstain_reason']
        folds.append(fold)
    summary={}
    for role,cohort in cohorts.items():
        aggregate=metrics(cohort,minimum_games=minimum_evaluation_games)
        periods=None if aggregate is None else {period:{field:dict(mae=fmean(abs(e[period][field]) for e in errors[role]),
            rmse=math.sqrt(fmean(e[period][field]**2 for e in errors[role]))) for field in ('home','away','total','margin')} for period in PERIODS}
        summary[role]=dict(games=len(cohort),metrics=aggregate,period_metrics=periods)
    return dict(status='RESEARCH_EVALUATED' if any(v['metrics'] is not None for v in summary.values()) else 'ABSTAIN_INSUFFICIENT_EVALUATION_SAMPLE',
        league=league,season_end_year=season_end_year,model=MODEL,scope='REGULATION_ONLY',folds=folds,cohorts=summary,
        split=dict(train_end_utc=train_end_utc,validation_end_utc=validation_end_utc,ties_share_partition=True),
        minimum_evaluation_games=minimum_evaluation_games,parameters_fitted=False,hyperparameters_selected_on_test=False,
        calibration_status='NOT_ESTABLISHED',prospective_records_created=0)
