"""Strict chronological NBA replay using an explicit directory of native receipts."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean

from core.team_identity import digest
from hybrid_engine import nba_dynamic
from hybrid_engine.availability import effective_box_time
from hybrid_engine.chronological_engine_study import corpus, _metrics, _record
from hybrid_engine.data import STRICT, Abstain, available_at, feature_cut, local_path, regulation
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.distributions import Budget
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS


def at(cohort, cutoff):
    eligible = []
    for versions in cohort:
        past = [r for r in versions if r['fixture_start_utc'] < available_at(r,STRICT) <= cutoff
                and regulation(r) is not None]
        if not past:
            continue
        exact = max(past, key=lambda r:(available_at(r,STRICT),r['source_catalog_sha256']))
        boxes = [b for r in versions for b in r.get('box_versions',())
                 if b['regulation_eligible'] and effective_box_time(b) <= cutoff]
        if boxes:
            exact = exact.copy()
            exact['box'] = max(boxes, key=effective_box_time)
        eligible.append(exact)
    return eligible


def replay(cohort):
    first, dynamic, failed = [], [], Counter()
    models = {}
    checked = 0
    for versions in cohort:
        truth = max(versions, key=lambda r:(r['ingested_at_utc'],r['source_catalog_sha256']))
        if not truth.get('periods') or regulation(truth) is None:
            continue
        checked += 1
        tip = truth['fixture_start_utc']
        origin = tip-PREMATCH_MINIMUM_LEAD_SECONDS-1
        day = (origin+10800)//86400
        cutoff = day*86400-10800
        try:
            if day not in models:
                history = at(cohort,cutoff)
                try:
                    if len(history)<30:
                        raise Abstain('WALKFORWARD_THIRTY_ASOF_RESULTS_REQUIRED')
                    fitted = nba_dynamic.fit([[row] for row in history],cutoff_utc=cutoff)
                    frozen = HierarchicalStrength().fit(history,cutoff_utc=cutoff,mode=STRICT)
                    models[day] = (fitted,frozen,history)
                except Abstain as exc:
                    models[day] = exc
            prepared = models[day]
            if isinstance(prepared,Abstain):
                raise prepared
            fitted,frozen,history = prepared
            cut = feature_cut([[r] for r in history],truth,mode=STRICT)
            v3 = nba_dynamic.historical_replay(fitted,cut.target,origin_utc=origin)
            v1 = frozen.predict(cut, method='RQMC_HALTON', budget=Budget(seconds=5), bounded_workspace=True)
        except Abstain as exc:
            failed[str(exc)] += 1
            continue
        line = round(v1.scores.sum())+.5
        first.append(_record(v1,cut,truth,'TEST',line,0,frozen.training_ids))
        dynamic.append(_record(v3,cut,truth,'TEST',line,0,fitted['payload']['training_ids']))
    return dict(format='STRICT_PAIRED_DYNAMIC_WALKFORWARD_V1',eligible_final_targets=checked,
                abstentions=dict(failed),matched=len(dynamic),
                v1_kernel=_metrics(first),v3=_metrics(dynamic),prospective_publications=0,
                market_fixture_count=0,
                average_v3_pace=mean(r['prediction']['metadata']['box_pace'] for r in dynamic) if dynamic else None)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts-directory',type=Path,required=True)
    parser.add_argument('--year',type=int,required=True)
    options=parser.parse_args()
    files=sorted(local_path(options.receipts_directory).glob('*.json'))
    native=[json.loads(p.read_text()) for p in files if p.name!='capture-summary.json']
    cohort,rejections=corpus(native,year=options.year)
    print(json.dumps(dict(replay(cohort), source_sha256=[digest(r) for r in native],box_rejections=rejections)))


if __name__=='__main__':
    main()
