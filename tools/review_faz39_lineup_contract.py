"""Isolated synthetic acceptance probes, NOT an integration or model benchmark."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
from unittest.mock import patch

import argparse,subprocess,sys,types
from faz41_faz40 import capture_announcement,prematch_context
from faz41_evidence import REGISTRY,fixture_identity
from prediction_inputs import digest
from tests.test_faz42_history import NOW,permitted_registry

PLAYERS=('1','2','3','4','5','6')
TARGET=fixture_identity(league='NBA',season_end_year=2027,start_utc=NOW+3600,home_team_id='19',away_team_id='2')
URL='https://cdn.nba.com/static/json/test/announcement.json'
PERMITTED=permitted_registry()


def dto(**kw):
    args=dict(eligible=PLAYERS,starters=PLAYERS[:5],official=True,observed_at_utc=NOW-10,source=URL,prediction_utc=NOW);args.update(kw)
    return assess_lineup(**args)


def announcement(*,players=PLAYERS,team='19',observed=NOW-10,created=NOW-1,source=URL,registry=PERMITTED):
    raw=dict(format='EXPLICIT_TEAM_ANNOUNCEMENT_V1',fixture=TARGET,provider_fixture_id='0022600099',team_id=team,
        players=list(players),starting_five=list(players[:5]),status='CONFIRMED',published_at_utc=NOW-20)
    with patch('time.time',return_value=created):return capture_announcement(raw,provider='NBA',source_url=source,
        observed_at_utc=observed,ingested_at_utc=created,usage='SYNTHETIC_TEST',registry=registry,registry_pin=digest(registry))


def context(observations,*,fixture=TARGET,cutoff=NOW,registry=PERMITTED):
    return prematch_context(observations,fixture=fixture,cutoff_utc=cutoff,registry=registry,registry_pin=digest(registry))


def outcome(fn):
    try:
        value=fn()
        if isinstance(value,tuple):status='/'.join(v.status.value for v in value)
        elif hasattr(value,'status'):status=value.status.value
        else:status='CONFIRMED' if value['payload']['rosters'] else 'NO_CONFIRMED_LINEUP'
        return dict(rejected=False,status=status)
    except (ValueError,TypeError,KeyError) as ex:return dict(rejected=True,reason=str(ex),exception=type(ex).__name__)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    expected={'lineup_uncertainty.py':'fec7a45a469b252e4753c1004c9f4eb12fd2119f253c92a0af02df0b551ff09b',
        'tests/test_lineup_uncertainty.py':'d90c5be4427b26f3ae367701decf912a0d19b0e99a11d2c2bd6e4c8beef4149c'}
    candidate_bytes={}
    for name,pin in expected.items():
        body=(args.candidate_root/name).read_bytes()
        if hashlib.sha256(body).hexdigest()!=pin:raise SystemExit('REFUSED_CANDIDATE_SOURCE_PIN_MISMATCH')
        candidate_bytes[name]=body
    root=Path(__file__).resolve().parents[1]
    baseline={'faz41_faz40.py':'000f2a9f3c0a0588cbe03c331eca20454c306364466507c7858600479e160dc1',
        'faz46_rosters.py':'6cd33d05616eecbae820e4ef59a91cf0d60510dfa70d4cc9722d94deb35bb1c5',
        'faz46_collection.py':'d2bbedba9857a44b983dd288ca9fe52d05710eba2f1682214a580dac0924bcb5'}
    current_module_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in baseline}
    if current_module_hashes!=baseline:raise SystemExit('REFUSED_CURRENT_REVIEW_BASELINE_CHANGED')
    # Execute only the pinned, already inspected stdlib-only DTO, in this
    # isolated CLI process. Nothing is installed into the application's tree.
    module=types.ModuleType('_faz39_lineup_contract_review_only')
    sys.modules[module.__name__]=module
    exec(compile(candidate_bytes['lineup_uncertainty.py'],str(args.candidate_root/'lineup_uncertainty.py'),'exec'),module.__dict__)
    global assess_lineup
    assess_lineup=module.assess_lineup
    rows=[]
    basics=[('missing_is_unavailable',lambda:assess_lineup(eligible=PLAYERS,prediction_utc=NOW),'UNAVAILABLE'),
        ('projected_is_not_official',lambda:dto(official=False,source=None,observed_at_utc=None),'PROJECTED'),
        ('post_prediction_observation_rejected',lambda:dto(observed_at_utc=NOW+1),'REJECTED')]
    for key,fn,expected in basics:
        observed=outcome(fn);rows.append(dict(case=key,kind='DTO_CLASSIFICATION',candidate=observed,
            candidate_meets_criterion=observed['rejected'] if expected=='REJECTED' else observed.get('status')==expected))
    past=fixture_identity(league='NBA',season_end_year=2027,start_utc=NOW-1,home_team_id='19',away_team_id='2')
    whitespace=('1',' 1','2','3','4','5');namespace=('1','NBA:1','2','3','4','5')
    gates=[
        ('untrusted_plain_source_is_not_official_proof',lambda:dto(source='provider'),lambda:context([announcement(source='provider')])),
        ('unknown_policy_cannot_authorize_official_claim',lambda:dto(),lambda:context([announcement(registry=REGISTRY)],registry=REGISTRY)),
        ('prediction_clock_is_mandatory',lambda:dto(prediction_utc=None),lambda:context([],cutoff=None)),
        ('cutoff_must_be_before_tipoff',lambda:dto(),lambda:context([],fixture=past)),
        ('cutoff_and_observation_cannot_be_in_real_clock_future',lambda:dto(prediction_utc=NOW+200,observed_at_utc=NOW+100),lambda:context([],cutoff=NOW+200)),
        ('same_second_does_not_prove_v2_availability',lambda:dto(observed_at_utc=NOW),lambda:context([announcement(observed=NOW,created=NOW)])),
        ('whitespace_alias_cannot_create_five_players',lambda:dto(eligible=whitespace,starters=whitespace[:5]),lambda:context([announcement(players=whitespace)])),
        ('same_player_cannot_be_on_both_teams',lambda:(dto(),dto()),lambda:context([announcement(),announcement(team='2')])),
        ('same_team_provider_prefix_alias_is_not_a_second_player',lambda:dto(eligible=namespace,starters=namespace[:5]),lambda:context([announcement(players=namespace)])),
    ]
    with patch('time.time',return_value=NOW):
        for key,a,b in gates:
            candidate=outcome(a);current=outcome(b)
            rows.append(dict(case=key,kind='AUTHORITATIVE_MODEL_GATE_REQUIREMENT',candidate=candidate,faz46=current,
                candidate_meets_criterion=candidate['rejected'],faz46_meets_criterion=current['rejected']))
    files={name:hashlib.sha256(body).hexdigest() for name,body in candidate_bytes.items()}
    files['review_probe_script']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report=dict(purpose='SYNTHETIC_CONTRACT_REVIEW_NOT_MERGED_NOT_MODEL_PERFORMANCE',created_utc=datetime.now(timezone.utc).isoformat(),
        candidate_sha='d7fb5bf25aafe504a158b564f2e4d99a84f68c89',baseline_sha='c3684df35e0eadf53285ea6743aaf141b28fd80d',current_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),current_module_sha256=current_module_hashes,files=files,
        classification_checks=3,classification_checks_passed=sum(r['candidate_meets_criterion'] for r in rows[:3]),
        authoritative_acceptance_criteria=9,candidate_standalone_criteria_met=sum(r['candidate_meets_criterion'] for r in rows[3:]),
        faz46_authoritative_criteria_met=sum(r['faz46_meets_criterion'] for r in rows[3:]),cases=rows,
        integration_performed=False,safe_to_integrate_without_additional_adapter=False,production_changed=False,real_prediction_result_pairs=0,
        caveat='The candidate is a DTO/classifier, not a source validator. These criteria are required before authoritative model integration, not claims that its existing six unit tests failed.')
    with args.output.open('x') as target:target.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','files')},indent=2))
    for row in rows:print(row['case'],json.dumps({k:v for k,v in row.items() if k in ('candidate','faz46')}))


if __name__=='__main__':main()
