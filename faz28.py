"""Versioned, uncalibrated score decomposition and regulation probability proxy.

No source fetching, ledger mutation, injury imputation or retrospective forecasts.
"""
from decimal import Decimal
from statistics import stdev
from dataclasses import asdict

from prediction_inputs import validate_prediction_inputs, digest
from prematch_monte_carlo import PrematchSimulationInput, PrematchMonteCarloEngine

MODEL_ID='FAZ28_NORMAL_V1'


def split_score(score):
    cents=int(Decimal(str(score))*100)
    base,remainder=divmod(cents,4)
    return [float(Decimal(base+(i<remainder))/100) for i in range(4)]


def total(values):
    return float(sum((Decimal(str(v)) for v in values),Decimal(0)))


def build_multilayer(snapshot, *, model_version, config=None):
    import re
    if not isinstance(model_version,str) or not re.fullmatch('[0-9a-f]{40}',model_version):
        raise ValueError('full source SHA required')
    cfg=dict(simulations=10000,seed=20261104,score_correlation=0.0,market_total=None,market_scope=None)
    if config is not None:
        if not isinstance(config,dict) or set(config)-set(cfg):raise ValueError('unknown model configuration')
        cfg.update(config)
    if type(cfg['simulations']) is not int or not 10000<=cfg['simulations']<=100000:
        raise ValueError('FAZ28 requires 10000 to 100000 scenarios')
    if type(cfg['seed']) is not int:raise ValueError('integer seed required')
    corr=cfg['score_correlation']
    import math
    if type(corr) not in (int,float) or not math.isfinite(corr) or not -.95<=corr<=.95:
        raise ValueError('invalid score correlation assumption')
    if cfg['market_total'] is not None:
        if cfg['market_scope']!='REGULATION_ONLY' or type(cfg['market_total']) not in (int,float) or not math.isfinite(cfg['market_total']) or cfg['market_total']<=0:
            raise ValueError('positive market line with explicit regulation scope required')
    elif cfg['market_scope'] is not None:raise ValueError('market scope without line')
    p=snapshot['payload']
    if p['league']!='NBA' or p['scope']!='FINAL_WITH_OT':raise ValueError('NBA original score contract required')
    validate_prediction_inputs(snapshot,league='NBA',prediction_utc=p['prediction_ts_utc'],
        expected_home=p['expected_home'],expected_away=p['expected_away'])
    for side in ('home','away'):
        if Decimal(str(p['expected_'+side]))*100 != (Decimal(str(p['expected_'+side]))*100).to_integral_value():
            raise ValueError('original score must use at most two decimal places')
    home,away=p['expected_home'],p['expected_away']
    quarters={}
    hs,aws=split_score(home),split_score(away)
    for i in range(4):quarters[str(i+1)]=dict(home=hs[i],away=aws[i],total=total([hs[i],aws[i]]))
    halves={str(i+1):dict(home=total(hs[i*2:i*2+2]),away=total(aws[i*2:i*2+2]),
        total=total(hs[i*2:i*2+2]+aws[i*2:i*2+2])) for i in range(2)}
    sample_std={side:stdev(r['pts_for'] for r in p['teams'][side]['records']) for side in ('home','away')}
    missing=['VERIFIED_INJURIES','VERIFIED_ROSTERS','EMPIRICAL_QUARTER_MODEL','VERIFIED_REGULATION_MEANS','PROBABILITY_CALIBRATION']
    if cfg['market_total'] is None:missing.append('SCOPED_MARKET_LINE')
    rows=[r for t in p['teams'].values() for r in t['records']]
    pace_status='BOX_SCORE_ESTIMATE' if all(r.get('pace_evidence',{}).get('kind')=='BOX_SCORE_ESTIMATE' for r in rows if r.get('pace_evidence')) and all(r.get('pace_evidence') for r in rows) else 'UNVERIFIED_SOURCE_PACE'
    if pace_status!='BOX_SCORE_ESTIMATE':missing.append('SOURCE_VERIFIED_PACE')
    simulation=None
    if min(sample_std.values())>0:
        simulation=asdict(PrematchMonteCarloEngine().simulate(PrematchSimulationInput(
            home_mean=home,away_mean=away,home_std=sample_std['home'],away_std=sample_std['away'],
            score_correlation=corr,simulations=cfg['simulations'],seed=cfg['seed'],market_total=cfg['market_total'])))
    else:missing.append('NONZERO_EMPIRICAL_SCORE_VARIANCE')
    margin=total([home,-away])
    return dict(model_id=MODEL_ID,model_version=model_version,config=cfg,
        input_sha256=snapshot['sha256'],generated_at=p['prediction_ts_utc'],
        calibration_status='NOT_ESTABLISHED',evaluation_cohort='NEW_OPT_IN_PROSPECTIVE_ONLY',
        parent_score_scope=p['scope'],model_scope='REGULATION_ONLY',scope_status='UNVALIDATED_REGULATION_PROXY',
        assumptions=['OT-inclusive FAZ13 means used as regulation proxy; not separately verified',
            'Equal quarter expectation with deterministic cent rounding; no learned period effects',
            'Rounded nonnegative correlated normal scores; historical pts_for sample std; unfitted correlation',
            'Gamma(18,1) scenario period allocation; no empirical quarter calibration'],
        team_totals=dict(home=home,away=away,total=total([home,away])),
        spread=dict(expected_home_margin=margin,fair_home_handicap=-margin,market_handicap=None,
                    interpretation='model-implied line, not a verified market line'),
        quarters=quarters,halves=halves,variance=dict(method='sample_std_of_original_pts_for',values=sample_std),
        pace_status=pace_status,missing_data=missing,simulation=simulation,
        eventual_game_win_probability=None,
        probability_status='UNCALIBRATED_PROXY' if simulation else 'UNAVAILABLE_VARIANCE')


def validate_multilayer(result, snapshot, model_version):
    if not isinstance(result,dict) or result.get('model_id')!=MODEL_ID:
        raise ValueError('unknown multilayer model')
    expected=build_multilayer(snapshot,model_version=model_version,config=result['config'])
    if digest(result)!=digest(expected):raise ValueError('multilayer replay mismatch')
