"""Research-only team-specific quarter behavior inventory from original pregame inputs.

Does NOT recommend a common scoring curve, a high Q2/Q3, injuries, minutes,
coach decisions, betting lines, or a fitted prediction. Each team and context
is described only by *its own* archived available records. No dataset writes.
"""
from __future__ import annotations

from collections import Counter
from statistics import mean, median, pstdev
import argparse
import hashlib
import json
import math
from pathlib import Path

FORMAT = 'TEAM_SPECIFIC_NATIVE_PERIOD_EVIDENCE_V1'
MAX_ROWS = 4000
SIDES = ('home','away')


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _number(x, tag):
    if type(x) not in (int, float) or not math.isfinite(x) or x < 0 or x > 500:
        raise ValueError(tag + '_INVALID_NONNEGATIVE_SCORE')
    return float(x)


def _clock(x, name):
    if type(x) is not int or x<=0:
        raise ValueError(name+'_POSITIVE_UTC_REQUIRED')
    return x


def _ids(request):
    if not isinstance(request, dict) or set(request)!={
        'league','season','fixture_id','home_team_id','away_team_id','decision_utc','tipoff_utc'}:
        raise ValueError('DYNAMICS_EXPLICIT_TARGET_REQUIRED')
    for key in ('league','season','fixture_id','home_team_id','away_team_id'):
        if type(request[key]) is not str or not request[key]:
            raise ValueError('DYNAMICS_EXPLICIT_ID_REQUIRED')
    if request['home_team_id']==request['away_team_id']:
        raise ValueError('DYNAMICS_DISTINCT_TEAMS_REQUIRED')
    if not 0 < _clock(request['decision_utc'],'DYNAMICS_DECISION') < _clock(request['tipoff_utc'],'DYNAMICS_TIPOFF'):
        raise ValueError('DYNAMICS_PREGAME_CLOCK_REQUIRED')


def _source(row, request):
    keys=('league','season','fixture_id','fixture_start_utc','home_team_id','away_team_id','available_at_utc','source_catalog_sha256','periods')
    if not isinstance(row,dict) or any(k not in row for k in keys):
        raise ValueError('DYNAMICS_COMPLETE_HISTORY_ROW_REQUIRED')
    if row['league']!=request['league'] or row['season']!=request['season']:
        raise ValueError('DYNAMICS_SEASON_LEAGUE_SCOPE_CONFLICT')
    if not all(type(row[k]) is str and row[k] for k in ('fixture_id','home_team_id','away_team_id')):
        raise ValueError('DYNAMICS_BAD_HISTORY_IDS')
    if row['fixture_id']==request['fixture_id'] or not (
        _clock(row['fixture_start_utc'],'DYNAMICS_HISTORY_TIP') <
        _clock(row['available_at_utc'],'DYNAMICS_HISTORY_AVAILABLE') <= request['decision_utc']):
        raise ValueError('DYNAMICS_POSTDECISION_OR_TARGET_LABEL')
    if row['home_team_id']==row['away_team_id']:
        raise ValueError('DYNAMICS_DUPLICATE_HISTORY_TEAMS')
    v=row['source_catalog_sha256']
    if type(v) is not str or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):
        raise ValueError('DYNAMICS_BAD_CATALOG_PIN')
    periods=row['periods']
    if not isinstance(periods,dict) or set(periods)!=set(SIDES):
        raise ValueError('DYNAMICS_COMPLETE_PERIODS_REQUIRED')
    for side in SIDES:
        vals=periods[side]
        if not isinstance(vals,list) or not 4<=len(vals)<=12:
            raise ValueError('DYNAMICS_FOUR_REGULATION_PERIODS_REQUIRED')
        if any(type(x) is not int or not 0<=x<=100 for x in vals):
            raise ValueError('DYNAMICS_INTEGER_PERIOD_SCORE_REQUIRED')
    if len(periods['home'])!=len(periods['away']):
        raise ValueError('DYNAMICS_CONFLICTING_PERIOD_LENGTH')


def _quart_stats(rows, side):
    if not rows:
        return dict(n=0, per_quarter_for=None, per_quarter_against=None,
                    full_for=None, full_against=None, observed_peak_quarter_frequency=None)
    for_key='for_quarters';against_key='against_quarters'
    def seq_stats(key):
        return [dict(mean=mean(r[key][q] for r in rows),
                     median=median(r[key][q] for r in rows),
                     sd=pstdev(r[key][q] for r in rows),
                     min=min(r[key][q] for r in rows),
                     max=max(r[key][q] for r in rows)) for q in range(4)]
    def full_stats(key):
        vals=[sum(r[key]) for r in rows]
        return dict(mean=mean(vals),median=median(vals),sd=pstdev(vals),
                    min=min(vals),max=max(vals))
    peaks=Counter()
    for row in rows:
        seq=row[for_key]
        m=max(seq)
        best=[q+1 for q,s in enumerate(seq) if s==m]
        if len(best)==1:
            peaks[str(best[0])+'Q']+=1
        else:
            peaks['TIED']+=1
    return dict(n=len(rows),per_quarter_for=seq_stats(for_key),
                per_quarter_against=seq_stats(against_key),
                full_for=full_stats(for_key),full_against=full_stats(against_key),
                observed_peak_quarter_frequency=dict(peaks),
                period_2_minus_period_1_mean=mean(r[for_key][1]-r[for_key][0] for r in rows),
                period_3_minus_period_2_mean=mean(r[for_key][2]-r[for_key][1] for r in rows))


def _team(team_id, all_rows, side):
    owned=[]
    for r in all_rows:
        if team_id not in (r['home_team_id'],r['away_team_id']):
            continue
        position='home' if r['home_team_id']==team_id else 'away'
        other='away' if position=='home' else 'home'
        owned.append(dict(fixture_id=r['fixture_id'],tipoff_utc=r['fixture_start_utc'],
                          source_catalog_sha256=r['source_catalog_sha256'],
                          available_at_utc=r['available_at_utc'],
                          venue=position,opponent_team_id=r[other+'_team_id'],
                          for_quarters=list(r['periods'][position][:4]),
                          against_quarters=list(r['periods'][other][:4])))
    owned.sort(key=lambda r:(r['tipoff_utc'],r['fixture_id']))
    by_venue={venue:_quart_stats([r for r in owned if r['venue']==venue],side)
              for venue in SIDES}
    by_opponent={k:_quart_stats([r for r in owned if r['opponent_team_id']==k],side)
                 for k in sorted({r['opponent_team_id'] for r in owned})}
    return dict(team_id=team_id,role_in_target=side,observations=len(owned),
                by_venue=by_venue,by_opponent=by_opponent,
                all_games=_quart_stats(owned,side),
                chronological_games=owned,
                no_team_pattern_imposed=True,
                current_5man_lineup_known=False,
                injuries_in_original_score_model=False,
                coach_impact_in_original_score_model=False,
                observed_team_behavior_not_fitted_future_projection=True)


def build(request, history, *, evidence_basis='DECLARED_NORMALIZED_NATIVE_RECORDS'):
    """Preserve individual, opponent and venue empirical records; do not predict."""
    _ids(request)
    if not isinstance(history,list) or len(history)>MAX_ROWS:
        raise ValueError('DYNAMICS_BOUNDED_HISTORY_REQUIRED')
    seen=set()
    for row in history:
        _source(row,request)
        if row['fixture_id'] in seen:
            raise ValueError('DYNAMICS_DUPLICATE_FIXTURE')
        seen.add(row['fixture_id'])
    history=sorted(history,key=lambda r:(r['fixture_start_utc'],r['fixture_id']))
    home=_team(request['home_team_id'],history,'home')
    away=_team(request['away_team_id'],history,'away')
    opponents=set([request['home_team_id'],request['away_team_id']])
    head2head=[r for r in history if {r['home_team_id'],r['away_team_id']}==opponents]
    all_used=[r for r in history if r['home_team_id'] in opponents or r['away_team_id'] in opponents]
    return dict(format=FORMAT,fixture_id=request['fixture_id'],
                league=request['league'],season=request['season'],
                decision_utc=request['decision_utc'],tipoff_utc=request['tipoff_utc'],
                scope='OBSERVED_PER_TEAM_EMPIRICAL_ONLY_NO_SCORE_FORECAST',
                evidence_basis=evidence_basis,
                inputs_sha256=digest(dict(request=request,history=history)),
                num_native_history_fixtures=len(all_used),
                original_head_to_head_count=len(head2head),
                target_home=home,target_away=away,
                no_universal_quarter_curve=True,no_hand_tuned_weighting=True,
                independent_pregame_player_coach_context_available=False,
                lineup_or_injury_impact_calculated=False,
                betting_direction_generated=False,confidence_calibrated=False,
                model_fitted=False,legacy_forecasts_changed=False,production_changed=False,
                warning='RETROSPECTIVE DESCRIPTION OF EACH TEAMS OWN PREDECISION MATCH HISTORY. NO PLAYER/COACH DATA IN THIS CORE PERIOD RECORD, NO VALIDATED PREDICTION, NO MARKET BETTING SIGNAL.')


def from_native_cut(cut):
    """Convert historical rows from actual strict `feature_cut` runtime provenance.

    Uses current Python witness capabilities, not arbitrary JSON witness claims.
    Consumers should use the returned evidence only, never backfit old picks.
    """
    from hybrid_engine.data import Cut,STRICT,available_at
    if not isinstance(cut,Cut) or cut.evaluation_class!=STRICT:
        raise ValueError('DYNAMICS_STRICT_NATIVE_CUT_REQUIRED')
    target=cut.target
    if (type(cut.cutoff_utc) is not int or not 0<cut.cutoff_utc<target['fixture_start_utc']):
        raise ValueError('DYNAMICS_INVALID_NATIVE_CUT_CLOCK')
    request=dict(league=target['league'],season=target['season'],
                 fixture_id=target['fixture_id'],home_team_id=target['home_team_id'],
                 away_team_id=target['away_team_id'],tipoff_utc=target['fixture_start_utc'],
                 decision_utc=cut.cutoff_utc)
    history=[]
    for r in cut.history:
        history.append(dict(league=r['league'],season=r['season'],fixture_id=r['fixture_id'],
                            fixture_start_utc=r['fixture_start_utc'],
                            home_team_id=r['home_team_id'],away_team_id=r['away_team_id'],
                            available_at_utc=available_at(r,STRICT),
                            source_catalog_sha256=r['source_catalog_sha256'],
                            periods=r['periods']))
    return build(request,history,evidence_basis='NATIVE_STRICT_CUT_CORE_AVAILABILITY_CHECKED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True)
    parser.add_argument('--history',required=True)
    args=parser.parse_args()
    def load(path):
        p=Path(path).expanduser()
        if p.is_symlink() or not p.is_file() or p.stat().st_size>16*1024*1024:
            raise ValueError('DYNAMICS_LOCAL_BOUNDED_JSON_REQUIRED')
        return json.loads(p.read_text())
    report=build(load(args.request),load(args.history))
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=='__main__':main()
