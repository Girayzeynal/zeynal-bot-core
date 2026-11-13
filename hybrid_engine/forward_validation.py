"""Bounded prospective research capture and append-only official result matching.

Offline CLI only. The existing frozen Bayesian coefficients are reused unchanged;
Faz13/possession methods are reused as components, never presented as an ensemble.
"""
import argparse
from dataclasses import asdict,replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT,Cut,Abstain,available_at,feature_cut,local_path
from hybrid_engine.euroleague_error_audit import error_cells
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.frozen_archive import FrozenArchive,read_gzip
from hybrid_engine.intervals import prediction_intervals,assert_frozen_sampler_sources
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.possession import PossessionModel
from hybrid_engine.prospective_results import OFFICIAL
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog


def verified_catalog(receipt):
    now=int(time.time())
    if (receipt.get('provider')!='EUROLEAGUE_LIVE' or receipt.get('source_url')!=OFFICIAL or
        receipt.get('status')!='DOCUMENT_RECEIVED' or receipt.get('http_status')!=200 or
        digest(receipt['document'])!=receipt['document_sha256'] or
        any(type(receipt.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
        not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now or now-receipt['ingested_at_utc']>300):
        raise ValueError('FRESH_OFFICIAL_FORWARD_SOURCE_REQUIRED')
    return archive_catalog(receipt['document'],provider='EUROLEAGUE_LIVE',season_start_year=2026,
        observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'])


class ForwardRegistry:
    def __init__(self,directory):
        self.root=local_path(directory);self.root.mkdir(parents=True,exist_ok=True)
    def asset(self,prefix,payload):
        name=prefix+'-'+digest(payload)+'.json';publish_json(self.root/name,payload)
        return dict(file=name,sha256=digest(payload))
    def read_asset(self,ref):
        if Path(ref['file']).name!=ref['file']:raise ValueError('FORWARD_ASSET_PATH')
        p=json.loads(local_path(self.root/ref['file']).read_text())
        if digest(p)!=ref['sha256']:raise ValueError('FORWARD_ASSET_PIN')
        return p
    def publication(self,path):
        w=json.loads(path.read_text());p=w['payload']
        if digest(p)!=w['sha256']:raise ValueError('FORWARD_PUBLICATION_PIN')
        return p
    def record(self,payload):
        key=digest(dict(fixture=payload['fixture']['canonical_id'],version=payload['version']))
        slot=self.root/('first-'+key+'.json')
        if slot.exists():
            old=self.publication(slot);p=self.read_asset(old['forecast']);return p,False
        p=dict(payload);now=int(time.time());tip=p['fixture']['start_ts_utc']
        if not 0<p['source_available_max_utc']<=p['prediction_generated_at_utc']<=now<tip:raise ValueError('FORWARD_PRETIPOFF_CLOCK')
        if p['actual'] is not None:raise ValueError('FORWARD_TARGET_LABEL_FORBIDDEN')
        p['snapshot_created_at_utc']=now
        for ref in p['assets']:self.read_asset(ref)
        ref=self.asset('forecast',p);published=int(time.time())
        publication=dict(forecast=ref,first_archived_at_utc=published,
            eligible_for_prospective_audit=published<tip,classification='PREMATCH' if published<tip else 'LATE_COMMIT_EXCLUDED')
        try:publish_json(slot,dict(payload=publication,sha256=digest(publication)))
        except ValueError:
            prior=self.publication(slot);return self.read_asset(prior['forecast']),False
        return p,True
    def records(self):
        rows=[]
        for slot in sorted(self.root.glob('first-*.json')):
            publication=self.publication(slot);p=self.read_asset(publication['forecast'])
            key=digest(dict(fixture=p['fixture']['canonical_id'],version=p['version']))
            if slot.stem!='first-'+key:raise ValueError('FORWARD_FIRST_IDENTITY_PIN')
            if publication['eligible_for_prospective_audit'] and not p['prediction_generated_at_utc']<=p['snapshot_created_at_utc']<=publication['first_archived_at_utc']<p['fixture']['start_ts_utc']:
                raise ValueError('FORWARD_PUBLICATION_CLOCK')
            for ref in p['assets']:self.read_asset(ref)
            rows.append(dict(payload=p,publication=publication))
        return rows
    def settle(self,receipt):
        catalog=verified_catalog(receipt);games={g['canonical_id']:g for g in catalog['payload']['fixtures']};rows=[]
        for item in self.records():
            p=item['payload'];g=games.get(p['fixture']['canonical_id']);fid=p['fixture']['canonical_id']
            if g is None or not g['completed'] or not g['periods']:
                rows.append(dict(fixture_id=fid,status='PENDING_FINAL'));continue
            if (any(g[k]!=p['fixture'][k] for k in ('home_team_id','away_team_id','start_ts_utc')) or
                not set(g['provider_fixture_ids'])&set(p['fixture']['provider_fixture_ids']) or receipt['observed_at_utc']<=g['start_ts_utc']):
                raise ValueError('FORWARD_RESULT_IDENTITY_OR_CLOCK')
            existing=list(self.root.glob('outcome-'+fid+'-*.json'))
            for path in existing:
                old=json.loads(path.read_text());body=old['payload']
                if digest(body)!=old['sha256']:raise ValueError('FORWARD_OUTCOME_PIN')
                self.read_asset(body['source'])
                if body['periods']!=g['periods'] or body['full_final']!=g['final_scores']:raise ValueError('FORWARD_RESULT_CORRECTION_REQUIRES_REVIEW')
            if existing:rows.append(dict(fixture_id=fid,status='ALREADY_VERIFIED'));continue
            body=dict(fixture_id=fid,forecast_sha256=digest(p),periods=g['periods'],full_final=g['final_scores'],
                source=self.asset('source',receipt),recorded_at_utc=int(time.time()),
                eligible=item['publication']['eligible_for_prospective_audit'],
                component_errors={n:error_cells(m['prediction'],g['periods']) for n,m in p['components'].items() if m['status']=='FORECAST_CREATED'},
                calibration_fit=False,confidence_status='UNCALIBRATED')
            self.asset('comparison',body)
            publish_json(self.root/('outcome-'+fid+'-'+digest(body)+'.json'),dict(payload=body,sha256=digest(body)))
            rows.append(dict(fixture_id=fid,status='VERIFIED_FINAL_APPENDED'))
        return rows


def frozen_model(archive):
    record=next(iter(archive.records.values()));assert_frozen_sampler_sources(record)
    pin=record['models']['BAYES_QMC']['prediction']['metadata']['artifact_digest']
    a=json.loads((archive.path/('bayes-'+pin+'.json')).read_text())
    if digest(a)!=pin:raise ValueError('FROZEN_PREPARED_MODEL_PIN')
    model=HierarchicalStrength();model.identity=tuple(a['identity']);model.mode=a['mode'];model.cutoff=a['cutoff_utc']
    model.teams=a['teams'];model.team_index={t:i for i,t in enumerate(a['teams'])};model.players=[];model.player_index={}
    model.duration=40;model.coefficients=np.array(a['coefficients']);model.covariance=np.array(a['covariance'])
    model.noise_variance=a['noise_variance'];model.training_ids=a['training_ids'];model.artifact_digest=pin;model.fitted=True
    return model,a


def capture(archive,registry,receipt,*,fetcher=fetch_document,maximum=3):
    catalog=verified_catalog(receipt);now=int(time.time());cohort=historical_rows([(catalog,catalog['sha256'])]);model,artifact=frozen_model(archive)
    # Restrict inputs to what is available NOW, not merely before a future tipoff.
    cohort=[[r for r in versions if available_at(r,STRICT)<=now and r['fixture_start_utc']<now] for versions in cohort]
    games=sorted([g for g in catalog['payload']['fixtures'] if not g['completed'] and now+1800<g['start_ts_utc']<now+86400],key=lambda g:g['start_ts_utc'])[:maximum]
    output=[];source=registry.asset('source',receipt);prepared=registry.asset('prepared',artifact)
    code=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for g in games:
        try:
            if g['canonical_id'] in model.training_ids:raise ValueError('FORWARD_TARGET_IN_TRAINING')
            target=dict(league='EuroLeague',season='2026/2027',fixture_id=g['canonical_id'],fixture_start_utc=g['start_ts_utc'],home_team_id=g['home_team_id'],away_team_id=g['away_team_id'])
            cut=replace(feature_cut(cohort,target,mode=STRICT),cutoff_utc=now)
            versions={};jobs=dict(BAYES_QMC=lambda:model.predict(cut,method='RQMC_HALTON',bounded_workspace=True),FAZ13_MC=lambda:v1_forecast(cut),
                POSSESSION_ANALYTIC=lambda:PossessionModel().predict(cut,method='ANALYTIC'),POSSESSION_MC=lambda:PossessionModel().predict(cut,method='MC'))
            for name,job in jobs.items():
                try:
                    f=job();versions[name]=dict(status='FORECAST_CREATED',prediction=f.summary(),intervals=prediction_intervals(f))
                except Abstain as exc:versions[name]=dict(status='ABSTAIN',reason=str(exc))
            simulated=int(time.time());checked=fetcher('EUROLEAGUE_LIVE',OFFICIAL);latest=verified_catalog(checked)
            matches=[x for x in latest['payload']['fixtures'] if x['canonical_id']==g['canonical_id']]
            if len(matches)!=1 or matches[0]!=g:raise ValueError('FORWARD_FIXTURE_CHANGED_DURING_CAPTURE')
            generated=int(time.time());data_clock=max(receipt['ingested_at_utc'],checked['ingested_at_utc'],max(available_at(r,STRICT) for r in cut.history))
            assets=[source,prepared,registry.asset('cut',asdict(cut)),registry.asset('recheck',checked)]
            p,new=registry.record(dict(format='FORWARD_COMPONENT_FORECAST_V1',fixture=g,actual=None,
                version='FROZEN_COMPONENTS_FORWARD_V1:'+digest(dict(artifact=model.artifact_digest,code=code)),
                prediction_generated_at_utc=generated,source_available_max_utc=data_clock,feature_cutoff_utc=now,simulation_completed_at_utc=simulated,
                components=versions,assets=assets,parameters_updated=False,training_in_request=False,
                ensemble=dict(status='NOT_TRAINED',weights=None),market_status='MARKET_UNAVAILABLE',calibration_status='UNCALIBRATED'))
            output.append(dict(fixture_id=g['canonical_id'],status='CAPTURED' if new else 'REUSED',forecast_sha256=digest(p)))
        except (ValueError,OSError) as exc:output.append(dict(fixture_id=g['canonical_id'],status='ABSTAIN',reason=str(exc)))
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True);p.add_argument('--archive-directory')
    p.add_argument('--capture',action='store_true');a=p.parse_args();registry=ForwardRegistry(a.directory)
    receipt=fetch_document('EUROLEAGUE_LIVE',OFFICIAL)
    result=capture(FrozenArchive(a.archive_directory),registry,receipt) if a.capture else registry.settle(receipt)
    print(json.dumps(result))


if __name__=='__main__':main()
