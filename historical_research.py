"""Chronological research replay, explicitly distinct from real live forecasts.

The score-only reference is a new research baseline, not FAZ13/FAZ28. Strict
replay requires source observation AND ingestion before each target cutoff.
An explicit diagnostic mode can measure event-time assumptions, but never
contributes to verified/live performance or permits model promotion.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
from statistics import mean
import time

from core.team_identity import digest
from historical_backtest import HistoricalPrediction,evaluate_predictions
from research_record_store import HISTORICAL_DATA,BACKTEST_SIMULATION
from season_archive_inventory import validate_catalog


MODEL_VERSION='RESEARCH_SCORE_MATCHUP_V1'
MODEL_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _native_team_stats(catalog,fixture):
    if catalog['provider']!='ESPN': return None,'NOT_COLLECTED_IN_THIS_ADAPTER'
    fields={'rebounds','assists','fieldGoalsAttempted','fieldGoalsMade','freeThrowsAttempted',
        'freeThrowsMade','threePointFieldGoalsAttempted','threePointFieldGoalsMade','points',
        'offensiveRebounds','turnovers'}
    variants=[]
    for event in catalog['raw']['events']:
        if event['id'] not in fixture['provider_fixture_ids']: continue
        result={}
        try:
            for team in event['competitions'][0]['competitors']:
                side=team['homeAway'];values={}
                for stat in team.get('statistics',[]):
                    name=stat['name']
                    if name not in fields:continue
                    value=float(stat['displayValue'])
                    if not math.isfinite(value) or value<0 or not value.is_integer() or value>1000:
                        raise ValueError('INVALID_STATISTIC')
                    value=int(value)
                    if name in values and values[name]!=value:raise ValueError('CONFLICTING_STATISTIC')
                    values[name]=value
                if values:
                    if 'points' in values and values['points']!=fixture['final_scores'][0 if side=='home' else 1]:
                        raise ValueError('STATISTIC_SCORE_CONFLICT')
                    result[side]=values
            variants.append(result)
        except (KeyError,TypeError,ValueError):return None,'STATISTICS_INVALID_OR_CONFLICTING'
    if not variants or not any(variants):return None,'NOT_PRESENT_IN_SOURCE'
    if any(v!=variants[0] for v in variants):return None,'STATISTICS_INVALID_OR_CONFLICTING'
    return dict(scope='FINAL_WITH_OT',teams=variants[0]),'PARTIAL_VERIFIED_NATIVE_STATISTICS'


def historical_rows(catalog_pins):
    """Replay native pinned sources; collapse aliases without inflating matches."""
    versions={};aliases={};slots={}
    for bundle,pin in catalog_pins:
        p=validate_catalog(bundle,trusted_sha256=pin)
        for g in p['fixtures']:
            if not g['completed']: continue
            key=(g['league'],g['canonical_id'])
            row=dict(record_type=HISTORICAL_DATA,league=g['league'],fixture_id=g['canonical_id'],
                season=f"{g['season_start_year']}/{g['season_start_year']+1}",fixture_start_utc=g['start_ts_utc'],
                provider=g['provider'],provider_fixture_ids=g['provider_fixture_ids'],
                home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],
                final_scores=g['final_scores'],periods=g['periods'],source_catalog_sha256=pin,
                observed_at_utc=p['observed_at_utc'],ingested_at_utc=p['ingested_at_utc'],
                source_available_at_utc=None,availability_evidence='OBSERVATION_AND_INGESTION_ONLY',
                team_statistics=None,player_statistics=None,pace=None,efficiency=None,lineups=None,
                rotation=None,injuries=None,prediction=None)
            row['additional_fields_status']='NOT_NORMALIZED_NATIVE_DOCUMENT_RETAINED'
            row['team_statistics'],row['team_statistics_status']=_native_team_stats(p,g)
            identity={k:v for k,v in row.items() if k not in ('source_catalog_sha256','observed_at_utc','ingested_at_utc','provider_fixture_ids')}
            if key in versions:
                previous=versions[key][0]
                other={k:v for k,v in previous.items() if k not in ('source_catalog_sha256','observed_at_utc','ingested_at_utc','provider_fixture_ids')}
                if identity!=other: raise ValueError('CONFLICTING_HISTORICAL_RESULT')
            for pid in g['provider_fixture_ids']:
                a=(g['provider'],pid)
                if a in aliases and aliases[a]!=key: raise ValueError('HISTORICAL_PROVIDER_ID_CONFLICT')
                aliases[a]=key
            for team in (g['home_team_id'],g['away_team_id']):
                s=(g['league'],team,g['start_ts_utc'])
                if s in slots and slots[s]!=key: raise ValueError('HISTORICAL_TEAM_START_CONFLICT')
                slots[s]=key
            versions.setdefault(key,[]).append(row)
    # Preserve versions: a later duplicate must not erase earlier availability.
    return [sorted(v,key=lambda r:(r['ingested_at_utc'],r['source_catalog_sha256']))
            for k,v in sorted(versions.items(),key=lambda kv:(kv[1][0]['fixture_start_utc'],kv[0]))]


def _scores(row):
    p=row['periods']
    return None if p is None else [sum(p['home'][:4]),sum(p['away'][:4])]


def feature_cut(target,cohort,*,assume_availability=False,min_games=6,window=10):
    if type(assume_availability) is not bool or type(min_games) is not int or type(window) is not int or not 1<=min_games<=window<=100:
        raise ValueError('INVALID_RESEARCH_CONFIGURATION')
    cutoff=target['fixture_start_utc']-1
    eligible=[]
    for versions in cohort:
        choices=[r for r in versions if r['league']==target['league'] and r['season']==target['season'] and
            r['fixture_id']!=target['fixture_id'] and r['fixture_start_utc']<cutoff and _scores(r) is not None and
            ((assume_availability and r['fixture_start_utc']<=cutoff-86400) or
             (not assume_availability and r['observed_at_utc']<=r['ingested_at_utc']<=cutoff))]
        if choices: eligible.append(min(choices,key=lambda r:(r['ingested_at_utc'],r['source_catalog_sha256'])))
    features={};pins=[]
    for side in ('home','away'):
        tid=target[side+'_team_id']
        recent=sorted([r for r in eligible if tid in (r['home_team_id'],r['away_team_id'])],key=lambda r:(r['fixture_start_utc'],r['fixture_id']))[-window:]
        if len(recent)<min_games: return None
        pf=[];pa=[];quarters_for=[];quarters_against=[]
        for r in recent:
            scores=_scores(r);h=r['home_team_id']==tid
            pf.append(scores[0 if h else 1]);pa.append(scores[1 if h else 0])
            quarters_for.append(r['periods']['home' if h else 'away'][:4])
            quarters_against.append(r['periods']['away' if h else 'home'][:4])
            pins.append(dict(fixture_id=r['fixture_id'],source_catalog_sha256=r['source_catalog_sha256'],
                observed_at_utc=r['observed_at_utc'],ingested_at_utc=r['ingested_at_utc']))
        features[side]=dict(team_id=tid,n_games=len(recent),points_for=mean(pf),points_against=mean(pa),
            quarters_for=[mean(p[q] for p in quarters_for) for q in range(4)],
            quarters_against=[mean(p[q] for p in quarters_against) for q in range(4)])
    return dict(cutoff_utc=cutoff,home=features['home'],away=features['away'],
                source_inputs=sorted({digest(p):p for p in pins}.values(),key=digest))


def reference_predict(features):
    """Receives features only: no target label, final score or target periods."""
    h=(features['home']['points_for']+features['away']['points_against'])/2
    a=(features['away']['points_for']+features['home']['points_against'])/2
    quarters={side:[(features[side]['quarters_for'][q]+features['away' if side=='home' else 'home']['quarters_against'][q])/2
                    for q in range(4)] for side in ('home','away')}
    halves={side:[sum(quarters[side][:2]),sum(quarters[side][2:])] for side in ('home','away')}
    return dict(home=h,away=a,total=h+a,margin=h-a,quarters=quarters,halves=halves,home_win_probability=None)


def simulate_history(catalog_pins,*,assume_availability=False,min_games=6,window=10,store=None):
    cohort=historical_rows(catalog_pins);runs=[]
    # Validate configuration even when the cohort is empty.
    if type(assume_availability) is not bool or type(min_games) is not int or type(window) is not int or not 1<=min_games<=window<=100:
        raise ValueError('INVALID_RESEARCH_CONFIGURATION')
    for versions in cohort:
        target=versions[0]
        if store:
            for row in versions: store.append(HISTORICAL_DATA,digest(row),row)
        features=feature_cut(target,cohort,assume_availability=assume_availability,min_games=min_games,window=window)
        cls=('AVAILABILITY_ASSUMED_RESEARCH' if assume_availability else 'PIT_PROVEN_BACKTEST') if features else 'ABSTAIN'
        prediction=None if features is None else reference_predict(deepcopy(features))
        # Label is joined only after the predictor has returned.
        actual=_scores(target)
        run=dict(record_type=BACKTEST_SIMULATION,league=target['league'],season=target['season'],
            fixture_id=target['fixture_id'],fixture_start_utc=target['fixture_start_utc'],cutoff_utc=target['fixture_start_utc']-1,
            home_team_id=target['home_team_id'],away_team_id=target['away_team_id'],
            model_version=f'{MODEL_VERSION}:{MODEL_SOURCE_SHA256[:12]}:w{window}:n{min_games}',
            model_source_sha256=MODEL_SOURCE_SHA256,scope='REGULATION_ONLY',evaluation_class=cls,
            availability_policy='EVENT_TIME_24H_ASSUMPTION' if assume_availability else 'SOURCE_OBSERVED_AND_INGESTED',
            reason=None if features else 'INSUFFICIENT_PRE_CUTOFF_SOURCE_EVIDENCE_OR_PERIOD_HISTORY',
            prediction=prediction,actual=actual,features=features,pace=None,
            actual_periods=None if target['periods'] is None else {s:target['periods'][s][:4] for s in ('home','away')},
            generated_at_utc=int(time.time()),
            source_catalog_sha256=target['source_catalog_sha256'],automatic_model_update_permitted=False)
        if store:
            stable={k:v for k,v in run.items() if k!='generated_at_utc'}
            # Creation time is provided by the store, never the historical cutoff.
            store.append(BACKTEST_SIMULATION,digest(stable),stable)
        runs.append(run)
    return dict(record_type=BACKTEST_SIMULATION,historical_games=len(cohort),runs=runs,
        prospective_predictions_created=0,automatic_model_update_permitted=False)


def metrics_report(runs):
    """Never pool availability classes, leagues, seasons or model versions."""
    groups={};teams={}
    for r in runs:
        if r.get('record_type')!=BACKTEST_SIMULATION: raise ValueError('ONLY_SIMULATION_RECORDS_ALLOWED')
        if r['prediction'] is None or r['actual'] is None: continue
        key=(r['league'],r['season'],r['model_version'],r['evaluation_class'],r['scope'])
        groups.setdefault(key,[]).append(r)
    result=[]
    for key,rows in sorted(groups.items()):
        seen=set();records=[];margins=[]
        for r in rows:
            if r['fixture_id'] in seen: raise ValueError('DUPLICATE_SIMULATION_FIXTURE')
            seen.add(r['fixture_id']);p=r['prediction'];h,a=r['actual']
            records.append(HistoricalPrediction(r['fixture_id'],r['league'],r['cutoff_utc'],r['generated_at_utc'],
                p['home'],p['away'],h,a,p.get('home_win_probability') if h!=a else None,'REGULATION_ONLY','REGULATION_ONLY',r['fixture_start_utc']))
            margins.append(p['home']-p['away']-h+a)
            for side,actual in [('home',h),('away',a)]:
                teams.setdefault((*key,r[side+'_team_id']),[]).append(p[side]-actual)
        metrics=asdict(evaluate_predictions(records))
        metrics.update(margin_mae=mean(abs(e) for e in margins),margin_rmse=math.sqrt(mean(e*e for e in margins)),margin_bias=mean(margins))
        for side,index in [('home',0),('away',1)]:
            errors=[r['prediction'][side]-r['actual'][index] for r in rows]
            metrics[side+'_mae']=mean(abs(e) for e in errors)
            metrics[side+'_rmse']=math.sqrt(mean(e*e for e in errors))
        decisive=[r for r in rows if r['prediction']['home']!=r['prediction']['away'] and r['actual'][0]!=r['actual'][1]]
        metrics['winner_direction_n']=len(decisive)
        metrics['winner_direction_accuracy']=None if not decisive else mean(
            (r['prediction']['home']>r['prediction']['away'])==(r['actual'][0]>r['actual'][1]) for r in decisive)
        bins=[]
        for i in range(10):
            bucket=[r for r in rows if r['prediction'].get('home_win_probability') is not None and
                min(9,int(10*r['prediction']['home_win_probability']))==i and r['actual'][0]!=r['actual'][1]]
            bins.append(dict(lower=i/10,upper=(i+1)/10,n=len(bucket),
                mean_probability=mean(r['prediction']['home_win_probability'] for r in bucket) if bucket else None,
                observed_frequency=mean(r['actual'][0]>r['actual'][1] for r in bucket) if bucket else None))
        periods={}
        for name,indices in [('1Q',[0]),('2Q',[1]),('3Q',[2]),('4Q',[3]),('1H',[0,1]),('2H',[2,3])]:
            errors=[sum(r['prediction']['quarters'][s][q] for q in indices)-sum(r['actual_periods'][s][q] for q in indices)
                    for r in rows if r['prediction'].get('quarters') is not None and r.get('actual_periods') is not None for s in ('home','away')]
            periods[name]=None if not errors else dict(n_team_scores=len(errors),mae=mean(abs(e) for e in errors),
                rmse=math.sqrt(mean(e*e for e in errors)),bias=mean(errors))
        result.append(dict(league=key[0],season=key[1],model_version=key[2],evaluation_class=key[3],scope=key[4],
            metrics=metrics,calibration_curve=bins,period_metrics=periods,pace_stratification='PACE_NOT_AVAILABLE',
            actual_live_prematch_performance=False,automatic_model_update_permitted=False))
    team_metrics=[dict(league=k[0],season=k[1],model_version=k[2],evaluation_class=k[3],scope=k[4],team_id=k[5],
        n=len(v),mae=mean(abs(e) for e in v),rmse=math.sqrt(mean(e*e for e in v)),bias=mean(v)) for k,v in sorted(teams.items())]
    return dict(groups=result,teams=team_metrics,automatic_model_update_permitted=False)


def chronological_evaluation(runs,*,train_end_utc,validation_end_utc,test_end_utc,minimum_train=100,minimum_evaluation=30):
    if (any(type(t) is not int for t in (train_end_utc,validation_end_utc,test_end_utc)) or
            not 0<train_end_utc<validation_end_utc<test_end_utc<=int(time.time()) or
            type(minimum_train) is not int or type(minimum_evaluation) is not int or
            min(minimum_train,minimum_evaluation)<2):
        raise ValueError('ORDERED_INDEPENDENT_PERIODS_REQUIRED')
    split={name:[] for name in ('TRAIN','VALIDATION','TEST')}
    for r in runs:
        t=r['fixture_start_utc']
        if t>=test_end_utc: continue
        split['TRAIN' if t<train_end_utc else 'VALIDATION' if t<validation_end_utc else 'TEST'].append(r)
    # Adequacy is per league/season/model and proven PIT class; assumed research
    # samples never satisfy the independent evidence threshold.
    output={name:dict(targets=len(rows),evaluated=sum(r['prediction'] is not None for r in rows),report=metrics_report(rows)) for name,rows in split.items()}
    keys={(r['league'],r['season'],r['model_version']) for r in runs}
    adequacy=[]
    for league,season,model in sorted(keys):
        counts={name:sum(r['league']==league and r['season']==season and r['model_version']==model and
                r['evaluation_class']=='PIT_PROVEN_BACKTEST' and r['prediction'] is not None for r in rows) for name,rows in split.items()}
        adequacy.append(dict(league=league,season=season,model_version=model,proven_counts=counts,
            threshold_met=counts['TRAIN']>=minimum_train and min(counts['VALIDATION'],counts['TEST'])>=minimum_evaluation))
    return dict(periods=output,adequacy=adequacy,model_fitting_performed=False,
        automatic_model_update_permitted=False,note='Fixed rolling reference; no coefficients fitted or promoted.')
