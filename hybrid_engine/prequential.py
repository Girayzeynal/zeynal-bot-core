"""Fixed-policy chronological replay for small cohorts; does not relax acceptance folds."""
import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

from core.team_identity import digest
from hybrid_engine.audit import known_fixture
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT,Abstain,available_at,feature_cut,load_manifest,local_path
from hybrid_engine.evaluation import summarize
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.statistics import paired_cluster_interval,paired_winner_interval
from hybrid_engine.walkforward import forecast_all,serialize,MODELS,BASELINES


def evaluate(cohort,provenance,league='EuroCup'):
    candidates=[];reasons=Counter();rows={n:[] for n in MODELS+BASELINES}
    pins={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')};code=digest(pins)
    for versions in cohort:
        native=[r for r in versions if r.get('_native_truth',True)]
        r=max(native,key=lambda v:v['ingested_at_utc'])
        if r['league']!=league:continue
        try:
            fixture=known_fixture(r,provenance['fixture_knowledge'],r['fixture_start_utc']-1)
            cut=feature_cut(cohort,r,mode=STRICT)
        except Abstain as e:reasons[str(e)]+=1;continue
        cut=replace(cut,inputs_digest=digest(dict(features=cut.inputs_digest,fixture=fixture)))
        candidates.append((cut,r,fixture))
    for cut,r,fixture in sorted(candidates,key=lambda x:(x[0].cutoff_utc,x[0].target['fixture_id'])):
        bayes=None
        try:bayes=HierarchicalStrength().fit(cut.history,cutoff_utc=cut.cutoff_utc,mode=STRICT)
        except Abstain as e:reasons['BAYES:'+str(e)]+=1
        # No validation-based selection, calibration or ensemble is fitted to this
        # cohort. Native ML needs >=100 past eligible examples; only 15 exist.
        forecasts,elapsed=forecast_all(cut,bayes,{},reasons)
        for name,f in forecasts.items():
            saved=serialize(cut,f,r,elapsed[name],-1,code,fixture)
            saved['capture_kind']='RETROSPECTIVE_PREQUENTIAL_REPLAY_NOT_ACTUAL_PREMATCH_RECORD'
            if saved['trace']['data_time_utc']>cut.cutoff_utc:raise ValueError('PREQUENTIAL_FUTURE_INPUT')
            rows[name].append(saved)
    return dict(format='SMALL_COHORT_PREQUENTIAL_REPLAY_V1',generated_at_utc=int(time.time()),league=league,
        protocol='FIXED_HYPERPARAMETERS_EXPANDING_PAST_LABELS_NO_SELECTION_NO_CALIBRATION',
        candidates=len(candidates),distinct_kickoffs=len({c.cutoff_utc for c,r,f in candidates}),
        model_rows=rows,metrics={n:summarize(v) for n,v in rows.items()},abstentions=dict(reasons),
        paired_vs_faz13={n:dict(points=paired_cluster_interval(rows['FAZ13_MC'],v),winner=paired_winner_interval(rows['FAZ13_MC'],v))
            for n,v in rows.items() if n!='FAZ13_MC'},
        native_ml_status='INSUFFICIENT_PAST_ELIGIBLE_TRAINING_AND_VALIDATION_EXAMPLES',
        acceptance_walkforward_minimum_distinct_kickoffs=20,acceptance_fold_policy_changed=False,
        acceptance_status='NOT_ACCEPTANCE_EVIDENCE',fresh_confirmatory_holdout=False,
        calibration_fit=False,ensemble_fit=False,production_default='FAZ13',production_changed=False,
        source_pins=pins,manifest_sha256=provenance['manifest_sha256'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--output-directory',required=True)
    args=p.parse_args();cohort,provenance=load_manifest(args.manifest);report=evaluate(cohort,provenance)
    root=local_path(args.output_directory);root.mkdir(exist_ok=True,parents=True);path=root/('cup-prequential-'+digest(report)+'.json')
    publish_json(path,report);print(json.dumps(dict(path=str(path),candidates=report['candidates'],metrics=report['metrics'],acceptance=report['acceptance_status'])))


if __name__=='__main__':main()
