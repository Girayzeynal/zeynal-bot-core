"""Offline paired player-scoring research using the existing Bayesian hierarchy.

Never replaces the active model, edits a forecast, or fits in a Telegram request.
Individual defense/pace and uncertainty in projected minutes remain unsupported.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict,replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT,Abstain,available_at,regulation,local_path,feature_cut,load_manifest
from hybrid_engine.distributions import Budget
from hybrid_engine.evaluation import v1_forecast
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.live_metrics import metrics
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.player_inputs import validate_witness
from hybrid_engine.player_minutes import MinutesArchive,validate_minutes,stamp
from hybrid_engine.statistics import paired_cluster_interval

VERSION='NBA_PLAYER_SCORING_HIERARCHY_SHADOW_V1'


def pins():
    root=Path(__file__).parent
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
        ('player_shadow.py','player_minutes.py','models.py','distributions.py','data.py')}


def eligible_rows(cohort,publications,directory,cutoff):
    by_id={}
    for publication in publications:
        p=validate_witness(publication,directory)
        if publication['first_archived_at_utc']>cutoff: continue
        if p['fixture_id'] in by_id: raise ValueError('DUPLICATE_PLAYER_INPUT_FIXTURE')
        by_id[p['fixture_id']]=(p,publication)
    rows=[]; exposures={}; traces=[]; exclusions={}
    for versions in cohort:
        candidates=[r for r in versions if r['league']=='NBA' and regulation(r) is not None and
            r['fixture_start_utc']<available_at(r,STRICT)<=cutoff]
        if not candidates: continue
        row=max(candidates,key=lambda r:available_at(r,STRICT))
        matched=by_id.get(row['fixture_id'])
        if matched is None:
            exclusions['NO_PROSPECTIVE_MINUTES_PUBLICATION']=exclusions.get('NO_PROSPECTIVE_MINUTES_PUBLICATION',0)+1
            continue
        p,publication=matched
        validate_minutes(publication['projection'],asof_utc=cutoff,fixture=row)
        rows.append(row)
        exposures[row['fixture_id']]={k:p[k] for k in ('observed_at_utc','ingested_at_utc')}
        for side in ('home','away'):
            # Zero-only roster entries carry no identifiable player coefficient.
            exposures[row['fixture_id']][side]=[r for r in p[side] if r['expected_minutes']>0]
        traces.append(dict(fixture_id=row['fixture_id'],projection_sha256=publication['projection']['sha256'],
            first_archived_at_utc=publication['first_archived_at_utc'],label_available_utc=available_at(row,STRICT)))
    return rows,exposures,traces,exclusions


def fit_pair(cohort,publications,directory,*,cutoff_utc,minimum_games=100):
    cutoff=stamp(cutoff_utc)
    if cutoff>int(time.time()) or type(minimum_games) is not int or not 30<=minimum_games<=10000:
        raise ValueError('OFFLINE_PLAYER_TRAINING_POLICY_REQUIRED')
    rows,exposures,traces,excluded=eligible_rows(cohort,publications,directory,cutoff)
    audit=dict(format='PLAYER_SHADOW_READINESS_V1',version=VERSION,eligible_games=len(rows),
        minimum_games=minimum_games,exclusions=excluded,cutoff_utc=cutoff,
        status='INSUFFICIENT_PROSPECTIVE_PLAYER_INPUTS',production_enabled=False,
        calibration_status='NOT_CALIBRATED',confidence_index=None,online_training=False)
    if len(rows)<minimum_games: return None,audit
    if len({(r['league'],r['season']) for r in rows})!=1: raise ValueError('SEPARATE_SEASON_PLAYER_FITS_REQUIRED')
    # Joint team/player fit: never subtract a player's PPG from an already
    # injury-affected team mean a second time.
    baseline=HierarchicalStrength(minimum_games=minimum_games).fit(rows,cutoff_utc=cutoff,mode=STRICT)
    candidate=HierarchicalStrength(minimum_games=minimum_games).fit(rows,cutoff_utc=cutoff,mode=STRICT,projected_exposures=exposures)
    if not candidate.players: raise Abstain('NO_IDENTIFIABLE_PLAYER_EXPOSURES')
    counts={pid:sum(any(p['player_id']==pid and p['expected_minutes']>0 for s in ('home','away') for p in e[s])
                    for e in exposures.values()) for pid in candidate.players}
    body=dict(format='PAIRED_PLAYER_BAYES_ARTIFACT_V1',version=VERSION,prepared_at_utc=int(time.time()),
        baseline=baseline.artifact(),candidate=candidate.artifact(),player_nonzero_training_games=counts,
        projection_traces=traces,source_code_pins=pins(),training_minutes_digest=digest(exposures),
        scope='OWN_TEAM_PLAYER_SCORING_EFFECT_ONLY',individual_defense_fitted=False,measured_pace_fitted=False,
        minute_uncertainty_calibrated=False,production_enabled=False,online_training=False)
    audit['status']='OFFLINE_RESEARCH_PAIR_PREPARED'
    return dict(payload=body,sha256=digest(body)),audit


def _load_hierarchy(a):
    teams=a['teams']; players=a['players']; size=2+2*len(teams)+len(players)
    if (a['format']!='BAYES_HIERARCHY_ARTIFACT_V1' or a['identity'][0]!='NBA' or a['mode']!=STRICT or
            not 1<=len(teams)<=30 or size>512 or
            len(set(teams))!=len(teams) or len(set(players))!=len(players) or len(a['training_ids'])<30 or
            len(set(a['training_ids']))!=len(a['training_ids'])):
        raise ValueError('PLAYER_ARTIFACT_SCOPE_OR_BUDGET')
    coef=np.asarray(a['coefficients'],dtype=float); cov=np.asarray(a['covariance'],dtype=float)
    if (coef.shape!=(size,) or cov.shape!=(size,size) or not np.isfinite(coef).all() or not np.isfinite(cov).all() or
            not np.allclose(cov,cov.T,rtol=0,atol=1e-8) or not 0<float(a['noise_variance'])<10000):
        raise ValueError('PLAYER_ARTIFACT_FINITE_PARAMETERS')
    try: np.linalg.cholesky(cov)
    except np.linalg.LinAlgError as exc: raise ValueError('PLAYER_ARTIFACT_POSTERIOR_NOT_POSITIVE') from exc
    model=HierarchicalStrength(); model.identity=tuple(a['identity']); model.mode=STRICT
    model.cutoff=a['cutoff_utc']; model.teams=list(teams); model.players=list(players)
    model.team_index={t:i for i,t in enumerate(teams)}; model.player_index={p:i for i,p in enumerate(players)}
    model.duration=48; model.coefficients=coef; model.covariance=cov; model.noise_variance=a['noise_variance']
    model.training_ids=list(a['training_ids']); model.artifact_digest=digest(a); model.fitted=True
    return model


class PreparedPlayerPair:
    def __init__(self,artifact,*,trusted_sha256):
        p=artifact['payload']; now=int(time.time())
        if artifact['sha256']!=trusted_sha256 or digest(p)!=trusted_sha256:
            raise ValueError('PLAYER_ARTIFACT_TRUSTED_PIN')
        if (p['format']!='PAIRED_PLAYER_BAYES_ARTIFACT_V1' or p['version']!=VERSION or p['source_code_pins']!=pins() or
                not 0<stamp(p['candidate']['training_available_max'])<=stamp(p['candidate']['cutoff_utc'])<=
                    stamp(p['prepared_at_utc'])<=now or p['production_enabled'] is not False):
            raise ValueError('PLAYER_ARTIFACT_SOURCE_CLOCK_OR_SCOPE')
        if (p['baseline']['training_ids']!=p['candidate']['training_ids'] or
                p['baseline']['identity']!=p['candidate']['identity'] or p['baseline']['cutoff_utc']!=p['candidate']['cutoff_utc'] or
                p['baseline']['players'] or not p['candidate']['players']):
            raise ValueError('PLAYER_PAIR_REQUIRES_IDENTICAL_TRAINING_GAMES')
        if not 0<stamp(p['baseline']['training_available_max'])<=stamp(p['baseline']['cutoff_utc']):
            raise ValueError('PLAYER_BASELINE_LABEL_CUTOFF')
        self.baseline=_load_hierarchy(p['baseline']); self.candidate=_load_hierarchy(p['candidate'])
        self.counts=p['player_nonzero_training_games']; self.sha256=trusted_sha256; self.artifact=deepcopy(artifact)

    def predict(self,cut,minutes,*,budget=Budget()):
        now=int(time.time()); p=validate_minutes(minutes,asof_utc=now,fixture=cut.target)
        if (cut.evaluation_class!=STRICT or cut.cutoff_utc>now or p['ingested_at_utc']>cut.cutoff_utc or
                now>=p['fixture_start_utc'] or cut.target['fixture_id'] in self.candidate.training_ids or
                any(r['fixture_id']==cut.target['fixture_id'] or available_at(r,STRICT)>cut.cutoff_utc for r in cut.history)):
            raise ValueError('PLAYER_TARGET_OR_FEATURE_CUTOFF_LEAKAGE')
        if cut.cutoff_utc-p['generated_at_utc']>3600: raise Abstain('PLAYER_MINUTE_PROJECTION_STALE_FOR_NEW_FORECAST')
        for side in ('home','away'):
            for player in p[side]:
                if player['expected_minutes']>0 and self.counts.get(player['player_id'],0)<5:
                    raise Abstain('PLAYER_EFFECT_WITHOUT_FIVE_PAST_EXPOSURES')
        baseline=self.baseline.predict(cut,budget=budget,method='RQMC_HALTON',bounded_workspace=True)
        candidate=self.candidate.predict(cut,budget=budget,method='RQMC_HALTON',projected_exposure=p,bounded_workspace=True)
        candidate.model=VERSION
        candidate.metadata.update(scope='OWN_TEAM_PLAYER_SCORING_EFFECT_ONLY',minutes_projection_sha256=minutes['sha256'],
            lineup_verified=False,minute_uncertainty_calibrated=False,individual_defense_fitted=False,
            measured_pace_fitted=False,confidence_index=None,production_enabled=False)
        return dict(TEAM_BAYES=baseline,PLAYER_BAYES=candidate,FAZ13_REFERENCE=v1_forecast(cut))


def capture_pair(pair,cut,publication,directory):
    root=local_path(directory); registry=ForwardRegistry(root/'forecasts')
    existing=[r for r in registry.records() if r['payload']['version']==pair.sha256 and
        r['payload']['fixture']['canonical_id']==cut.target['fixture_id']]
    if existing: return existing[0]['payload'],False
    p=validate_witness(publication,root)
    if publication['first_archived_at_utc']>cut.cutoff_utc:
        raise ValueError('PLAYER_MINUTES_NOT_ARCHIVED_AT_FORECAST_CUTOFF')
    components=pair.predict(cut,publication['projection'])
    generated=int(time.time()); source=max([p['source_available_max_utc'],pair.candidate.cutoff]+
        [available_at(r,STRICT) for r in cut.history])
    refs=[registry.asset('paired-model',pair.artifact),registry.asset('minutes',publication['projection']),
          registry.asset('feature-cut',asdict(cut))]
    body=dict(record_type='PAIRED_PLAYER_SHADOW_NOT_PRODUCTION',fixture=dict(canonical_id=cut.target['fixture_id'],
        start_ts_utc=cut.target['fixture_start_utc'],**cut.target),version=pair.sha256,actual=None,assets=refs,
        source_available_max_utc=source,prediction_generated_at_utc=generated,model_version=VERSION,
        original_snapshot_sha256=p['original_snapshot_sha256'],
        components={name:dict(status='FORECAST_CREATED',prediction=f.summary(),intervals=prediction_intervals(f))
                    for name,f in components.items()},calibration_status='NOT_CALIBRATED',confidence_index=None,
        production_enabled=False,online_training=False)
    return registry.record(body)


def readiness(directory):
    root=local_path(directory); folder=root/'minutes'
    publications=MinutesArchive(folder).first() if folder.is_dir() else []
    complete=[]; rejected=0
    for p in publications:
        try: validate_witness(p,root); complete.append(p)
        except (ValueError,KeyError,TypeError,OSError): rejected+=1
    prepared=list(root.glob('player-pair-*.json')) if root.is_dir() else []
    return dict(format='PLAYER_SHADOW_READINESS_V1',status='WAITING_FOR_OFFLINE_FIT' if complete else
        'BLOCKED_NO_PROSPECTIVE_PLAYER_MINUTES',prospective_minutes_games=len(complete),
        rejected_inputs=rejected,prepared_artifacts=len(prepared),minimum_fit_games=100,
        minimum_future_audit=100,minimum_day_clusters=8,production_enabled=False,
        calibration_status='NOT_CALIBRATED',confidence_index=None,default_engine_unchanged=True)


def render_status(directory):
    # Reading this optional status never trains or performs network I/O.
    root=local_path(directory); count=len(list((root/'minutes').glob('minutes-*.json'))) if (root/'minutes').is_dir() else 0
    return ('🧪 <b>KADRO ETKİLİ MODEL | AYRI ARAŞTIRMA</b>\n'
        f'Maç öncesi dakika dosyası: {count} (ayrıntılı uygunluk çevrimdışı denetlenir).\n'
        'Oyuncu etkisi aktif skor modeline uygulanmadı.\n'
        'Dakika kaydı ve geçmiş sonuçlarla çevrimdışı eğitim/ileri denetim gerekiyor.\n'
        'İlk beş, oyuncu bazlı savunma ve tempo etkisi doğrulanmadı.')


def performance(directory,ledger,*,asof_utc=None):
    """Only originally published shadow pairs and native-verified later finals."""
    from ledger_reports import LedgerReports
    from projection_integrity import assert_projection
    asof=int(time.time()) if asof_utc is None else stamp(asof_utc)
    if asof>int(time.time()): raise ValueError('NO_FUTURE_SHADOW_PERFORMANCE_CLOCK')
    root=local_path(directory); folder=root/'forecasts'
    records=ForwardRegistry(folder).records() if folder.is_dir() else []
    verified=LedgerReports(local_path(ledger)).read('NBA')
    labels={}
    for r in verified['forecasts']:
        if r['actual'] is None or r['label_available_utc']>asof: continue
        key=r['fixture_id']
        if key in labels and any(labels[key][k]!=r[k] for k in ('actual','actual_periods','fixture_start_utc')):
            raise ValueError('CONFLICTING_NATIVE_SHADOW_RESULT')
        labels[key]=r
    groups={}; pending=0; settled_ids=set()
    for entry in records:
        p=entry['payload']; publication=entry['publication']; fixture=p['fixture']
        if (p['record_type']!='PAIRED_PLAYER_SHADOW_NOT_PRODUCTION' or
                not publication['eligible_for_prospective_audit'] or publication['first_archived_at_utc']>asof): continue
        label=labels.get(fixture['canonical_id'])
        if label is None: pending+=1; continue
        if label['fixture_start_utc']!=fixture['start_ts_utc'] or label['label_available_utc']<=fixture['start_ts_utc']:
            raise ValueError('SHADOW_RESULT_CLOCK_OR_FIXTURE')
        settled_ids.add(fixture['canonical_id'])
        bucket=groups.setdefault(p['version'],{name:[] for name in ('TEAM_BAYES','PLAYER_BAYES','FAZ13_REFERENCE')})
        if set(p['components'])!=set(bucket): raise ValueError('COMPLETE_PAIRED_SHADOW_COMPONENTS_REQUIRED')
        for name,component in p['components'].items():
            q=component['prediction']; assert_projection(q)
            quarters=np.asarray(q['quarters'])
            item=dict(fixture_id=label['fixture_id'],league='NBA',season=fixture['season'],
                model_version=name,model_digest=digest(dict(pair=p['version'],component=name)),
                prediction=[q['home'],q['away']],predicted_quarters=quarters.tolist(),
                predicted_halves=[quarters[:2].sum(axis=0).tolist(),quarters[2:].sum(axis=0).tolist()],
                winner=q['winner'],intervals=component['intervals'],actual=label['actual'],actual_periods=label['actual_periods'],
                fixture_start_utc=fixture['start_ts_utc'],prediction_generated_at_utc=p['prediction_generated_at_utc'],
                label_available_utc=label['label_available_utc'])
            bucket[name].append(item)
    result=[]
    for version,models in groups.items():
        comparisons={}; rows={}
        for name,items in models.items():
            if len({r['fixture_id'] for r in items})!=len(items): raise ValueError('DUPLICATE_SHADOW_PAIRED_GAME')
            rows[name]=[dict(fixture_id=r['fixture_id'],start_utc=r['fixture_start_utc'],actual=r['actual'],
                actual_quarters=np.asarray([r['actual_periods'][s][:4] for s in ('home','away')]).T.tolist(),
                prediction=next(e['payload']['components'][name]['prediction'] for e in records if
                    e['payload']['version']==version and e['payload']['fixture']['canonical_id']==r['fixture_id'])) for r in items]
        for baseline in ('TEAM_BAYES','FAZ13_REFERENCE'):
            comparisons[baseline]=paired_cluster_interval(rows[baseline],rows['PLAYER_BAYES'],family_size=26)
        n=len(models['PLAYER_BAYES']); days=len({(r['fixture_start_utc']+10800)//86400 for r in models['PLAYER_BAYES']})
        result.append(dict(pair_version=version,n=n,day_clusters=days,
            status='INSUFFICIENT_FUTURE_AUDIT' if n<100 or days<8 else 'RESEARCH_REVIEW_REQUIRED_NO_AUTOMATIC_PROMOTION',
            metrics={name:metrics(items) for name,items in models.items()},paired_comparisons=comparisons))
    return dict(format='PLAYER_SHADOW_NATIVE_FORWARD_PERFORMANCE_V1',groups=result,pending=pending,
        n=len(settled_ids),paired_version_records=sum(g['n'] for g in result),versions_not_pooled=True,
        production_enabled=False,calibration_fit=False,confidence_index=None,
        promotion_decision='NO_GO_UNTIL_DISJOINT_ACCEPTANCE_AND_EXPLICIT_APPROVAL',original_ledger_read_only=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True); parser.add_argument('--history-manifest')
    parser.add_argument('--capture-manifest'); parser.add_argument('--fixture-id')
    parser.add_argument('--model-artifact'); parser.add_argument('--model-sha')
    parser.add_argument('--report-ledger')
    args=parser.parse_args(); root=local_path(args.directory); root.mkdir(parents=True,exist_ok=True)
    report=readiness(root)
    if args.report_ledger: report['performance']=performance(root,args.report_ledger)
    if args.history_manifest:
        cohort,_=load_manifest(args.history_manifest)
        publications=MinutesArchive(root/'minutes').first()
        artifact,audit=fit_pair(cohort,publications,root,cutoff_utc=int(time.time()))
        report['fit_audit']=audit
        if artifact: publish_json(root/('player-pair-'+artifact['sha256']+'.json'),artifact)
    if args.capture_manifest:
        if args.history_manifest or not all((args.fixture_id,args.model_artifact,args.model_sha)):
            parser.error('Capture requires fixture/model/artifact SHA and never fits a model')
        path=local_path(args.model_artifact)
        if path.stat().st_size>8*1024*1024: raise ValueError('PLAYER_MODEL_ARTIFACT_SIZE')
        pair=PreparedPlayerPair(json.loads(path.read_text()),trusted_sha256=args.model_sha)
        publications=MinutesArchive(root/'minutes').first()
        matches=[p for p in publications if p['projection']['payload']['fixture_id']==args.fixture_id]
        if len(matches)!=1: raise ValueError('EXACT_PROSPECTIVE_MINUTES_REQUIRED')
        publication=matches[0]; target={k:publication['projection']['payload'][k] for k in
            ('league','season','fixture_id','fixture_start_utc','home_team_id','away_team_id')}
        now=int(time.time()); cohort,_=load_manifest(args.capture_manifest)
        cohort=[[r for r in versions if available_at(r,STRICT)<=now] for versions in cohort]
        cohort=[v for v in cohort if v]
        cut=replace(feature_cut(cohort,target,mode=STRICT),cutoff_utc=now)
        forecast,created=capture_pair(pair,cut,publication,root)
        report['capture']=dict(new_record=created,pair_version=forecast['version'],fixture_id=target['fixture_id'])
    path=root/('readiness-'+digest(report)+'.json'); publish_json(path,dict(payload=report,sha256=digest(report)))
    print(json.dumps(dict(report,path=str(path)),sort_keys=True))


if __name__=='__main__': main()
