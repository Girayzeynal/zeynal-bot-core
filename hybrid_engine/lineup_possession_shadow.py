"""NBA player/lineup/quarter-first SHADOW simulator. No live service integration.

Every parameter, projected stint and player availability must be supplied in a
SHA-pinned, time-eligible input envelope. Hashes protect bytes, NOT authenticity
of the upstream model fit, medical report or coach rotation assertion.

This module does not fit or manufacture player impact coefficients, infer medical
status from news, download sources, register bets, or modify legacy forecasts.
It is an opt-in RESEARCH ONLY primitive until independent feed provenance and
prospective validation are implemented.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

VERSION = 'LINEUP_POSSESSION_QUARTER_SHADOW_V1'
SIDES = ('home', 'away')
POINTS = np.arange(5, dtype=np.int64)
MAX_STINTS = 96
MAX_PLAYERS = 40
MAX_BYTES = 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(v, label, low=None, high=None):
    if type(v) not in (int, float) or not math.isfinite(v):
        raise ValueError(label + '_FINITE_NUMBER_REQUIRED')
    x = float(v)
    if (low is not None and x < low) or (high is not None and x > high):
        raise ValueError(label + '_OUT_OF_RANGE')
    return x


def ids(values, label, *, at_least=1, at_most=MAX_PLAYERS):
    if not isinstance(values, list) or not at_least <= len(values) <= at_most or any(
        type(x) is not str or not x or len(x)>128 for x in values) or len(set(values)) != len(values):
        raise ValueError(label + '_UNIQUE_NONEMPTY_IDS_REQUIRED')
    return values


def sha(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('SOURCE_SHA256_REQUIRED')
    return value


def envelope(value, label):
    if not isinstance(value, dict) or set(value) != {'payload', 'sha256'}:
        raise ValueError(label+'_ENVELOPE_REQUIRED')
    if sha(value['sha256']) != digest(value['payload']):
        raise ValueError(label+'_HASH_CONFLICT')
    return value['payload']


def source_clock(record, fixture, kind):
    if record.get('fixture_id') != fixture['fixture_id']:
        raise ValueError(kind+'_FIXTURE_ID_CONFLICT')
    observed=record.get('observed_at_utc')
    available=record.get('available_at_utc')
    if (type(observed) is not int or type(available) is not int or
        not 0 < observed <= available <= fixture['decision_utc'] < fixture['tipoff_utc']):
        raise ValueError(kind+'_PREGAME_CLOCK_CONFLICT')
    if (type(record.get('source_url')) is not str or not record['source_url'].startswith('https://') or
        len(record['source_url']) > 1200):
        raise ValueError(kind+'_HTTPS_SOURCE_URL_REQUIRED')
    sha(record.get('source_document_sha256'))
    # This metadata is declared by the packager, not independent provider proof.
    if record.get('attestation') != 'DECLARED_SOURCE_NOT_INDEPENDENTLY_VERIFIED':
        raise ValueError(kind+'_NO_FAKE_VERIFICATION')


def _coeffs(p, tag):
    if not isinstance(p, dict) or set(p) != {'attack', 'defense', 'pace'}:
        raise ValueError(tag+'_COMPLETE_FITTED_COEFFICIENTS_REQUIRED')
    return {k:number(p[k], tag+'_'+k, -.5, .5) for k in p}


def validate(bundle):
    if not isinstance(bundle,dict) or set(bundle) != {'format', 'fixture', 'model', 'roster', 'rotation'} or bundle['format']!=VERSION:
        raise ValueError('SHADOW_EXPLICIT_INPUT_BUNDLE_REQUIRED')
    fixture=bundle['fixture']
    if not isinstance(fixture, dict) or set(fixture)!= {
        'league','fixture_id','home_team_id','away_team_id','tipoff_utc','decision_utc'}:
        raise ValueError('SHADOW_FIXTURE_FIELDS_REQUIRED')
    if fixture['league']!='NBA' or type(fixture['fixture_id']) is not str or not fixture['fixture_id']:
        raise ValueError('SHADOW_NBA_FIXTURE_REQUIRED')
    if (any(type(fixture[k]) is not str or not fixture[k] for k in ('home_team_id','away_team_id')) or
        fixture['home_team_id']==fixture['away_team_id'] or type(fixture['tipoff_utc']) is not int or
        type(fixture['decision_utc']) is not int or not 0 < fixture['decision_utc'] < fixture['tipoff_utc'] or
        fixture['decision_utc'] > int(time.time())):
        raise ValueError('SHADOW_TARGET_CLOCK_OR_TEAM_CONFLICT')

    model=envelope(bundle['model'],'SHADOW_MODEL')
    roster=envelope(bundle['roster'],'SHADOW_ROSTER')
    rotation=envelope(bundle['rotation'],'SHADOW_ROTATION')
    if model.get('format')!='PREFIT_LINEUP_POSSESSION_PARAMETERS_V1' or model.get('training_scope')!='PREVIOUSLY_AVAILABLE_GAMES_ONLY':
        raise ValueError('SHADOW_HISTORICAL_MODEL_DECLARATION_REQUIRED')
    if (type(model.get('fit_cutoff_utc')) is not int or
        type(model.get('training_available_max_utc')) is not int or
        not 0 < model['training_available_max_utc'] <= model['fit_cutoff_utc'] <= fixture['decision_utc']):
        raise ValueError('SHADOW_NO_POSTFORECAST_PARAMETER_FIT')
    sha(model.get('training_source_sha256'))
    ids(model.get('training_fixture_ids'), 'SHADOW_TRAINING', at_most=20000)
    if fixture['fixture_id'] in model['training_fixture_ids']:
        raise ValueError('SHADOW_TARGET_LABEL_LEAKAGE')
    if model.get('player_coefficients_fit_status')!='PREGAME_HISTORICAL_EXPOSURE_FIT_DECLARED':
        raise ValueError('SHADOW_PLAYER_FIT_NOT_PROVEN')
    if roster.get('format')!='PREGAME_NBA_ROSTER_STATUS_V1':
        raise ValueError('SHADOW_ROSTER_FORMAT_REQUIRED')
    if rotation.get('format')!='PREGAME_LINEUP_ROTATION_ESTIMATE_V1' or rotation.get('record_class')!='PREGAME_PROJECTED_NOT_CONFIRMED':
        raise ValueError('SHADOW_ROTATION_FORMAT_REQUIRED')
    for record,tag in ((roster,'SHADOW_ROSTER'),(rotation,'SHADOW_ROTATION')):
        source_clock(record,fixture,tag)
    if roster.get('coverage')!='DECLARED_COMPLETE_RELEVANT_PLAYERS' or not isinstance(roster.get('players'),dict) or set(roster['players'])!=set(SIDES):
        raise ValueError('SHADOW_STATUS_COVERAGE_MISSING')
    statuses={}
    for side in SIDES:
        entries=roster['players'][side]
        if not isinstance(entries,list) or not 5<=len(entries)<=MAX_PLAYERS:
            raise ValueError('SHADOW_PLAYER_STATUS_LIST_REQUIRED')
        names=[]
        statuses[side]={}
        for p in entries:
            if not isinstance(p,dict) or set(p) != {'player_id','status'}:
                raise ValueError('SHADOW_PLAYER_STATUS_FIELDS_REQUIRED')
            name=p['player_id'];ids([name],'SHADOW_PLAYER_ID')
            if p['status'] not in ('AVAILABLE','OUT'):
                # QUESTIONABLE without outcome-independent scenario weights is
                # not silently treated as AVAILABLE/OUT.
                raise ValueError('SHADOW_UNRESOLVED_PLAYER_STATUS')
            names.append(name);statuses[side][name]=p['status']
        if len(names)!=len(set(names)) or sum(v=='AVAILABLE' for v in statuses[side].values())<5:
            raise ValueError('SHADOW_INVALID_UNIQUE_ACTIVE_ROSTER')
    if set(statuses['home']) & set(statuses['away']):
        raise ValueError('SHADOW_PLAYER_ASSIGNED_BOTH_TEAMS')

    tempo=model.get('base_pace_per_48')
    probs=model.get('point_outcome_probabilities')
    effects=model.get('player_coefficients')
    coaches=model.get('coach_quarter_log_effects')
    if any(not isinstance(obj,dict) or set(obj)!=set(SIDES) for obj in (tempo,probs,effects,coaches)):
        raise ValueError('SHADOW_COMPLETE_TWO_TEAM_MODEL_REQUIRED')
    for side in SIDES:
        number(tempo[side], 'SHADOW_BASE_PACE', 65, 145)
        v=probs[side]
        if not isinstance(v,list) or len(v)!=5 or any(number(p,'SHADOW_POINT_MASS',0,1)<0 for p in v) or abs(sum(v)-1)>1e-8:
            raise ValueError('SHADOW_VALID_POINT_DISTRIBUTION_REQUIRED')
        if not isinstance(effects[side],dict) or set(effects[side])!=set(statuses[side]):
            raise ValueError('SHADOW_NO_IMPUTED_OR_MISSING_PLAYER_COEFFICIENT')
        for player,coef in effects[side].items():_coeffs(coef,'SHADOW_PLAYER')
        coach=coaches[side]
        if not isinstance(coach,dict) or set(coach)!={'pace','attack'}:
            raise ValueError('SHADOW_TACTIC_PARAMS_REQUIRED')
        for k in ('pace','attack'):
            values=coach[k]
            if not isinstance(values,list) or len(values)!=4:
                raise ValueError('SHADOW_FOUR_QUARTER_COACH_PRIOR_REQUIRED')
            for value in values:number(value,'SHADOW_COACH_'+k,-.5,.5)
    number(model.get('home_court_attack_log_effect'), 'SHADOW_HOME_EFFECT', -.5,.5)
    number(model.get('home_court_pace_log_effect'), 'SHADOW_HOME_PACE', -.5,.5)

    stints=rotation.get('stints')
    if not isinstance(stints,list) or not 4<=len(stints)<=MAX_STINTS:
        raise ValueError('SHADOW_FOUR_QUARTER_STINTS_REQUIRED')
    minutes=[0.]*4
    exposures={side:{pid:0. for pid in statuses[side]} for side in SIDES}
    for entry in stints:
        if not isinstance(entry,dict) or set(entry)!={'quarter','minutes','home','away'}:
            raise ValueError('SHADOW_STINT_FIELDS_REQUIRED')
        quarter=entry['quarter']
        if type(quarter) is not int or not 1<=quarter<=4:
            raise ValueError('SHADOW_QUARTER_1_TO_4_REQUIRED')
        dur=number(entry['minutes'],'SHADOW_STINT_DURATION', .001, 12)
        minutes[quarter-1]+=dur
        for side in SIDES:
            five=ids(entry[side], 'SHADOW_LINEUP',at_least=5,at_most=5)
            if any(statuses[side].get(pid)!='AVAILABLE' for pid in five):
                raise ValueError('SHADOW_OUT_OR_UNKNOWN_PLAYER_USED_IN_STINT')
            for pid in five:exposures[side][pid]+=dur
    if any(abs(t-12)>1e-6 for t in minutes):
        raise ValueError('SHADOW_EACH_QUARTER_MUST_HAVE_12_MINUTES')
    if any(abs(sum(exposures[side].values())-240)>1e-5 for side in SIDES):
        raise ValueError('SHADOW_240_TEAM_PLAYER_MINUTES_REQUIRED')
    if any(exposures[side][pid] > 48+1e-6 for side in SIDES for pid in exposures[side]):
        raise ValueError('SHADOW_MAX_PLAYER_REGULATION_MINUTES_EXCEEDED')
    return dict(fixture=fixture,model=model,rotation=rotation,roster=roster,exposures=exposures,
                pins={key:bundle[key]['sha256'] for key in ('model','roster','rotation')},
                input_digest=digest(bundle))


def tilt_probabilities(probs, shift):
    """Outcome-value exponential tilt of *pre-fit* point distribution.

    These are research-only model assumptions, not measured point values.
    No parameter is estimated from the target game's result.
    """
    base=np.asarray(probs,dtype=float)
    if base.shape!=(5,) or abs(float(base.sum())-1)>1e-8:
        raise ValueError('SHADOW_INVALID_POINT_BASE')
    logits=shift*POINTS.astype(float)
    logits-=float(np.max(logits))
    weights=base*np.exp(logits)
    if not 0<float(weights.sum()):
        raise ValueError('SHADOW_ZERO_POINT_MASS')
    return weights/weights.sum()


def _draw_points(rng, possessions, probabilities):
    """Vectorized exact 5-category categorical count with a varying Poisson N."""
    remaining=possessions.copy()
    points=np.zeros(len(possessions),dtype=np.int32)
    rest=1.0
    for value in range(4):
        prob=float(probabilities[value])/rest if rest else 0.0
        prob=max(0.0,min(1.0,prob))
        drawn=rng.binomial(remaining,prob)
        remaining-=drawn
        points += int(value)*drawn
        rest-=float(probabilities[value])
    points += 4*remaining
    return points


def simulate(bundle, *, scenarios=10000, seed=20261121):
    # Validate and pin all inputs BEFORE drawing a single path.
    p=validate(bundle)
    if type(scenarios) is not int or not 1000<=scenarios<=32768 or type(seed) is not int or seed<0:
        raise ValueError('SHADOW_BOUNDED_DETERMINISTIC_SCENARIOS_REQUIRED')
    model=p['model'];f=p['fixture'];stints=p['rotation']['stints'];coefs=model['player_coefficients']
    rng=np.random.default_rng(seed)
    samples=np.zeros((scenarios,4,2),dtype=np.int32)
    possession_paths=np.zeros((scenarios,4),dtype=np.int32)
    expected_segment_ceilings=[]
    for stint in stints:
        quarter=stint['quarter']-1;minutes=stint['minutes'];
        pace_effect=(model['home_court_pace_log_effect']+
            model['coach_quarter_log_effects']['home']['pace'][quarter]+
            model['coach_quarter_log_effects']['away']['pace'][quarter])*.5
        for side in SIDES:
            pace_effect+=sum(coefs[side][pid]['pace'] for pid in stint[side])/10
        pace48=math.sqrt(model['base_pace_per_48']['home']*model['base_pace_per_48']['away'])*math.exp(pace_effect)
        rate=pace48*minutes/48.0
        if not 0<rate<100 or not math.isfinite(rate):
            raise ValueError('SHADOW_POSSESSION_RATE_INVALID')
        n=rng.poisson(rate, size=scenarios).astype(np.int32)
        possession_paths[:,quarter]+=n
        for s,side in enumerate(SIDES):
            other=SIDES[1-s]
            offense=sum(coefs[side][pid]['attack'] for pid in stint[side])/5
            opponent_def=sum(coefs[other][pid]['defense'] for pid in stint[other])/5
            coach=model['coach_quarter_log_effects'][side]['attack'][quarter]
            home=model['home_court_attack_log_effect'] if side=='home' else 0.
            prob=tilt_probabilities(model['point_outcome_probabilities'][side],
                                    offense-opponent_def+coach+home)
            samples[:,quarter,s]+=_draw_points(rng,n,prob)
        expected_segment_ceilings.append(dict(quarter=quarter+1,minutes=minutes,
                                             possessions_per_side_expected=rate))
    if not np.array_equal(samples.sum(axis=1).sum(axis=1),samples.sum(axis=(1,2))):
        raise ValueError('SHADOW_PATH_COHERENCE_FAILURE')
    if np.any(samples<0):raise ValueError('SHADOW_NEGATIVE_POINTS')
    quarter_corr=np.corrcoef(samples.sum(axis=2).T)
    if quarter_corr.shape!=(4,4) or not np.isfinite(quarter_corr).all():
        raise ValueError('SHADOW_INVALID_QUARTER_DISTRIBUTION_CORRELATION')
    out=dict(
        format='LINEUP_POSSESSION_QUARTER_SHADOW_RESULT_V1',
        record_class='RESEARCH_ONLY_UNCALIBRATED_NOT_PUBLISHED_TIP',
        fixture_id=f['fixture_id'],asof_utc=f['decision_utc'],tipoff_utc=f['tipoff_utc'],
        input_sha256=p['input_digest'],evidence_sha256=p['pins'],
        original_model_untouched=True,
        roster_source_authenticity_independently_verified=False,
        coefficient_training_integrity_independently_verified=False,
        bookmaker_settlement_scope_verified=False,
        lineup_stints_projected_not_confirmed=True,
        coach_effects_claimed_from_prefit_artifact_not_live_verified=True,
        scenarios=scenarios,seed=seed,
        home_mean=float(samples[:,:,0].sum(axis=1).mean()),
        away_mean=float(samples[:,:,1].sum(axis=1).mean()),
        total_mean=float(samples.sum(axis=(1,2)).mean()),
        quarters_mean=samples.mean(axis=0).tolist(),
        halves_mean=[samples[:,:2].sum(axis=1).mean(axis=0).tolist(),
                     samples[:,2:].sum(axis=1).mean(axis=0).tolist()],
        quarter_path_correlation=quarter_corr.tolist(),
        expected_possessions_by_stint=expected_segment_ceilings,
        mean_possessions_by_quarter=possession_paths.mean(axis=0).tolist(),
        projected_minutes_by_team=p['exposures'],
        score_paths_sha256=hashlib.sha256(samples.tobytes()).hexdigest(),
        source_coverage_status='DECLARED_PREGAME_INPUTS_NOT_INDEPENDENTLY_VERIFIED',
        deployable=False,production_changed=False,legacy_forecasts_changed=False,
        total_generated_from_quarter_events=True,
        old_largest_remainder_allocation_used=False,
        true_possession_by_possession_pbp_replay=False,
        actual_coach_strategy_verified=False,
        injuries_adjusted_via_roster_exclusion_only=True,
        travel_rest_and_referee_effects_not_modeled=True,
        verified_predictive_accuracy=None)
    return out,samples


def markets(samples, quoted_lines):
    """Regulation-only research, not bookmaker settlement. Never invent lines."""
    if not isinstance(quoted_lines,list) or len(quoted_lines)>128:
        raise ValueError('SHADOW_EXPLICIT_QUOTES_REQUIRED')
    records=[]
    for quote in quoted_lines:
        if not isinstance(quote,dict) or set(quote)!={'period','market','line'}:
            raise ValueError('SHADOW_EXPLICIT_PERIOD_MARKET_LINE_REQUIRED')
        q,kind=quote['period'],quote['market']
        number(quote['line'],'SHADOW_MARKET_LINE',-500,500)
        if q=='FULL':chunk=samples
        elif q=='1H':chunk=samples[:,:2,:]
        elif q=='2H':chunk=samples[:,2:,:]
        elif q in ('1Q','2Q','3Q','4Q'):
            chunk=samples[:,int(q[0])-1:int(q[0]),:]
        else:raise ValueError('SHADOW_MARKET_PERIOD')
        totals=chunk.sum(axis=1)
        if kind=='TOTAL':v=totals.sum(axis=1)
        elif kind=='HOME':v=totals[:,0]
        elif kind=='AWAY':v=totals[:,1]
        elif kind=='HOME_HANDICAP':v=totals[:,0]-totals[:,1];
        else:raise ValueError('SHADOW_MARKET_KIND')
        line= -quote['line'] if kind=='HOME_HANDICAP' else quote['line']
        p_under=float(np.mean(v<line));p_push=float(np.mean(v==line));p_over=float(np.mean(v>line))
        records.append(dict(period=q,market=kind,line=quote['line'],
                            probabilities=dict(under=p_under,push=p_push,over=p_over),
                            raw_direction=('ALT' if p_under>p_over else 'UST' if p_over>p_under else 'DENGELI'),
                            selection_enabled=False,calibrated_confidence=None,
                            bookmaker_settlement_verified=False))
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True,help='Existing externally prepared, SHA-pinned PREGAME player+rotation+fit bundle')
    parser.add_argument('--quotes',help='Optional existing JSON list of actual bookmaker period/market/line numbers')
    parser.add_argument('--scenarios',type=int,default=10000)
    parser.add_argument('--seed',type=int,default=20261121)
    args=parser.parse_args()
    f=Path(args.bundle).expanduser()
    if f.is_symlink() or not f.is_file() or f.stat().st_size>MAX_BYTES:
        raise ValueError('SHADOW_BOUNDED_EXISTING_BUNDLE_REQUIRED')
    data=json.loads(f.read_text())
    result,samples=simulate(data,scenarios=args.scenarios,seed=args.seed)
    if args.quotes:
        q=Path(args.quotes).expanduser()
        if q.is_symlink() or not q.is_file() or q.stat().st_size>MAX_BYTES:
            raise ValueError('SHADOW_BOUNDED_QUOTED_LINES_REQUIRED')
        lines=json.loads(q.read_text())
        result['market_research']=markets(samples,lines)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False))


if __name__=='__main__':main()
