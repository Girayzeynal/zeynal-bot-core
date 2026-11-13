"""Append native NBA outcomes and audit immutable forecasts without hindsight tuning."""
import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tarfile
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.calibration_guard import CalibrationPlan,review_checkpoints,drift_monitor,shadow_walk_forward,read_or_register_plan,cohort_key
from hybrid_engine.data import Cut,local_path
from hybrid_engine.decision_layer import QuoteEvidence,DecisionDistribution,evaluate_quote,settled_value
from hybrid_engine.evaluation import summarize
from hybrid_engine.frozen_archive import read_gzip
from hybrid_engine.intervals import prediction_intervals,empirical_coverage
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.observed_markets import observe_espn
from hybrid_engine.statistics import calibration_curve
from projection_integrity import assert_projection
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog

NBA_INDEX='b59c2c465800bbddd0a1c133ada2150500ec9b7390ef9bd5a82d012fd0d4255b'


def read_snapshots(directory,*,trusted_index=NBA_INDEX):
    root=local_path(directory);wrapper=json.loads((root/('index-'+trusted_index+'.json')).read_text());index=wrapper['payload']
    if digest(index)!=trusted_index or wrapper['sha256']!=trusted_index:raise ValueError('PROSPECTIVE_INDEX_PIN')
    output=[]
    for entry in index['records']:
        path=local_path(root/entry['file']);raw=path.read_bytes();w=json.loads(raw);p=w['payload']
        if hashlib.sha256(raw).hexdigest()!=entry['file_sha256'] or digest(p)!=entry['sha256'] or w['sha256']!=entry['sha256']:
            raise ValueError('PROSPECTIVE_SNAPSHOT_PIN')
        if p['actual'] is not None or not p['prediction_generated_at_utc']<=p['created_at_utc']<p['fixture_start_utc']:
            raise ValueError('PREMATCH_RECORD_CLOCK_OR_LABEL')
        assert_projection(p['prediction'])
        output.append(dict(snapshot=p,snapshot_sha256=w['sha256'],variant=entry['variant']))
    return output


def independent_snapshots(records):
    chosen={};variants=defaultdict(list)
    for record in records:
        p=record['snapshot'];key=(p['league'],p['season'],p['fixture_id'],p['model_version'])
        variants[key].append(record['snapshot_sha256']);old=chosen.get(key)
        if old is not None:
            other=old['snapshot']
            if p['fixture_start_utc']!=other['fixture_start_utc'] or any(p[s]['provider_id']!=other[s]['provider_id'] for s in ('home','away')):
                raise ValueError('DUPLICATE_FORECAST_IDENTITY_CONFLICT')
        if old is None or (p['created_at_utc'],record['snapshot_sha256'])<(old['snapshot']['created_at_utc'],old['snapshot_sha256']):chosen[key]=record
    return list(chosen.values()),dict(input_snapshots=len(records),independent_forecasts=len(chosen),
        duplicates_not_independent=len(records)-len(chosen),policy='FIRST_ISSUED_PER_FIXTURE_AND_MODEL_VERSION',
        variants=[dict(key=list(k),snapshot_sha256s=v) for k,v in sorted(variants.items())])


class NativeAssets:
    def __init__(self,packet):self.archive=tarfile.open(local_path(packet),'r:gz')
    def close(self):self.archive.close()
    def read(self,variant,ref):
        if Path(ref['file']).name!=ref['file']:raise ValueError('ASSET_PATH_REFUSED')
        prefix='live-nba' if variant=='initial_before_memory_fix' else 'live-nba-optimized'
        member=self.archive.getmember(prefix+'/assets/'+ref['file'])
        if not member.isfile() or member.size>5*1024*1024:raise ValueError('BOUNDED_REGULAR_ASSET_REQUIRED')
        d=json.loads(self.archive.extractfile(member).read())
        if digest(d)!=ref['sha256']:raise ValueError('NATIVE_ASSET_PIN')
        return d


def trace_for(p):
    return dict(league=p['league'],season=p['season'],fixture_id=p['fixture_id'],home_team_id=p['home']['provider_id'],
        away_team_id=p['away']['provider_id'],tipoff_utc=p['fixture_start_utc'],model_version=p['model_version'],model_digest=p['model_digest'],
        prediction_utc=p['prediction_generated_at_utc'],inputs_available_max_utc=max(c['ingested_at_utc'] for c in p['input_clocks']))


def replay_snapshot(record,assets):
    """Replay exact saved features/parameters, including the pre-memory-fix implementation.

    Operational loader code need not be re-executed; the unchanged math sources,
    parameter/input pins, pre-forecast clocks and original sample hash all must match.
    """
    p=record['snapshot'];v=record['variant'];prepared=assets.read(v,p['prepared_asset']);meta=prepared['payload'];a=meta['model']
    if digest(meta)!=prepared['sha256'] or prepared['sha256']!=p['prepared_artifact_sha256'] or digest(a)!=meta['model_sha256']:
        raise ValueError('FROZEN_PARAMETER_PIN')
    root=Path(__file__).parent
    for name in ('models.py','distributions.py','data.py'):
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=meta['source_code_pins'][name]:raise ValueError('FROZEN_MATH_SOURCE_CHANGED')
    cut=Cut(**assets.read(v,p['input_asset']))
    if (cut.target['fixture_id']!=p['fixture_id'] or not a['training_available_max']<=a['cutoff_utc']<=cut.cutoff_utc<=p['prediction_generated_at_utc'] or
        p['fixture_id'] in a['training_ids'] or any(max(r['observed_at_utc'],r['ingested_at_utc'])>cut.cutoff_utc for r in cut.history)):
        raise ValueError('FROZEN_INPUT_OR_PARAMETER_CLOCK')
    m=HierarchicalStrength();m.identity=tuple(a['identity']);m.mode=a['mode'];m.cutoff=a['cutoff_utc'];m.duration=48
    m.teams=a['teams'];m.team_index={t:i for i,t in enumerate(m.teams)};m.players=a['players'];m.player_index={t:i for i,t in enumerate(m.players)}
    m.coefficients=np.array(a['coefficients']);m.covariance=np.array(a['covariance']);m.noise_variance=a['noise_variance']
    m.training_ids=a['training_ids'];m.artifact_digest=meta['model_sha256'];m.fitted=True
    f=m.predict(cut,method='RQMC_HALTON',bounded_workspace=True);bands=prediction_intervals(f)
    if bands['sample_sha256']!=p['intervals']['sample_sha256'] or not np.allclose(f.summary()['quarters'],p['prediction']['quarters'],rtol=1e-12,atol=1e-10):
        raise ValueError('FROZEN_NUMERIC_OR_SAMPLE_REGRESSION')
    return DecisionDistribution(f,trace_for(p)),a['training_ids']


def quotes_from_assets(record,assets):
    p=record['snapshot'];quotes={};rejected=[]
    for ref in p['source_assets']:
        r=assets.read(record['variant'],ref)
        if '/scoreboard?' not in r['source_url']:continue
        if r['ingested_at_utc']>p['prediction_generated_at_utc']:raise ValueError('POST_FORECAST_MARKET_RECEIPT_REFUSED')
        found=observe_espn(r,now_utc=p['prediction_generated_at_utc'])
        rejected.extend(found['rejected'])
        for item in found['quotes']:
            if item['payload']['fixture_id']!=p['fixture_id']:continue
            q=QuoteEvidence.from_espn(item,trusted_sha256=item['sha256']);quotes[q.sha256]=q
    return sorted(quotes.values(),key=lambda q:q.sha256),rejected


def native_final(receipt,snapshot):
    p=snapshot;pid=p['provider_fixture_ids'][0]
    expected='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+pid
    if (receipt.get('provider')!='ESPN' or receipt.get('source_url')!=expected or receipt.get('status')!='DOCUMENT_RECEIVED' or
        receipt.get('http_status')!=200 or digest(receipt['document'])!=receipt.get('document_sha256') or
        not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=int(time.time())):raise ValueError('FINAL_NATIVE_SOURCE_BINDING')
    h=deepcopy(receipt['document']['header']);c=h['competitions'][0]
    if h['id']!=pid or c['id']!=pid:raise ValueError('FINAL_NATIVE_FIXTURE_ID')
    h['date']=c['date']
    for team in c['competitors']:
        for part in team.get('linescores',[]):
            if 'value' not in part:
                text=part.get('displayValue')
                if type(text) is not str or not text.isascii() or not text.isdigit():raise ValueError('FINAL_NATIVE_PERIOD_VALUE')
                part['value']=int(text)
    bundle=archive_catalog({'events':[h]},provider='ESPN',season_start_year=int(p['season'].split('/')[0]),
        observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'])
    g=bundle['payload']['fixtures'][0]
    if g['canonical_id']!=p['fixture_id'] or g['start_ts_utc']!=p['fixture_start_utc'] or any(g[s+'_team_id']!=p[s]['provider_id'] for s in ('home','away')):
        raise ValueError('FINAL_NATIVE_IDENTITY_OR_TIPOFF_CONFLICT')
    if not g['completed'] or g['periods'] is None:return None
    return dict(fixture_id=g['canonical_id'],league=p['league'],season=p['season'],tipoff_utc=g['start_ts_utc'],
        periods=g['periods'],final_with_ot=g['final_scores'],regulation=[sum(g['periods'][s][:4]) for s in ('home','away')],
        overtime_periods=len(g['periods']['home'])-4,label_available_utc=receipt['ingested_at_utc'],
        source_url=expected,source_document_sha256=receipt['document_sha256'],native_catalog_sha256=bundle['sha256'])


class FinalArchive:
    def __init__(self,directory):self.root=local_path(directory);self.root.mkdir(parents=True,exist_ok=True)
    def ingest(self,receipt,snapshot):
        source=self.root/('source-'+digest(receipt)+'.json');publish_json(source,receipt)
        final=native_final(receipt,snapshot)
        if final is None:return dict(status='PENDING_NOT_FINAL',fixture_id=snapshot['fixture_id'])
        old=self.read([snapshot]).get(snapshot['fixture_id'])
        if old:
            if any(old[k]!=final[k] for k in ('periods','final_with_ot','regulation')):raise ValueError('FINAL_CORRECTION_REQUIRES_APPEND_ONLY_REVIEW')
            return dict(status='ALREADY_VERIFIED',fixture_id=snapshot['fixture_id'])
        payload=dict(final,source_file=source.name,recorded_at_utc=int(time.time()))
        publish_json(self.root/('result-'+digest(payload)+'.json'),dict(payload=payload,sha256=digest(payload)))
        return dict(status='VERIFIED_FINAL_APPENDED',fixture_id=snapshot['fixture_id'])
    def read(self,snapshots):
        by_id={p['fixture_id']:p for p in snapshots};results={}
        for path in self.root.glob('result-*.json'):
            w=json.loads(path.read_text());p=w['payload']
            if digest(p)!=w['sha256'] or path.stem!='result-'+w['sha256']:raise ValueError('FINAL_RESULT_PIN')
            if p['fixture_id'] not in by_id:continue
            source=local_path(self.root/p['source_file'])
            if source.parent!=self.root:raise ValueError('FINAL_SOURCE_PATH')
            native=json.loads(source.read_text())
            if source.stem!='source-'+digest(native):raise ValueError('FINAL_SOURCE_FILE_PIN')
            checked=native_final(native,by_id[p['fixture_id']])
            if checked is None or any(checked[k]!=p[k] for k in checked):raise ValueError('FINAL_NATIVE_REPLAY_CONFLICT')
            if p['fixture_id'] in results:raise ValueError('DUPLICATE_FINAL_REVIEW_REQUIRED')
            results[p['fixture_id']]=p
        return results


def score_audit(records,outcomes,*,training_ids=None):
    selected,dedup=independent_snapshots(records);groups=defaultdict(list);calibration=[];per_fixture=[]
    for item in selected:
        p=item['snapshot'];o=outcomes.get(p['fixture_id'])
        if o is None:continue
        actual_q=np.array([o['periods'][s][:4] for s in ('home','away')]).T
        row=dict(fixture_id=p['fixture_id'],prediction=p['prediction'],actual=o['regulation'],actual_quarters=actual_q.tolist(),seconds=0.,markets={})
        groups[(p['league'],p['model_version'])].append((row,p,o))
        per_fixture.append(dict(fixture_id=p['fixture_id'],provider_fixture_ids=p['provider_fixture_ids'],
            snapshot_sha256=item['snapshot_sha256'],prediction=[p['prediction']['home'],p['prediction']['away']],
            regulation=o['regulation'],final_with_ot=o['final_with_ot'],overtime_periods=o['overtime_periods'],
            periods=o['periods'],source_url=o['source_url'],label_available_utc=o['label_available_utc'],
            tipoff_utc=p['fixture_start_utc'],prediction_utc=p['prediction_generated_at_utc']))
        if training_ids is not None:
            calibration.append(dict(league=p['league'],model_version=p['model_version'],period='FULL',market='WINNER',settlement_scope='REGULATION_ONLY',
                fixture_id=p['fixture_id'],snapshot_sha256=item['snapshot_sha256'],probabilities=p['prediction']['winner'],
                outcome=0 if o['regulation'][0]>o['regulation'][1] else 1 if o['regulation'][0]==o['regulation'][1] else 2,
                prediction_utc=p['prediction_generated_at_utc'],tipoff_utc=p['fixture_start_utc'],label_available_utc=o['label_available_utc'],
                inputs_available_max_utc=max(x['ingested_at_utc'] for x in p['input_clocks']),model_fit_cutoff_utc=p['parameter_fit_cutoff_utc'],
                model_training_ids=training_ids[p['fixture_id']],data_class='REAL_CAPTURED_PREMATCH'))
    reports=[]
    for (league,version),items in sorted(groups.items()):
        rows=[r for r,p,o in items];metrics=summarize(rows)
        metrics.pop('runtime_seconds',None)
        hits=sum(int(np.argmax(r['prediction']['winner']))==(0 if r['actual'][0]>r['actual'][1] else 1 if r['actual'][0]==r['actual'][1] else 2) for r in rows)
        from hybrid_engine.markets import wilson
        metrics['winner_direction']=dict(correct=hits,n=len(rows),rate=hits/len(rows),scope='REGULATION_ONLY',wilson_95=wilson(hits,len(rows)))
        metrics['winner_reliability']={side:calibration_curve([r['prediction']['winner'][i] for r in rows],
            [int((0 if r['actual'][0]>r['actual'][1] else 1 if r['actual'][0]==r['actual'][1] else 2)==i) for r in rows]) for i,side in enumerate(('home','tie','away'))}
        reports.append(dict(league=league,model_version=version,settlement_scope='REGULATION_ONLY',metrics=metrics,
            error_uncertainty=dict(day_clusters=len({(p['fixture_start_utc']+10800)//86400 for r,p,o in items}),
                status='DESCRIPTIVE_ONLY_NO_SMALL_COHORT_SUPERIORITY_CLAIM',mae_interval_95=None,brier_interval_95=None),
            interval_coverage=empirical_coverage([(p['intervals'],o['periods']) for r,p,o in items]),
            full_game_ot_probability_metrics=None,calibration_verified=False))
    return dict(format='IMMUTABLE_NBA_SCORE_AUDIT_V1',deduplication=dedup,settled_independent_forecasts=len(per_fixture),
        pending_independent_forecasts=len(selected)-len(per_fixture),groups=reports,per_fixture=per_fixture,
        calibration_records=calibration,market_direction_metrics=dict(status='NO_VERIFIED_PREGAME_SETTLEMENT_DECISIONS',n=0),
        model_parameters_changed=False,automatic_calibration=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive-directory',required=True)
    parser.add_argument('--native-packet',required=True);parser.add_argument('--output-directory',required=True)
    parser.add_argument('--fetch-finals',action='store_true');parser.add_argument('--evaluate-shadow',action='store_true')
    parser.add_argument('--plan-directory')
    args=parser.parse_args();records=read_snapshots(args.archive_directory);selected,_=independent_snapshots(records)
    root=local_path(args.output_directory);root.mkdir(parents=True,exist_ok=True);finals=FinalArchive(root/'finals')
    captures=[]
    if args.fetch_finals:
        for item in selected:
            p=item['snapshot'];url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+p['provider_fixture_ids'][0]
            captures.append(finals.ingest(fetch_document('ESPN',url),p))
    assets=NativeAssets(args.native_packet);ids={};decisions=[]
    try:
        for item in selected:
            distribution,training=replay_snapshot(item,assets);ids[item['snapshot']['fixture_id']]=training
            quotes,rejected=quotes_from_assets(item,assets)
            decisions.append(dict(snapshot_sha256=item['snapshot_sha256'],fixture_id=item['snapshot']['fixture_id'],
                all_quote_ids=[q.sha256 for q in quotes],rejected_native_quotes=rejected,
                evaluations=[evaluate_quote(distribution,q,asof_utc=int(time.time())) for q in quotes] if quotes else [evaluate_quote(distribution,asof_utc=int(time.time()))],
                recorded_at_utc=int(time.time()),mean_median_mode=distribution.describe()))
    finally:assets.close()
    outcomes=finals.read([v['snapshot'] for v in selected]);report=score_audit(records,outcomes,training_ids=ids)
    plan=read_or_register_plan(args.plan_directory or root)
    from hybrid_engine.decision_metrics import audit_markets
    report['market_direction_metrics']=audit_markets(records,decisions,outcomes)
    cohorts=defaultdict(list)
    for row in report['calibration_records']:cohorts[cohort_key(row)].append(row)
    report['drift_observations']=[dict(cohort=list(k),report=drift_monitor(rows,asof_utc=int(time.time()))) for k,rows in cohorts.items()]
    report.update(captures=captures,decisions=decisions,review=review_checkpoints(report['calibration_records'],asof_utc=int(time.time()),plan=plan),
        shadow=(shadow_walk_forward(report['calibration_records'],plan,asof_utc=int(time.time())) if args.evaluate_shadow else None),
        plan_sha256=plan.sha256,production_decision='NO_GO',real_telegram_status='BLOCKED')
    target=root/('audit-'+digest(report)+'.json');publish_json(target,dict(payload=report,sha256=digest(report)))
    print(json.dumps(dict(path=str(target),settled=report['settled_independent_forecasts'],pending=report['pending_independent_forecasts'],
        native_quotes=sum(len(d['all_quote_ids']) for d in decisions),groups=[dict(league=g['league'],metrics=g['metrics']) for g in report['groups']])))


if __name__=='__main__':main()
