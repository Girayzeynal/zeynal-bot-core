"""Read-only source/PIT readiness and walk-forward research diagnostics.

No downloads, fitting, reference coefficient changes or prediction-ledger writes.
Score inputs are externally pinned; support/roster sidecars remain separate.
"""
from copy import deepcopy
import json
from pathlib import Path
import time

from prediction_inputs import digest
from faz40_archive import require
from faz40_archive_audit import file_sha
from faz41_evidence import REGISTRY,REGISTRY_PIN
from faz41_faz40 import research_with_context
from faz42_history import _validated,inventory,evaluate
from faz42_snapshot import model_manifest,verify_execution_manifest
from faz44_inputs import read_development_inputs,publish_development_artifact
from faz45_collection import read_support_bundle
from faz45_support import support_report,validate_support
from faz46_collection import read_audit
from faz47_history_binding import materialize_research_archive

FORMAT='FAZ47_RESEARCH_READINESS_V1'


def readiness_report(scores,*,support=None,roster_observations=None,asof_utc=None,minimum_team_games=5,minimum_evaluation_games=30,
                     simulations=10000,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    at=int(time.time()) if asof_utc is None else asof_utc
    require(type(minimum_team_games) is int and 2<=minimum_team_games<=30 and type(minimum_evaluation_games) is int and minimum_evaluation_games>=2 and
        type(simulations) is int and simulations>=10000,'READINESS_CONFIGURATION')
    rows=_validated(scores,at,registry,registry_pin)
    require(len(rows)<=500 and all(p['data_type']=='OFFICIAL_STAT' for o,p in rows),'BOUNDED_SCORE_UNIVERSE_REQUIRED')
    support=[] if support is None else support;rosters=[] if roster_observations is None else roster_observations
    require(type(support) is list and type(rosters) is list,'READINESS_SIDECAR_LISTS_REQUIRED')
    categories={p['usage']=='SYNTHETIC_TEST' for o,p in rows}|{o['payload']['usage']=='SYNTHETIC_TEST' for o in support+rosters}
    require(len(categories)<=1,'MIXED_SYNTHETIC_REAL_READINESS_INPUTS')
    if support:validate_support(scores,support,asof_utc=at,registry=registry,registry_pin=registry_pin)
    # Validate every roster even when it belongs to a different target; do not
    # hide a corrupt sidecar behind fixture filtering.
    if rosters:
        from faz46_rosters import replay_listing
        for o in rosters:replay_listing(o,fixture=o['payload']['fixture'],cutoff_utc=at,maximum_age_seconds=100*366*86400,require_permitted=False,registry=registry,registry_pin=registry_pin)
    inv=inventory(scores,asof_utc=at,registry=registry,registry_pin=registry_pin);reports={}
    for league in ('NBA','EUROLEAGUE','EUROCUP'):
        season=2027;selected=[o for o,p in rows if p['fixture']['league']==league and p['fixture']['season_end_year']==season]
        by_game={o['payload']['fixture']['canonical_id']:o for o in selected};starts=sorted({o['payload']['fixture']['start_utc'] for o in selected})
        r=dict(input_games=len(by_game),distinct_tipoff_groups=len(starts),evaluation=None,latest_target=None)
        if not by_game:r['status']='ABSTAIN_NO_SCORE_ARCHIVE';reports[league]=r;continue
        if len(starts)<3:r['evaluation']=dict(status='ABSTAIN_INSUFFICIENT_CHRONOLOGICAL_GROUPS',folds=[],cohorts=None)
        else:
            train_index=min(len(starts)-2,max(1,len(starts)*3//5));validation_index=min(len(starts)-1,max(train_index+1,len(starts)*4//5))
            r['evaluation']=evaluate(selected,league=league,season_end_year=season,train_end_utc=starts[train_index],validation_end_utc=starts[validation_index],
                asof_utc=at,minimum_team_games=minimum_team_games,minimum_evaluation_games=minimum_evaluation_games,simulations=simulations,registry=registry,registry_pin=registry_pin)
        target=max((o['payload']['fixture'] for o in selected),key=lambda f:(f['start_utc'],f['canonical_id']));cutoff=target['start_utc']-1
        records=materialize_research_archive(selected,registry=registry,registry_pin=registry_pin)
        context=[o for o in rosters if o['payload']['fixture']==target]
        try:
            result=research_with_context(records,context,target=target,cutoff_utc=cutoff,history_evidence=selected,mode='ARCHIVED_SOURCE_CLOCK',
                minimum_team_games=minimum_team_games,simulations=simulations,registry=registry,registry_pin=registry_pin)
            p=result['payload'];ref=p['reference']
            r['latest_target']=dict(target=target,cutoff_utc=cutoff,status=ref['status'],abstain_reason=ref.get('abstain_reason'),
                excluded=ref.get('excluded',{}),history_source_binding=p['history_source_binding'],prediction=ref['prediction'],
                prediction_usage=ref['usage'],original_context_usage=p['evidence']['payload']['usage'],context_missing=p['evidence']['payload']['missing'],
                context_applied_to_coefficients=False,context_observations=len(context),prospective_records_created=0)
        except ValueError as ex:r['latest_target']=dict(target=target,cutoff_utc=cutoff,status='ABSTAIN',abstain_reason=str(ex),prediction=None,prospective_records_created=0)
        if support:r['support_readiness']=support_report(scores,support,target,cutoff_utc=cutoff,minimum_team_games=minimum_team_games,
            last_games=max(10,minimum_team_games),registry=registry,registry_pin=registry_pin)
        else:r['support_readiness']=dict(status='ABSTAIN_NO_AUXILIARY_BUNDLE')
        mats=[o['payload']['materialized_at_utc'] for o in selected]
        r['all_source_wrappers_after_last_tipoff']=min(mats)>max(starts)
        r['status']='READINESS_AUDITED_NOT_MODEL_SUPERIORITY';reports[league]=r
    pairs=sum(c['games'] for r in reports.values() for c in ((r.get('evaluation') or {}).get('cohorts') or {}).values())
    return dict(status='READ_ONLY_RESEARCH_READINESS_NOT_PROSPECTIVE',asof_utc=at,source_inventory=inv,leagues=reports,
        evaluated_prediction_result_pairs=pairs,roster_observations=len(rosters),support_observations=len(support),
        usage='SYNTHETIC_TEST' if categories=={True} else 'RETROSPECTIVE_RESEARCH',
        coefficients_fitted=False,production_coefficients_changed=False,prospective_records_created=0,calibration_status='NOT_ESTABLISHED',
        external_storage='NOT_CONFIGURED',scheduler='NOT_INSTALLED',independent_cloud_recovery='NOT_VERIFIED')


def main():
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--score-inputs',required=True);a.add_argument('--trusted-score-sha256',required=True)
    a.add_argument('--support-inputs');a.add_argument('--trusted-support-sha256');a.add_argument('--prematch-audit');a.add_argument('--trusted-prematch-sha256')
    a.add_argument('--source-policy');a.add_argument('--trusted-policy-sha256');a.add_argument('--output')
    args=a.parse_args()
    try:
        require(all(bool(x)==bool(y) for x,y in [(args.support_inputs,args.trusted_support_sha256),(args.prematch_audit,args.trusted_prematch_sha256),(args.source_policy,args.trusted_policy_sha256)]),'READINESS_PIN_PAIRS_REQUIRED')
        policy=dict(registry=REGISTRY,registry_pin=REGISTRY_PIN);policy_ref=None
        if args.source_policy:
            from faz44_policy import read_source_policy
            p=read_source_policy(args.source_policy,trusted_sha256=args.trusted_policy_sha256);policy=dict(registry=p['registry'],registry_pin=p['registry_sha256']);policy_ref=p['policy_bundle_sha256']
        paths=[p for p in (args.score_inputs,args.support_inputs,args.prematch_audit,args.source_policy) if p];before={p:file_sha(p) for p in paths}
        b=read_development_inputs(args.score_inputs,trusted_sha256=args.trusted_score_sha256,policy_bundle_sha256=policy_ref,**policy)
        require(b.payload.get('format')=='FAZ44_INDEXED_DEVELOPMENT_INPUTS_V1','INDEXED_SCORE_INPUT_REQUIRED')
        scores=list(b.payload['sources'].values());require(all(o['payload']['usage']!='SYNTHETIC_TEST' for o in scores),'SYNTHETIC_READINESS_CLI_REFUSED')
        support=[];rosters=[]
        if args.support_inputs:
            p=read_support_bundle(args.support_inputs,trusted_sha256=args.trusted_support_sha256,score_input_sha256=args.trusted_score_sha256,scores=scores,**policy);support=list(p['observations'].values())
        if args.prematch_audit:
            p=read_audit(args.prematch_audit,trusted_sha256=args.trusted_prematch_sha256,**policy);rosters=[o for r in p['report']['audits'] for o in r['observations']]
        runtime=model_manifest();verify_execution_manifest(runtime)
        report=readiness_report(scores,support=support,roster_observations=rosters,**policy)
        verify_execution_manifest(runtime);require(all(file_sha(p)==h for p,h in before.items()),'READINESS_INPUT_FILES_CHANGED')
        p=dict(format=FORMAT,usage='READ_ONLY_RESEARCH_READINESS',created_at_utc=int(time.time()),model_manifest=runtime,
            source_pins=dict(score=args.trusted_score_sha256,support=args.trusted_support_sha256,prematch=args.trusted_prematch_sha256,policy=policy_ref),
            source_files_sha256=before,source_files_unchanged=True,report=report,prospective_records_created=0)
        sealed=dict(payload=p,sha256=digest(p));created=None
        if args.output:created=publish_development_artifact(args.output,sealed,expected_format=FORMAT,filename_prefix='faz47-readiness-')
        summary={league:dict(input_games=r['input_games'],tipoff_groups=r['distinct_tipoff_groups'],latest_status=(r['latest_target'] or {}).get('status'),
            latest_excluded=(r['latest_target'] or {}).get('excluded'),all_source_wrappers_after_last_tipoff=r.get('all_source_wrappers_after_last_tipoff')) for league,r in report['leagues'].items()}
        print(json.dumps(dict(status=report['status'],model_sha=runtime['payload']['git_sha'],trusted_readiness_sha256=sealed['sha256'],path=args.output,
            created=created,leagues=summary,evaluated_prediction_result_pairs=report['evaluated_prediction_result_pairs'],source_files_unchanged=True,
            prospective_records_created=0,network_requests=0),sort_keys=True));return 0
    except (ValueError,KeyError,TypeError,OSError,AttributeError):print(json.dumps(dict(status='ABSTAIN_READINESS_OPERATION_NOT_CONFIRMED',prospective_records_created=0)));return 1


if __name__=='__main__':raise SystemExit(main())
