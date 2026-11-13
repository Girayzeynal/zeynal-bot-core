"""Offline release research: source audit and isolated prospective quote observations.

No network, Telegram messages, production databases, model promotion or deployment.
Historical availability and local receipt clocks are preserved by the data loader.
"""
import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

from core.team_identity import digest
from hybrid_engine.archive_sources import pinned
from hybrid_engine.audit import source_audit
from hybrid_engine.availability import effective_box_time
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT,Abstain,available_at,feature_cut,load_manifest,local_path
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.observed_markets import observe_espn,evaluate_observation
from hybrid_engine.possession import PossessionModel


def dataset_audit(manifest_path):
    cohort,provenance=load_manifest(manifest_path)
    report=source_audit(cohort,provenance)
    report['manifest_sha256']=provenance['manifest_sha256']
    report['production_default']='FAZ13';report['production_changed']=False
    return report


def model_identity(forecast,code_version):
    """Model identity is stable across fixtures; input digests are a separate trace."""
    metadata=forecast.metadata or {}
    return digest(dict(version=forecast.model,code=code_version,scope='REGULATION_ONLY',
        artifact=metadata.get('artifact_digest'),parameters={k:metadata[k] for k in
            ('method','scenarios','seed','score_formula','quarter_probabilities') if k in metadata}))


def prospective_quotes(manifest_path,receipt_manifest,output_directory):
    cohort,provenance=load_manifest(manifest_path)
    index=json.loads(local_path(receipt_manifest).read_text())
    if index['format']!='OBSERVED_MARKET_INPUTS_V1':raise ValueError('MARKET_INPUT_MANIFEST_REQUIRED')
    if len(index['files'])>8:raise ValueError('BOUNDED_QUOTE_CAPTURE_REQUIRED')
    root=local_path(output_directory);root.mkdir(parents=True,exist_ok=True)
    observations=[];rejected=[];source_pins=[]
    for file in index['files']:
        receipt=json.loads(pinned(file));result=observe_espn(receipt,now_utc=int(time.time()))
        observations.extend(result['quotes']);rejected.extend(result['rejected'])
        source_pins.append(dict(file_sha256=file['sha256'],source_url=receipt['source_url'],
            observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc']))
    by_fixture={}
    for q in observations:by_fixture.setdefault(q['payload']['fixture_id'],[]).append(q)
    files=[Path(__file__),Path(__file__).with_name('models.py'),Path(__file__).with_name('evaluation.py'),
        Path(__file__).with_name('possession.py'),Path(__file__).with_name('distributions.py'),
        Path(__file__).parent.parent/'prematch_monte_carlo.py']
    code_pins={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    code_version=digest(code_pins);batch_cutoff=int(time.time());bayes_models={}
    results=[];failures=[]
    for fid,quotes in by_fixture.items():
        quote=quotes[0]['payload'];freeze=batch_cutoff
        target={k:quote[k] for k in ('league','season','fixture_id','fixture_start_utc','home_team_id','away_team_id')}
        try:
            cut=feature_cut(cohort,target,mode=STRICT)
            max_data=max(available_at(r,STRICT) for r in cut.history)
            for side in ('home','away'):
                for r,b,own,other in cut.features[side]['boxes']:max_data=max(max_data,effective_box_time(b))
            max_data=max(max_data,max(q['payload']['ingested_at_utc'] for q in quotes))
            if max_data>freeze or freeze>=target['fixture_start_utc']:raise Abstain('PROSPECTIVE_INPUT_OR_FIXTURE_CLOCK')
            cut=replace(cut,cutoff_utc=freeze,inputs_digest=digest(dict(features=cut.inputs_digest,decision_cutoff=freeze,quotes=[q['sha256'] for q in quotes])))
            jobs={'FAZ13':lambda:v1_forecast(cut),'POSSESSION':lambda:PossessionModel().predict(cut,method='ANALYTIC')}
            key=(target['league'],target['season'])
            if key not in bayes_models:bayes_models[key]=HierarchicalStrength().fit(cut.history,cutoff_utc=freeze,mode=STRICT)
            bayes=bayes_models[key]
            jobs['BAYES']=lambda:bayes.predict(cut,method='RQMC_HALTON',bounded_workspace=True)
            models={}
            for name,job in jobs.items():
                try:
                    forecast=job();version=model_identity(forecast,code_version);predicted=int(time.time())
                    grid=[evaluate_observation(q,forecast,trusted_sha256=q['sha256'],model_digest=version,prediction_utc=predicted) for q in quotes]
                    models[name]=dict(model_version=forecast.model,model_digest=version,prediction=forecast.summary(),market_observations=grid)
                except Abstain as exc:models[name]=dict(status='ABSTAIN',reason=str(exc))
            created=int(time.time())
            if created>=target['fixture_start_utc']:raise Abstain('PROSPECTIVE_PUBLICATION_AFTER_TIPOFF')
            p=dict(format='ISOLATED_PROSPECTIVE_RESEARCH_V1',record_type='PROSPECTIVE_RESEARCH_NOT_TELEGRAM_PRODUCTION',
                evaluation_class='PENDING_FUTURE_RESULT',actual=None,fixture=target,models=models,
                inputs_cutoff_utc=freeze,created_at_utc=created,input_available_max_utc=max_data,
                source_manifest_sha256=provenance['manifest_sha256'],quote_sha256=[q['sha256'] for q in quotes],
                input_digest=cut.inputs_digest,source_code_pins=code_pins,telegram_delivered=False,production_record_created=False)
            path=root/('prospective-'+digest(p)+'.json');publish_json(path,p)
            results.append(dict(path=str(path),file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),payload=p))
        except Abstain as exc:failures.append(dict(fixture_id=fid,reason=str(exc)))
    return dict(format='PROSPECTIVE_QUOTE_READINESS_V1',source_pins=source_pins,observations=observations,
        source_rejections=rejected,forecasts=results,forecast_abstentions=failures,
        verified_calibration_profiles=0,verified_settlement_scope_quotes=0,
        settled_oos_market_games=0,performance_claim='NOT_EVALUABLE_PENDING_MATCH_RESULTS_AND_SETTLEMENT_SCOPE',
        production_default='FAZ13',production_changed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True)
    p.add_argument('--quote-receipts');p.add_argument('--output-directory',required=True);args=p.parse_args()
    root=local_path(args.output_directory);root.mkdir(parents=True,exist_ok=True)
    report=dict(source_audit=dataset_audit(args.manifest))
    if args.quote_receipts:report['prospective_quotes']=prospective_quotes(args.manifest,args.quote_receipts,root/'prospective')
    path=root/('preparation-'+digest(report)+'.json');publish_json(path,report)
    print(json.dumps(dict(path=str(path),production_changed=False)))


if __name__=='__main__':main()
