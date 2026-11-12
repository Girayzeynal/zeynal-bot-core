"""Offline evidence checks and matched panels. No downloads, model tuning or deploys."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json

from hybrid_engine.audit import source_audit
from hybrid_engine.archive_sources import pinned, utc
from hybrid_engine.availability import effective_time
from hybrid_engine.data import load_manifest, local_path
from hybrid_engine.evaluation import summarize
from hybrid_engine.statistics import market_metrics


PANELS = dict(
    score_laws=('FAZ13_MC','FAZ13_QMC','FAZ13_ANALYTIC','BAYES_QMC','LEAGUE_MEAN','RECENT_POINTS_FOR'),
    learned_models=('FAZ13_MC','BAYES_QMC','LIGHTGBM','CATBOOST','ENSEMBLE','VALIDATION_SELECTED'),
    possession=('FAZ13_MC','POSSESSION_MC','POSSESSION_ANALYTIC'))


def matched_panels(rows):
    output = {}
    for panel,names in PANELS.items():
        ids=set.intersection(*({r['fixture_id'] for r in rows[n]} for n in names))
        output[panel]=dict(n=len(ids), fixture_ids=sorted(ids),
            models={n:summarize([r for r in rows[n] if r['fixture_id'] in ids]) for n in names},markets={})
        for market in ('1Q','1H','TOTAL','HOME','AWAY','HOME_HANDICAP'):
            for offset in ((-2.5,0.,2.5) if market=='1Q' else (-5.,0.,5.)):
                common=ids.copy()
                for n in names:
                    common &= {r['fixture_id'] for r in rows[n] if any(m['market']==market and m['offset']==offset and m['probabilities'] is not None for m in r['line_grid'])}
                output[panel]['markets'][market+':'+str(offset)]=dict(n=len(common),
                    models={n:market_metrics([r for r in rows[n] if r['fixture_id'] in common],market,offset) for n in names})
    return output


def verify_predictions(report):
    checked=Counter()
    for c in report['cohorts'].values():
        seen=set()
        for fold in c['folds']:
            train=set(fold['training_ids']); val=set(fold['validation_ids']); test=set(fold['test_ids'])
            if train&val or train&test or val&test or test&seen:raise ValueError('FOLD_ID_OVERLAP')
            seen |= test
            for role,cutoff in [('train',fold['validation_cutoff']),('validation',fold['test_cutoff'])]:
                if any(r['available_utc']>cutoff for r in fold['label_version_pins'][role]): raise ValueError('FIT_LABEL_AFTER_CUTOFF')
                checked['past_label_versions']+=len(fold['label_version_pins'][role])
            if fold['ensemble'] and (fold['ensemble']['fit_cutoff']!=fold['test_cutoff'] or set(fold['ensemble']['validation_ids'])-val):
                raise ValueError('ENSEMBLE_NOT_VALIDATION_ONLY')
        for name,rows in c['model_rows'].items():
            for r in rows:
                t=r['trace']
                if not t['data_time_utc']<=t['prediction_utc']<r['start_utc']:raise ValueError('PREDICTOR_CLOCK_LEAK')
                if not all(t.get(k) for k in ('model_version','model_digest','source_version','input_digest','fixture_source')):raise ValueError('INCOMPLETE_PREDICTION_TRACE')
                checked['prediction_traces']+=1
                for m in r['line_grid']:
                    if m['confidence_index'] is not None:raise ValueError('UNVERIFIED_CONFIDENCE')
                    p=m['probabilities']
                    if p is not None:
                        if set(p)!={'under','push','over'} or any(not 0<=v<=1 for v in p.values()) or abs(sum(p.values())-1)>1e-8:raise ValueError('INVALID_MARKET_MASS')
                        checked['normalized_market_lines']+=1
    return dict(status='PASS',checks=checked,meaning='MECHANICAL_AUDIT_NOT_AN_INDEPENDENT_ACCURACY_TEST')


def quote_audit(manifest,cohort):
    import io
    import pandas as pd
    ids={pid for group in cohort for pid in group[0]['provider_fixture_ids'] if group[0]['league']=='NBA'}
    output=[]; seen=set()
    for file in manifest['files']:
        if file['kind']!='PUBLIC_ARCHIVE_INPUTS':continue
        for source in json.loads(pinned(file))['sources']:
            if source['kind']!='NBA_QUOTES' or source['data']['sha256'] in seen:continue
            seen.add(source['data']['sha256']); frame=pd.read_parquet(io.BytesIO(pinned(source['data'])))
            matching=frame[frame.game_id.map(lambda v:str(int(v))).isin(ids)]
            output.append(dict(file_sha256=source['data']['sha256'],rows=len(frame),matching_current_cohort=len(matching),
                commence_range_utc=[frame.commence_time.min(),frame.commence_time.max()],
                event_snapshot_range_utc=[frame.snapshot.min(),frame.snapshot.max()],
                policy='SNAPSHOT_COLUMN_IS_NOT_INDEPENDENT_PUBLICATION_PROOF;NO_CROSS_SEASON_JOIN'))
    return output


def run(manifest_path,backtest_path):
    c,p=load_manifest(manifest_path); report=json.loads(local_path(backtest_path).read_text())
    if p['manifest_sha256']!=report['provenance']['manifest_sha256']:raise ValueError('REPORT_DATASET_PIN_CONFLICT')
    # A plain JSON roundtrip strips only runtime witnesses, not retrieval clocks.
    plain_c=json.loads(json.dumps(c));plain_p=json.loads(json.dumps(p));plain_p.pop('archive_binding',None)
    before=source_audit(plain_c,plain_p)
    return dict(format='HYBRID_ZERO_SAMPLE_ROOT_CAUSE_V1',
        backtest_file_sha256=hashlib.sha256(local_path(backtest_path).read_bytes()).hexdigest(),
        retrieval_only_ablation=before,with_verified_archives=source_audit(c,p),archive_binding=p['archive_binding'],
        prediction_verification=verify_predictions(report),
        matched_panels={key:matched_panels(v['model_rows']) for key,v in report['cohorts'].items()},
        actual_quote_audit=quote_audit(json.loads(local_path(manifest_path).read_text()),c),
        limitations=['WIKI_FINAL_RECONCILIATION_CAN_SELECT_A_NONREPRESENTATIVE_SUBSET',
            'PUBLIC_ARCHIVE_EXISTENCE_IS_NOT_PRIOR_BOT_INGESTION_OR_CONTRACTUAL_DATA_PERMISSION',
            'GITHUB_AND_WIKIMEDIA_API_RECEIPTS_ARE_PINNED_NOT_CRYPTOGRAPHIC_TIMESTAMP_SIGNATURES',
            'NO_NEW_PROSPECTIVE_HOLDOUT_AFTER_THE_PREVIOUS_RESEARCH_ITERATION',
            'NO_VERIFIED_PREMATCH_ROSTER_OR_CURRENT_BOOKMAKER_QUOTES'],
        production_default='FAZ13',production_changed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True);parser.add_argument('--backtest-report',required=True)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    report=run(args.manifest,args.backtest_report)
    local_path(args.output).write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps(dict(output=args.output,verification=report['prediction_verification'])))


if __name__=='__main__':main()
