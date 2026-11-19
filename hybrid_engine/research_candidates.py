"""Offline readiness + reuse of existing possession/quarter candidates.

Not a live inference entry point. A strict Cut must originate in load_manifest /
feature_cut (or in the authenticated frozen input audit). Missing boxes abstain;
score averages are never renamed possession tempo or per-100 efficiency.
"""
from collections import Counter

from hybrid_engine.availability import effective_box_time
from hybrid_engine.boxes import checked_stats
from hybrid_engine.data import STRICT, Abstain, available_at
from hybrid_engine.distributions import Budget
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.possession import PossessionModel
from hybrid_engine.quarter_shadow import predict as quarter_shadow

VERSION = 'PHASE92_RESEARCH_CANDIDATE_GATE_V1'


def feature_readiness(cut):
    if cut.evaluation_class != STRICT or type(cut.cutoff_utc) is not int or not 0 < cut.cutoff_utc < cut.target['fixture_start_utc']:
        raise ValueError('STRICT_PREMATCH_CANDIDATE_CUT_REQUIRED')
    for r in cut.history:
        if (r['fixture_id'] == cut.target['fixture_id'] or r['fixture_start_utc'] >= cut.cutoff_utc or
                available_at(r, STRICT) > cut.cutoff_utc or
                (r['league'], r['season']) != (cut.target['league'], cut.target['season'])):
            raise ValueError('CANDIDATE_HISTORY_LEAKAGE_OR_SCOPE')
    sides = {}
    for side in ('home', 'away'):
        entries = cut.features[side]['boxes']
        seen = set()
        totals = Counter()
        pace = []
        source_pins = []
        for row, box, own, other in entries:
            if (row not in cut.history or row['fixture_id'] in seen or
                    own not in ('home', 'away') or other != ('away' if own == 'home' else 'home') or
                    row[own+'_team_id'] != cut.target[side+'_team_id'] or
                    box not in [row.get('box'), *row.get('box_versions', [])] or
                    box['fixture_id'] != row['fixture_id'] or box['league'] != row['league']):
                raise ValueError('CANDIDATE_BOX_IDENTITY_CONFLICT')
            if (not box['regulation_eligible'] or any(len(row['periods'][s]) != 4 for s in ('home', 'away')) or
                    effective_box_time(box) > cut.cutoff_utc):
                raise ValueError('CANDIDATE_BOX_FUTURE_OR_OVERTIME')
            if [sum(row['periods'][s]) for s in ('home','away')] != row['final_scores']:
                raise ValueError('CANDIDATE_BOX_PERIOD_TOTAL_CONFLICT')
            stat = {s: checked_stats(box['teams'][s]) for s in ('home', 'away')}
            if any(box['teams'][s].get('possessions_estimate') != stat[s]['possessions_estimate'] for s in ('home','away')):
                raise ValueError('CANDIDATE_STORED_POSSESSION_ESTIMATE_CONFLICT')
            if [stat[s]['points'] for s in ('home', 'away')] != row['final_scores']:
                raise ValueError('CANDIDATE_BOX_SCORE_CONFLICT')
            pin = box['source'].get('document_sha256')
            if not isinstance(pin, str) or len(pin) != 64 or any(c not in '0123456789abcdef' for c in pin):
                raise ValueError('CANDIDATE_BOX_SOURCE_PIN_REQUIRED')
            seen.add(row['fixture_id'])
            totals['points_for'] += stat[own]['points']
            totals['points_against'] += stat[other]['points']
            totals['own_possessions'] += stat[own]['possessions_estimate']
            totals['opponent_possessions'] += stat[other]['possessions_estimate']
            totals['turnovers'] += stat[own]['tov']
            totals['offensive_rebounds'] += stat[own]['orb']
            totals['free_throw_attempts'] += stat[own]['fta']
            pace.append((stat[own]['possessions_estimate'] + stat[other]['possessions_estimate']) / 2)
            source_pins.append(dict(fixture_id=row['fixture_id'], document_sha256=pin,
                                    available_at_utc=effective_box_time(box)))
        n = len(seen)
        sides[side] = dict(box_games=n, source_pins=source_pins,
            estimated_possessions_per_regulation_game=None if not n else sum(pace)/n,
            estimated_offensive_rating=None if not n else 100*totals['points_for']/totals['own_possessions'],
            estimated_defensive_rating=None if not n else 100*totals['points_against']/totals['opponent_possessions'],
            turnover_rate=None if not n else totals['turnovers']/totals['own_possessions'],
            offensive_rebounds=None if not n else totals['offensive_rebounds'],
            free_throw_attempts=None if not n else totals['free_throw_attempts'])
    return dict(format=VERSION, cutoff_utc=cut.cutoff_utc, league=cut.target['league'],
        fixture_id=cut.target['fixture_id'], sides=sides,
        possession_readiness='ELIGIBLE_FOR_OFFLINE_COMPARISON' if min(v['box_games'] for v in sides.values()) >= 6 else 'ABSTAIN_INSUFFICIENT_PAST_BOXES',
        pace_definition='FGA_PLUS_0.44FTA_MINUS_ORB_PLUS_TOTAL_TOV_ESTIMATE_NOT_MEASURED_PBP',
        regulation_minutes=48 if cut.target['league']=='NBA' else 40,
        rest='START_TIME_GAP_IS_A_PROXY_NOT_VERIFIED_TRAVEL_OR_RECOVERY',
        roster='NO_VERIFIED_PREMATCH_MINUTE_EXPOSURES_OR_PLAYER_COEFFICIENTS',
        context_markov='ANNOTATED_POSSESSION_BOUNDARIES_AND_CONTEXT_COVERAGE_REQUIRED',
        calibration_fit=False, production_enabled=False)


def run_candidates(cut, *, base=None, seed=20261112):
    """Reuse original samplers; never replace an archived forecast in place."""
    report = feature_readiness(cut)
    candidates = {}
    if report['possession_readiness'] == 'ELIGIBLE_FOR_OFFLINE_COMPARISON':
        for method in ('ANALYTIC', 'MC'):
            try:
                f = PossessionModel().predict(cut, method=method, budget=Budget(seed=seed))
                candidates['POSSESSION_'+method] = dict(status='RESEARCH_OUTPUT_NOT_VALIDATED',
                    projection=f.summary(), intervals=prediction_intervals(f),
                    calibration_status='NOT_CALIBRATED', scenarios=f.metadata['scenarios'])
            except Abstain as exc:
                candidates['POSSESSION_'+method] = dict(status='ABSTAIN', reason=str(exc))
    else:
        candidates['POSSESSION'] = dict(status='ABSTAIN', reason=report['possession_readiness'])
    if base is not None:
        try:
            f = quarter_shadow(base, cut, seed=seed)
            candidates['QUARTER_SHADOW'] = dict(status='EXPLORATORY_ONLY',
                projection=f.summary(), intervals=prediction_intervals(f),
                point_scores_and_full_game_paths_preserved=True,
                fresh_disjoint_validation_required=True)
        except Abstain as exc:
            candidates['QUARTER_SHADOW'] = dict(status='ABSTAIN', reason=str(exc))
    return dict(readiness=report, candidates=candidates, calibration_fit=False,
                evidence_class='OFFLINE_RESEARCH_NOT_AN_ACTUAL_PREMATCH_CAPTURE',
                forecast_replaced=False, production_enabled=False, promotion_decision='NO_GO_WITHOUT_PAIRED_OOS')
