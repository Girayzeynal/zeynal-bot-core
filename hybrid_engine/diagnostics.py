"""Offline OOS diagnostics; never tunes scores, calibrates on TEST, or promotes models."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from hybrid_engine.data import STRICT, local_path
from hybrid_engine.root_cause import verify_predictions, matched_panels
from hybrid_engine.statistics import calibration_curve, paired_cluster_interval, paired_winner_interval, market_metrics
from hybrid_engine.walkforward import LINE_MARKETS


def signed_bias(rows, *, iterations=2000, seed=20261112):
    """Descriptive bias on held-out games; it is not a fitted score correction."""
    if not rows: return dict(n=0, status='NO_OOS_GAMES')
    if len({r['fixture_id'] for r in rows}) != len(rows): raise ValueError('DUPLICATE_OOS_FIXTURE')
    q=np.asarray([r['prediction']['quarters'] for r in rows])
    a=np.asarray([r['actual_quarters'] for r in rows]); e=q-a
    names=['1Q','2Q','3Q','4Q','1H','2H','TOTAL','HOME','AWAY','MARGIN']
    total=e.sum(axis=1)
    errors=np.column_stack([e[:,i].sum(axis=1) for i in range(4)]+
        [e[:,:2].sum(axis=(1,2)),e[:,2:].sum(axis=(1,2)),total.sum(axis=1),
         total[:,0],total[:,1],total[:,0]-total[:,1]])
    days=np.asarray([(r['start_utc']+10800)//86400 for r in rows]); unique=sorted(set(days))
    intervals=[None]*len(names)
    if len(unique)>=8:
        groups=[np.flatnonzero(days==d) for d in unique];rng=np.random.default_rng(seed)
        samples=np.array([errors[np.concatenate([groups[j] for j in rng.integers(0,len(groups),len(groups))])].mean(axis=0)
            for _ in range(iterations)])
        alpha=.05/len(names);intervals=np.quantile(samples,[alpha/2,1-alpha/2],axis=0).T.tolist()
    return dict(n=len(rows),day_clusters=len(unique),
        status='EXPLORATORY_NOT_A_CORRECTION' if len(unique)>=8 else 'INSUFFICIENT_DAY_CLUSTERS_FOR_CLAIM',
        family_size=len(names),unit='TSI_GAME_DAY_CLUSTER',
        markets={name:dict(mean_signed_error=float(errors[:,j].mean()),familywise_interval=intervals[j])
                 for j,name in enumerate(names)},score_correction_applied=False)


def calibration_readiness(rows):
    counts=Counter((r['trace']['model_digest'],m['market'],m['line']) for r in rows
        for m in r['line_grid'] if m['probabilities'] is not None)
    maximum=max(counts.values(),default=0)
    return dict(status='ABSTAIN',verified_profiles=0,confidence_index=None,
        required_fit_games=100,required_later_disjoint_audit_games=100,
        maximum_exact_model_market_line_oos_games=maximum,
        reason='INSUFFICIENT_EXACT_PROFILE_SAMPLES' if maximum<200 else 'REQUIRES_SEPARATE_PAST_FIT_AND_LATER_AUDIT',
        test_labels_used_for_calibration=False,
        rule='DESCRIPTIVE_OOS_CURVES_ARE_NOT_A_VERIFIED_CALIBRATION_ARTIFACT')


def diagnose(report):
    if report.get('evaluation_class')!=STRICT: raise ValueError('STRICT_OOS_REPORT_REQUIRED')
    verification=verify_predictions(report);leagues={}
    for key,c in report['cohorts'].items():
        rows=c['model_rows'];base=rows['FAZ13_MC'];models={}
        for name,candidate in rows.items():
            ids={r['fixture_id'] for r in base}&{r['fixture_id'] for r in candidate}
            b=[r for r in base if r['fixture_id'] in ids];v=[r for r in candidate if r['fixture_id'] in ids]
            if any(r['role']!='TEST' for r in b+v):raise ValueError('DIAGNOSTICS_REQUIRE_HELD_OUT_TEST')
            winners=[r for r in v if r['prediction']['winner'] is not None]
            models[name]=dict(n_common=len(ids),comparison=paired_cluster_interval(b,v),
                winner_comparison=paired_winner_interval(b,v),
                signed_bias=signed_bias(v),calibration_readiness=calibration_readiness(v),
                markets={m:market_metrics(v,m,0.) for m in LINE_MARKETS},
                winner_calibration={side:calibration_curve(
                    [r['prediction']['winner'][i] for r in winners],
                    [int((0 if r['actual'][0]>r['actual'][1] else 1 if r['actual'][0]==r['actual'][1] else 2)==i) for r in winners])
                    for i,side in enumerate(('home','tie','away'))})
        leagues[key]=dict(n_faz13=len(base),status=c.get('status','EVALUATED'),reason=c.get('reason'),
            matched_panels=matched_panels(rows),models=models)
    return dict(format='FAZ84_1_OOS_DIAGNOSTICS_V1',prediction_verification=verification,cohorts=leagues,
        source_file_pins=report['source_file_pins'],manifest_sha256=report['provenance']['manifest_sha256'],
        independent_new_holdout=False,posthoc_score_or_probability_correction=False,
        inference='EXPLORATORY_REUSED_OOS_DATA_NOT_FRESH_CONFIRMATORY_EVIDENCE',
        production_default='FAZ13',production_changed=False,decision='NO_GO')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--backtest-report',required=True)
    p.add_argument('--output',required=True);args=p.parse_args();path=local_path(args.backtest_report)
    raw=path.read_bytes();report=json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)
    result=diagnose(report);result['backtest_file_sha256']=hashlib.sha256(raw).hexdigest()
    local_path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False))
    print(json.dumps(dict(output=args.output,cohorts={k:v['n_faz13'] for k,v in result['cohorts'].items()},decision=result['decision'])))


if __name__=='__main__':main()
