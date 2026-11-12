"""Unrounded arithmetic contract and explicit two-decimal display tolerances."""
import math

RAW_ABSOLUTE_TOLERANCE=1e-8
DISPLAY_TOLERANCES=dict(team_from_four_quarters=.025,total_from_eight_quarters=.045,
    half_from_two_quarters=.015,team_from_two_halves=.015,total_from_two_teams=.015)


def assert_projection(p):
    q=p['quarters'];h=p['halves']
    if isinstance(q,dict):
        quarters=[[q['home'][i],q['away'][i]] for i in range(4)]
        halves=[[h['home'][i],h['away'][i]] for i in range(2)]
    else:quarters=q;halves=h
    if len(quarters)!=4 or len(halves)!=2 or any(len(v)!=2 for v in list(quarters)+list(halves)):
        raise ValueError('FOUR_QUARTERS_TWO_HALVES_REQUIRED')
    values=[v for row in list(quarters)+list(halves) for v in row]+[p['home'],p['away'],p['total'],p['margin'],p['home_handicap']]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):raise ValueError('FINITE_PROJECTION_REQUIRED')
    if any(v<0 for row in quarters for v in row):raise ValueError('NONNEGATIVE_QUARTER_REQUIRED')
    def equal(a,b):
        if not math.isclose(a,b,abs_tol=RAW_ABSOLUTE_TOLERANCE,rel_tol=1e-12):raise ValueError('PROJECTION_ARITHMETIC_CONFLICT')
    for s,key in enumerate(('home','away')):
        equal(sum(v[s] for v in quarters),p[key]);equal(sum(v[s] for v in halves),p[key])
        for i in range(2):equal(sum(v[s] for v in quarters[2*i:2*i+2]),halves[i][s])
    equal(p['home']+p['away'],p['total']);equal(p['home']-p['away'],p['margin']);equal(-p['margin'],p['home_handicap'])
    return True
