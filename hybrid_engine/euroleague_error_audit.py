"""Postgame diagnostics of frozen components. Never fits or rewrites predictions."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.boxes import publish_json,normalize_box
from hybrid_engine.data import Cut,local_path
from hybrid_engine.frozen_archive import FrozenArchive,read_gzip
from hybrid_engine.intervals import prediction_intervals,empirical_coverage,sample_paths,assert_frozen_sampler_sources
from hybrid_engine.prospective_results import ProspectiveResults


def timing_eligibility(record):
    """Snapshot capture time does not establish a separately recorded generation time."""
    generated=record.get('prediction_generated_at_utc');archived=record.get('first_archived_at_utc')
    tip=record['fixture']['start_ts_utc'];created=record['created_at_utc']
    eligible=all(type(v) is int for v in (generated,archived,created,tip)) and 0<generated<=created<=archived<tip
    return dict(strict_pregame_eligible=eligible,generation_utc=generated,first_archived_utc=archived,
        snapshot_capture_utc=created,tipoff_utc=tip,
        reason=None if eligible else 'SEPARATE_GENERATION_OR_ARCHIVE_CLOCK_UNPROVEN',
        use='STRICT_PROSPECTIVE' if eligible else 'DESCRIPTIVE_FROZEN_CAPTURE_ONLY')


def error_cells(prediction,periods):
    q=np.array([periods[s][:4] for s in ('home','away')],dtype=float).T
    p=np.asarray(prediction['quarters'],dtype=float);e=p-q
    if p.shape!=(4,2) or q.shape!=(4,2):raise ValueError('COHERENT_FOUR_QUARTERS_REQUIRED')
    if not np.allclose(p.sum(axis=0),[prediction['home'],prediction['away']],atol=1e-8):raise ValueError('INCOHERENT_PROJECTION')
    error=e.sum(axis=0);actual=q.sum(axis=0);actual_margin=actual[0]-actual[1]
    predicted_margin=prediction['home']-prediction['away']
    return dict(prediction=[prediction['home'],prediction['away']],actual=actual.tolist(),
        home_error=float(error[0]),away_error=float(error[1]),total_error=float(error.sum()),
        total_absolute_error=float(abs(error.sum())),total_squared_error=float(error.sum()**2),
        margin_error=float(error[0]-error[1]),winner_direction_correct=bool(np.sign(predicted_margin)==np.sign(actual_margin)),
        quarter_errors=e.tolist(),half_errors=[e[:2].sum(axis=0).tolist(),e[2:].sum(axis=0).tolist()],
        quarter_total_errors=e.sum(axis=1).tolist(),half_total_errors=[float(e[:2].sum()),float(e[2:].sum())])


def allocation_diagnostics(forecast,cut,periods):
    paths=sample_paths(forecast);actual=np.array([periods[s][:4] for s in ('home','away')]).T
    output={}
    for j,side in enumerate(('home','away')):
        tid=cut.target[side+'_team_id'];prior=[]
        for row in cut.history:
            if tid not in (row['home_team_id'],row['away_team_id']):continue
            own='home' if row['home_team_id']==tid else 'away';prior.append(row['periods'][own][:4])
        historical=np.asarray(prior[-10:],dtype=float)
        if len(historical)<2:continue
        q=np.quantile(paths[:,:,j],[.05,.25,.5,.75,.95],axis=0)
        output[side]=dict(history_n=len(historical),history_mean=historical.mean(axis=0).tolist(),
            history_sd=historical.std(axis=0,ddof=1).tolist(),simulated_sd=paths[:,:,j].std(axis=0,ddof=1).tolist(),
            actual=actual[:,j].tolist(),p05=q[0].tolist(),p95=q[4].tolist(),
            actual_outside_p05_p95=((actual[:,j]<q[0])|(actual[:,j]>q[4])).tolist(),
            estimated_rest_gap_hours=cut.features[side]['start_gap_hours'],
            rest_gap_kind='START_TIME_GAP_PROXY_NOT_VERIFIED_REST',
            allocation='FIXED_HISTORICAL_WEIGHTS_LARGEST_REMAINDER_NOT_DYNAMIC_QUARTER_EVENTS')
    pair=set((cut.target['home_team_id'],cut.target['away_team_id']))
    h2h=[dict(fixture_id=r['fixture_id'],start_utc=r['fixture_start_utc'],scores=r['final_scores'])
        for r in cut.history if {r['home_team_id'],r['away_team_id']}==pair]
    return dict(teams=output,known_prior_head_to_head=h2h,causal_claim=False,
        unverified=['PREMATCH_ROTATIONS','MATCHUP_DEFENSIVE_SCHEMES','FATIGUE','DERBY_EFFECT','EARLY_PBP_PACE'],
        model_parameters_changed=False)


def box_diagnostics(record,cut,outcome,receipt):
    row=dict(league='EuroLeague',season='2026/2027',fixture_id=record['fixture']['canonical_id'],provider='EUROLEAGUE_LIVE',
        fixture_start_utc=record['fixture']['start_ts_utc'],provider_fixture_ids=record['fixture']['provider_fixture_ids'],
        home_team_id=record['fixture']['home_team_id'],away_team_id=record['fixture']['away_team_id'],
        periods=outcome['periods'],final_scores=outcome['final_with_ot'])
    box=normalize_box(row,receipt);pace=float(np.mean([box['teams'][s]['possessions_estimate'] for s in ('home','away')]))
    baseline=record['models']['POSSESSION_ANALYTIC']['prediction'];prior_pace=baseline['metadata']['pace_mean']
    efficiency=baseline['total']/prior_pace;actual_total=sum(outcome['actual'])
    metrics={}
    for side in ('home','away'):
        b=box['teams'][side];prior=[item[1]['teams'][item[2]] for item in cut.features[side]['boxes']]
        attempts=sum(v['fga3'] for v in prior);makes=sum(v['fgm3'] for v in prior)
        metrics[side]=dict(estimated_possessions=b['possessions_estimate'],points_per_estimated_possession=b['points']/b['possessions_estimate'],
            three_point_made=b['fgm3'],three_point_attempted=b['fga3'],
            three_point_rate=b['fgm3']/b['fga3'] if b['fga3'] else None,
            prior_pooled_three_point_rate=makes/attempts if attempts else None,prior_box_games=len(prior),
            rotation_causal_effect=None)
    return dict(source_sha256=receipt['document_sha256'],source_url=receipt['source_url'],
        observed_at_utc=receipt['observed_at_utc'],teams=metrics,actual_estimated_pace=pace,
        possession_baseline_pace=prior_pace,actual_total=actual_total,possession_baseline_total=baseline['total'],
        pace_term=(pace-prior_pace)*efficiency,efficiency_term=actual_total-pace*efficiency,
        decomposition='ACTUAL_MINUS_POSSESSION_BASELINE;ALGEBRAIC_NOT_CAUSAL;NOT_BAYESIAN_ATTRIBUTION',
        possession_measurement='FGA_PLUS_0.44FTA_MINUS_ORB_PLUS_TOV_PROXY_NOT_PBP',used_for_pregame_forecast=False)


def audit(archive,results,*,box_receipts=()):
    outcomes=results.outcomes();rows=[];cases={};box_index={r['source_url']:r for r in box_receipts if r.get('status')=='DOCUMENT_RECEIVED'}
    for fid,record in archive.records.items():
        if fid not in outcomes:continue
        assert_frozen_sampler_sources(record);outcome=outcomes[fid]
        cut=Cut(**read_gzip(archive.path/('inputs-'+record['input_file_sha256']+'.json.gz')))
        components={};allocation=None
        for name,m in record['models'].items():
            if m['status']!='FORECAST_CREATED':continue
            forecast=archive.replay(record,name,cut=cut);bands=prediction_intervals(forecast)
            cases.setdefault(name,[]).append((bands,outcome['periods']))
            cells=error_cells(m['prediction'],outcome['periods']);cells.update(model_version=m['model_version'],bands=bands)
            components[name]=cells
            if name=='BAYES_QMC':allocation=allocation_diagnostics(forecast,cut,outcome['periods'])
        url='https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games/'+record['fixture']['provider_fixture_id'].split('_')[1]+'/stats'
        box=box_diagnostics(record,cut,outcome,box_index[url]) if url in box_index else dict(status='POSTGAME_BOX_UNAVAILABLE')
        rows.append(dict(fixture_id=fid,provider_fixture_id=record['fixture']['provider_fixture_id'],fixture=record['fixture'],
            forecast_sha256=digest(record),outcome_sha256=digest(outcome),timing=timing_eligibility(record),
            actual_regulation=outcome['actual'],actual_full=outcome['final_with_ot'],actual_periods=outcome['periods'],
            result_source=dict(file=outcome['source_file'],document_sha256=outcome['source_document_sha256'],observed_utc=outcome['observed_at_utc']),
            components=components,quarter_model_diagnostics=allocation,postgame_box=box,
            ensemble=dict(status='NOT_TRAINED',weights=None),market_status='MARKET_UNAVAILABLE',calibration_status='UNCALIBRATED'))
    descriptive=results.comparison()
    for m in descriptive['models'].values():m.pop('runtime_seconds',None)
    return dict(format='PHASE845_EUROLEAGUE_ERROR_AUDIT_V1',created_at_utc=int(time.time()),descriptive_games=len(rows),
        strict_pregame_performance_games=sum(r['timing']['strict_pregame_eligible'] for r in rows),
        descriptive_metrics_not_verified_prospective_success=True,rows=rows,comparison=descriptive,
        coverage={name:empirical_coverage(v) for name,v in cases.items()},
        intervals_reconstructed_from_frozen_samples_after_results=True,
        calibration_fit=False,ensemble_fit=False,engine_changed=False,production_decision='NO_GO')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive-directory',required=True);p.add_argument('--results-directory',required=True)
    p.add_argument('--box-receipt',action='append',default=[]);p.add_argument('--output-directory',required=True);a=p.parse_args()
    archive=FrozenArchive(a.archive_directory);r=audit(archive,ProspectiveResults(archive,a.results_directory),
        box_receipts=[json.loads(local_path(f).read_text()) for f in a.box_receipt])
    root=local_path(a.output_directory);root.mkdir(parents=True,exist_ok=True);path=root/('euroleague-audit-'+digest(r)+'.json')
    publish_json(path,dict(payload=r,sha256=digest(r)));print(json.dumps(dict(path=str(path),descriptive_games=r['descriptive_games'],strict_games=r['strict_pregame_performance_games'])))


if __name__=='__main__':main()
