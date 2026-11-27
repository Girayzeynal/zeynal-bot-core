"""Connect source-pinned historical rotation to the existing player contrast fit.

A separately archived forward research candidate; no changes to live scores.
No injury publication or target result is needed. Do not infer causal effects.
"""
import math
import time
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Abstain,local_path
from hybrid_engine.player_minutes import capped_rotation
from hybrid_engine.player_box_pilot import fit_box_association,projected_pair,verified_box_rows,paired_holdout
from hybrid_engine.player_contrast_research import fit,conditional_pair,fit_for_comparison
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS


def prepare(root,season,cutoff):
    root=local_path(root)
    storage=root/'adaptive-v2/inputs'
    if not (storage/'native').is_dir():
        raise Abstain('HISTORICAL_SCORE_NATIVE_FEATURE_ARCHIVE_MISSING')
    from hybrid_engine.adaptive_data import FeatureStore
    store=FeatureStore(storage,[root/'live-nba/assets'],
        lambda *a,**k: (_ for _ in ()).throw(RuntimeError('NETWORK_FORBIDDEN')))
    cohort=store.cohort('NBA',int(season.split('/')[0]),cutoff)
    games,excluded=verified_box_rows(cohort,cutoff)
    games=[g for g in games if g['season']==season]
    control=fit_box_association(games,cutoff,include_players=False)
    if control['status']!='REAL_HISTORICAL_BOX_MODEL_FITTED_RESEARCH_ONLY':
        raise Abstain('HISTORICAL_SCORE_INSUFFICIENT_NATIVE_BOX_GAMES')
    candidate=fit(games,cutoff)
    return dict(control=control,candidate=candidate,games=games,excluded=excluded)


def rotation_from_summary(summary):
    rows=summary['main_five']+summary['bench']
    if len(summary['main_five'])!=5 or len({r['player_id'] for r in rows})!=len(rows):
        raise ValueError('HISTORICAL_SCORE_ROTATION_IDENTITY')
    return dict(zip([r['player_id'] for r in rows],
        capped_rotation([r['average_minutes'] for r in rows])))


def compare(summary,snapshot,prepared,*,now):
    if (summary['format']!='NBA_HISTORICAL_MAIN_FIVE_V1'
        or summary['status']!='HISTORICAL_ROTATION_READY'
        or summary['fixture_id']!=snapshot['fixture_id']
        or summary['original_snapshot_sha256']!=digest(snapshot)
        or summary['fixture_start_utc']!=snapshot['fixture_start_utc']
        or digest({k:v for k,v in summary.items() if k!='sha256'})!=summary['sha256']
        or not summary['generated_at_utc']<=now<snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS):
        raise Abstain('HISTORICAL_SCORE_FORECAST_BINDING_OR_CLOCK')
    control=prepared['control'];candidate=prepared['candidate'];model=candidate['payload']
    if (control['season']!=snapshot['season'] or model['season']!=snapshot['season']
        or control['cutoff_utc']!=model['cutoff_utc'] or model['cutoff_utc']>summary['generated_at_utc']
        or control['training_sha256']!=model['training_sha256']
        or control['training_fixture_ids']!=model['training_fixture_ids']
        or snapshot['fixture_id'] in model['training_fixture_ids']):
        raise Abstain('HISTORICAL_SCORE_TRAINING_BINDING')
    teams=[snapshot[s]['provider_id'] for s in ('home','away')]
    if teams!=[summary['teams'][s]['team_id'] for s in ('home','away')]:
        raise ValueError('HISTORICAL_SCORE_TEAM_BINDING')
    rotations=[rotation_from_summary(summary['teams'][s]) for s in ('home','away')]
    if set(rotations[0])&set(rotations[1]):
        raise Abstain('HISTORICAL_SCORE_PLAYER_ON_BOTH_TEAMS')
    represented=[sum(m for p,m in r.items() if p in model['players']) for r in rotations]
    if not any(v>0 for v in represented):
        raise Abstain('HISTORICAL_SCORE_NO_FITTED_PLAYER_EXPOSURE')
    baseline=projected_pair(control,*teams,*rotations)
    point=conditional_pair(candidate,*teams,*rotations)['prediction']
    if any(not math.isfinite(x) or not 0<x<300 for x in point+baseline):
        raise Abstain('HISTORICAL_SCORE_OUT_OF_RANGE')
    return dict(format='HISTORICAL_FIVE_PLAYER_SCORE_RESEARCH_V1',
        status='FORWARD_CONDITIONAL_SCORE_RESEARCH',fixture_id=snapshot['fixture_id'],
        fixture_start_utc=snapshot['fixture_start_utc'],generated_at_utc=now,
        original_snapshot_sha256=digest(snapshot),rotation_sha256=summary['sha256'],
        model_sha256=candidate['sha256'],control_sha256=digest(control),
        training_sha256=model['training_sha256'],training_games=model['training_games'],
        training_cutoff_utc=model['cutoff_utc'],player_terms=len(model['players']),
        represented_minutes=represented,original_prediction=snapshot['prediction'],
        team_control=dict(home=baseline[0],away=baseline[1],total=sum(baseline)),
        player_candidate=dict(home=point[0],away=point[1],total=sum(point)),
        candidate_minus_control=[point[i]-baseline[i] for i in range(2)],
        lineup_verified=False,injury_source_calls=0,calibrated=False,
        causal_effect=False,production_enabled=False,forecast_changed=False)


def archive_score(root,summary,snapshot,prepared):
    now=int(time.time())
    result=compare(summary,snapshot,prepared,now=now)
    root=local_path(root)
    # Retain reproducible model and control evidence independently of the original score.
    model=prepared['candidate'];control=prepared['control'];cpin=digest(control)
    publish_json(root/('historical-score-model-'+model['sha256']+'.json'),model)
    publish_json(root/('historical-score-control-'+cpin+'.json'),dict(payload=control,sha256=cpin))
    if int(time.time())>=snapshot['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS:
        raise Abstain('HISTORICAL_SCORE_PUBLICATION_WINDOW_CLOSED')
    pin=digest(result)
    publish_json(root/('historical-score-'+pin+'.json'),dict(payload=result,sha256=pin))
    return dict(result,sha256=pin)


def review(prepared,now):
    return paired_holdout(prepared['games'],now_utc=now,candidate_fitter=fit_for_comparison)
