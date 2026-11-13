"""Observation-only checkpoints and an explicitly offline, versioned shadow candidate."""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.evaluation import probability_metrics

PLAN_DEFAULTS=dict(format='CALIBRATION_REVIEW_PLAN_V1',candidate_version='SHADOW_DIRICHLET_RELIABILITY_V1',
    checkpoints=[100,250,500],minimum_past_fit=100,minimum_oos_audit=100,minimum_day_clusters=8,
    evaluation_block=25,dirichlet_prior_per_class=1.,probability_bins=10,
    minimum_brier_advantage=.01,maximum_log_loss_difference=0.,family_size=66,
    bootstrap_iterations=100000,seed=20261113,brier_drift_delta=.05,
    automatic_refit=False,automatic_promotion=False)


@dataclass(frozen=True)
class CalibrationPlan:
    payload:dict
    sha256:str

    @classmethod
    def register(cls,*,registered_at_utc=None):
        now=int(time.time());stamp=now if registered_at_utc is None else registered_at_utc
        if type(stamp) is not int or stamp!=now or stamp<=0:raise ValueError('ACTUAL_PLAN_REGISTRATION_CLOCK_REQUIRED')
        p=dict(PLAN_DEFAULTS,registered_at_utc=stamp,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        return cls(p,digest(p))

    def validate(self):
        if digest(self.payload)!=self.sha256 or any(self.payload.get(k)!=v for k,v in PLAN_DEFAULTS.items()):
            raise ValueError('PREDECLARED_PLAN_POLICY_MUTATED')
        if type(self.payload.get('registered_at_utc')) is not int or not 0<self.payload['registered_at_utc']<=int(time.time()):
            raise ValueError('PLAN_REGISTRATION_CLOCK_INVALID')
        if self.payload.get('implementation_sha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise ValueError('PREDECLARED_CALIBRATION_IMPLEMENTATION_CHANGED')


def read_or_register_plan(directory):
    import json
    from hybrid_engine.data import local_path
    from hybrid_engine.boxes import publish_json
    root=local_path(directory);root.mkdir(parents=True,exist_ok=True);files=list(root.glob('plan-*.json'))
    if len(files)>1:raise ValueError('MULTIPLE_CALIBRATION_PLANS_REQUIRE_EXPLICIT_REVIEW')
    if files:
        d=json.loads(files[0].read_text());plan=CalibrationPlan(d['payload'],d['sha256'])
        if files[0].stem!='plan-'+plan.sha256:raise ValueError('PLAN_FILE_PIN')
        plan.validate();return plan
    plan=CalibrationPlan.register();publish_json(root/('plan-'+plan.sha256+'.json'),dict(payload=plan.payload,sha256=plan.sha256))
    return plan


def cohort_key(r):
    line=0. if r['market']=='WINNER' else r['line']
    if isinstance(line,bool) or not isinstance(line,(int,float)) or not math.isfinite(line):raise ValueError('EXACT_CALIBRATION_LINE_REQUIRED')
    return (r['league'],r['model_version'],r['period'],r['market'],r['settlement_scope'],float(line),r.get('bookmaker_id',''))


def eligible_records(records,*,asof_utc):
    first={}
    for r in records:
        p=np.asarray(r['probabilities'],dtype=float)
        if (p.shape!=(3,) or not np.isfinite(p).all() or np.any(p<0) or np.any(p>1) or abs(p.sum()-1)>1e-8 or
            type(r['outcome']) is not int or r['outcome'] not in (0,1,2)):
            raise ValueError('VALID_RAW_THREE_CLASS_OBSERVATION_REQUIRED')
        if (any(type(r[k]) is not int for k in ('inputs_available_max_utc','prediction_utc','tipoff_utc','label_available_utc','model_fit_cutoff_utc')) or
            not 0<r['inputs_available_max_utc']<=r['prediction_utc']<r['tipoff_utc']<r['label_available_utc']<=asof_utc or
            r['model_fit_cutoff_utc']>r['prediction_utc'] or r['fixture_id'] in r['model_training_ids'] or
            r['data_class'] not in ('REAL_CAPTURED_PREMATCH','SYNTHETIC_TEST')):
            raise ValueError('STRICT_PREMATCH_OOS_OBSERVATION_REQUIRED')
        key=(*cohort_key(r),r['fixture_id']);old=first.get(key)
        if old and (old['outcome']!=r['outcome'] or old['tipoff_utc']!=r['tipoff_utc']):raise ValueError('CONFLICTING_INDEPENDENT_OBSERVATION')
        # Fixed first-issued policy. Later model-digest/operational variants cannot
        # add independent forecasts or replace an inconvenient first prediction.
        if old is None or (r['prediction_utc'],r['snapshot_sha256'])<(old['prediction_utc'],old['snapshot_sha256']):first[key]=r
    return sorted(first.values(),key=lambda r:(r['prediction_utc'],r['fixture_id']))


def review_checkpoints(records,*,asof_utc,plan=None):
    plan=plan or CalibrationPlan.register();plan.validate();rows=eligible_records(records,asof_utc=asof_utc);groups={}
    for r in rows:groups.setdefault(cohort_key(r),[]).append(r)
    output=[]
    for key,items in sorted(groups.items()):
        n=len(items);reached=[v for v in plan.payload['checkpoints'] if n>=v]
        output.append(dict(cohort=list(key),independent_forecasts=n,reached_review_checkpoints=reached,
            next_checkpoint=next((v for v in plan.payload['checkpoints'] if v>n),None),
            status='REVIEW_CHECKPOINT_AVAILABLE' if reached else 'INSUFFICIENT_DATA',
            automatic_refit=False,automatic_promotion=False,confidence_index=None))
    return dict(plan_sha256=plan.sha256,groups=output,automatic_refit=False,automatic_promotion=False,
        independent_unit='FIXTURE_WITHIN_LEAGUE_MODEL_VERSION_AND_EXACT_SCOPE_NOT_SNAPSHOT_OR_LINE')


def drift_monitor(records,*,asof_utc,reference=None):
    rows=eligible_records(records,asof_utc=asof_utc)
    if not rows:return dict(status='INSUFFICIENT_DATA',n=0,alerts=[],model_update=False)
    if len({cohort_key(r) for r in rows})!=1:raise ValueError('SINGLE_DRIFT_COHORT_REQUIRED')
    raw=probability_metrics([r['probabilities'] for r in rows],[r['outcome'] for r in rows])
    result=dict(status='INSUFFICIENT_DATA' if len(rows)<100 else 'NO_VERIFIED_PRIOR_REFERENCE',n=len(rows),
        raw_brier=raw['brier'],alerts=[],model_update=False,calibration_fit=False)
    if len(rows)<100:return result
    if (not reference or reference.get('role')!='PRIOR_DISJOINT_AUDIT' or reference.get('n',0)<100 or
        reference.get('cohort')!=list(cohort_key(rows[0])) or
        reference.get('available_max_utc',asof_utc)>=min(r['prediction_utc'] for r in rows)):
        return result
    baseline=reference['brier']
    if not math.isfinite(baseline) or not 0<=baseline<=2:raise ValueError('VALID_DRIFT_REFERENCE_REQUIRED')
    result['status']='OBSERVATION_ONLY'
    if raw['brier']-baseline>PLAN_DEFAULTS['brier_drift_delta']:
        result['alerts']=['HEURISTIC_BRIER_DRIFT_REVIEW_NOT_AN_AUTOMATIC_CALIBRATION']
    return result


def paired_uncertainty(rows,plan):
    p=plan.payload;days=sorted({(r['tipoff_utc']+10800)//86400 for r in rows})
    result=dict(n=len(rows),day_clusters=len(days),unit='TSI_GAME_DAY_CLUSTER',family_size=p['family_size'],
        interval=None,status='INSUFFICIENT_DATA',cross_day_team_dependence_not_fully_corrected=True)
    if len(rows)<p['minimum_oos_audit'] or len(days)<p['minimum_day_clusters']:return result
    diffs=[]
    for r in rows:
        truth=np.eye(3)[r['outcome']];raw=np.asarray(r['raw']);candidate=np.asarray(r['candidate']);y=r['outcome']
        diffs.append([float(np.sum((candidate-truth)**2)-np.sum((raw-truth)**2)),
            -math.log(max(1e-15,candidate[y]))+math.log(max(1e-15,raw[y]))])
    differences=np.asarray(diffs);groups=[np.flatnonzero([(r['tipoff_utc']+10800)//86400==d for r in rows]) for d in days]
    rng=np.random.default_rng(p['seed']);values=[]
    totals=np.array([differences[g].sum(axis=0) for g in groups]);counts=np.array([len(g) for g in groups])
    # Stream multinomial cluster weights. This resolves the corrected tail
    # probabilities without allocating iterations × game-count arrays.
    batch=max(1,min(1024,1000000//len(groups)));remaining=p['bootstrap_iterations']
    while remaining:
        n=min(batch,remaining);weights=rng.multinomial(len(groups),np.full(len(groups),1/len(groups)),size=n)
        numerator=np.einsum('ij,jk->ik',weights,totals,optimize=False);denominator=weights@counts
        values.append(numerator/denominator[:,None]);remaining-=n
    alpha=.05/(2*p['family_size'])
    bounds=np.quantile(np.concatenate(values),[alpha/2,1-alpha/2],axis=0)
    result.update(status='EXPLORATORY_PAIRED_CLUSTER_INTERVAL',difference=differences.mean(axis=0).tolist(),
        interval={'brier':bounds[:,0].tolist(),'log_loss':bounds[:,1].tolist()},bootstrap_iterations=p['bootstrap_iterations'],
        corrected_tail_probability=alpha/2,expected_bootstrap_samples_per_corrected_tail=p['bootstrap_iterations']*alpha/2)
    return result


def shadow_walk_forward(records,plan,*,asof_utc):
    """Explicit offline call only. No live parameters, points or intervals are fitted."""
    plan.validate();p=plan.payload;rows=eligible_records(records,asof_utc=asof_utc);groups={}
    for row in rows:groups.setdefault(cohort_key(row),[]).append(row)
    if len(groups)>p['family_size']:raise ValueError('PREDECLARED_COHORT_FAMILY_BUDGET')
    reports=[]
    for key,cohort in sorted(groups.items()):
        # A plan written after these predictions cannot claim confirmatory OOS.
        targets=[r for r in cohort if r['prediction_utc']>p['registered_at_utc']];evaluated=[];folds=[]
        for i in range(0,len(targets),p['evaluation_block']):
            block=targets[i:i+p['evaluation_block']];cut=min(r['prediction_utc'] for r in block)
            target_ids={r['fixture_id'] for r in block}
            past=[r for r in cohort if r['label_available_utc']<cut and r['fixture_id'] not in target_ids]
            if len(past)<p['minimum_past_fit']:continue
            bins={}
            for r in past:
                raw=r['probabilities'];cell=(int(np.argmax(raw)),min(9,int(max(raw)*10)))
                bins.setdefault(cell,[]).append(r)
            predictions=[]
            for r in block:
                raw=r['probabilities'];cell=(int(np.argmax(raw)),min(9,int(max(raw)*10)));fit=bins.get(cell,[])
                if len(fit)<30:continue
                counts=np.bincount([v['outcome'] for v in fit],minlength=3)+p['dirichlet_prior_per_class']
                candidate=(counts/counts.sum()).tolist()
                item=dict(fixture_id=r['fixture_id'],snapshot_sha256=r['snapshot_sha256'],tipoff_utc=r['tipoff_utc'],
                    prediction_utc=r['prediction_utc'],raw=raw,candidate=candidate,outcome=r['outcome'],
                    fit_ids=sorted(v['fixture_id'] for v in fit),fit_available_max_utc=max(v['label_available_utc'] for v in fit))
                evaluated.append(item);predictions.append(r['fixture_id'])
            folds.append(dict(cutoff_utc=cut,fit_count=len(past),evaluation_ids=predictions,fit_digest=digest(past)))
        uncertainty=paired_uncertainty(evaluated,plan)
        advantages=uncertainty['interval']
        thresholds_met=bool(advantages and uncertainty['difference'][0]<=-p['minimum_brier_advantage'] and
            advantages['brier'][1]<0 and advantages['log_loss'][1]<=p['maximum_log_loss_difference'])
        reports.append(dict(cohort=list(key),observed_count=len(cohort),post_plan_target_count=len(targets),
            evaluated_count=len(evaluated),folds=folds,evaluations=evaluated,uncertainty=uncertainty,
            predeclared_thresholds_met=thresholds_met,
            real_data_only=all(r['data_class']=='REAL_CAPTURED_PREMATCH' for r in cohort),
            eligible_for_explicit_user_review=thresholds_met and all(r['data_class']=='REAL_CAPTURED_PREMATCH' for r in cohort)))
    return dict(format='OFFLINE_SHADOW_CALIBRATION_REPORT_V1',candidate_version=p['candidate_version'],plan_sha256=plan.sha256,
        registration_attestation='LOCAL_APPEND_ONLY_PLAN_NOT_INDEPENDENT_PUBLIC_PREREGISTRATION',
        groups=reports,automatic_model_update=False,score_and_interval_models_changed=False,
        deployment_decision='NO_GO_EXPLICIT_RELEASE_APPROVAL_REQUIRED',explicit_approval_present=False,
        candidate_sha256=digest(dict(plan=plan.sha256,reports=reports)))
