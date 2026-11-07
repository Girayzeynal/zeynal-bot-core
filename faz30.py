"""Read-only FAZ29 baseline diagnostics. No model fitting or forecast creation."""
from itertools import combinations
import json
from pathlib import Path
import time

from prospective_error_audit import audit,read_only_ledger
from prediction_inputs import validate_prediction_inputs
from model_evaluation import score_metrics,paired_compare,walk_forward_plan
from period_feature_layer import materialize_period,export_observations
from simulation_assumptions import variance_contract


def input_coverage(snapshot):
    p=snapshot['payload'];cutoff=p['prediction_ts_utc']
    validate_prediction_inputs(snapshot,league='NBA',prediction_utc=cutoff,
        expected_home=p['expected_home'],expected_away=p['expected_away'])
    coverage={};periods=[]
    for side,item in p['teams'].items():
        rows=item['records'];opponents=set();observed=[];pace_estimates=0;period_count=0;period_missing=0
        for index,row in enumerate(rows):
            evidence=row.get('pace_evidence')
            if not evidence:
                period_missing+=1;continue
            source=evidence.get('snapshot',{});game=source.get('game',{})
            opponent='away_team_id' if row['home'] else 'home_team_id'
            if isinstance(game.get(opponent),str):opponents.add(game[opponent])
            if evidence.get('kind')=='BOX_SCORE_ESTIMATE':pace_estimates+=1
            if type(source.get('observed_at_utc')) is int:observed.append(source['observed_at_utc'])
            try:
                record=materialize_period(source['summary'],source_observed_utc=source['observed_at_utc'],
                    source_evidence_sha256=evidence['snapshot_sha256'],
                    input_ref=dict(snapshot_sha256=snapshot['sha256'],side=side,index=index))
                periods.append(record);period_count+=1
            except (KeyError,ValueError,TypeError):period_missing+=1
        coverage[side]=dict(team=item['key'],raw_offense_games=len(rows),raw_defense_games=len(rows),
            distinct_identified_opponents=len(opponents),opponent_adjusted_strength='NOT_COMPUTED',
            possession_adjusted_offense_defense='NOT_COMPUTED',pace_estimate_games=pace_estimates,measured_pace_games=0,
            retained_source_period_games=period_count,missing_period_games=period_missing,
            home_games=sum(r['home'] is True for r in rows),away_games=sum(r['home'] is False for r in rows),
            fitted_home_advantage='NOT_ESTABLISHED',source_time_verified_games=len(observed),
            latest_source_observation_utc=max(observed) if observed else None,
            latest_source_age_at_prediction_seconds=cutoff-max(observed) if observed else None,
            observed_last_game_start_gap_hours=(cutoff-max(r['ts_utc'] for r in rows))/3600,
            rest_or_travel_duration_verified=False,verified_injuries=False,verified_rosters=False,verified_market=False)
    return dict(input_sha256=snapshot['sha256'],original_prediction_utc=cutoff,teams=coverage,
                status='RAW_FEATURE_COVERAGE_NOT_CALIBRATED_MODEL_READINESS'),periods


def report(paths):
    rows=[];coverage=[];features=[];simulation_diagnostics=[];integrity=[]
    # Individual ledger audits retain their provenance checks. A shadow version
    # may share a game with another ledger; same-cohort duplication is forbidden.
    for path in paths:
        verified=audit([path]);integrity+=verified['ledgers']
        rows.extend(r for r in verified['rows'] if r['status']=='evaluated')
        ledger=read_only_ledger(path)
        with ledger._connect() as db:bundles=db.execute('SELECT fixture_id,payload FROM faz24_stages').fetchall()
        for fixture,raw in bundles:
            bundle=json.loads(raw);snapshot=ledger.load_prediction_inputs('NBA',fixture)
            entry,records=input_coverage(snapshot)
            coverage.append(dict(fixture_id=fixture,model_version=bundle['model_version'],**entry));features+=records
            layer=bundle.get('multilayer')
            if layer and layer.get('simulation'):
                v=layer['variance']['values'];cfg=layer['config'];sim=layer['simulation']
                simulation_diagnostics.append(dict(fixture_id=fixture,model_version=bundle['model_version'],
                    contract=variance_contract(v['home'],v['away'],cfg['score_correlation']),
                    stored_observed_home_std=sim['observed_home_std'],stored_observed_away_std=sim['observed_away_std'],
                    stored_observed_correlation=sim['observed_score_correlation'],stored_total_std=sim['total_std'],
                    seed=cfg['seed'],scenarios=cfg['simulations'],simulation_rerun=False,
                    interpretation='SIMULATOR_ASSUMPTIONS_NOT_REAL_OUTCOME_VARIANCE_CALIBRATION'))
    grouped={}
    for row in rows:
        key=(row['model'],row['model_version'],row['scope'])
        cohort=grouped.setdefault(key,[])
        if any(r['fixture_id']==row['fixture_id'] for r in cohort):raise ValueError('duplicate same-cohort fixture')
        cohort.append(row)
    cohorts=[dict(model=k[0],model_version=k[1],scope=k[2],metrics=score_metrics(v)) for k,v in grouped.items()]
    comparisons=[]
    for a,b in combinations(grouped,2):
        comparisons.append(dict(left=dict(model=a[0],version=a[1],scope=a[2]),
            right=dict(model=b[0],version=b[1],scope=b[2]),comparison=paired_compare(grouped[a],grouped[b])))
    unique_features=export_observations(features)
    return dict(cohorts=cohorts,paired_comparisons=comparisons,coverage=coverage,
        period_feature_layer=dict(materialized_records=len(features),distinct_games=len(unique_features),
            records=unique_features,usage='NEW_HISTORICAL_FEATURE_EXPORT_NOT_A_PREDICTION',
            available_to_original_forecasts=False),
        temporal_plan=walk_forward_plan(rows),simulation_diagnostics=simulation_diagnostics,
        ledger_integrity=integrity,unique_evaluated_games=len({r['fixture_id'] for r in rows}),
        coefficients_changed=False,forecasts_regenerated=False,calibration_status='NOT_ESTABLISHED',
        statistical_status='SMALL_SAMPLE_DESCRIPTIVE_ONLY')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('ledgers',nargs='+')
    args=parser.parse_args()
    print(json.dumps(report(args.ledgers),sort_keys=True,allow_nan=False))
