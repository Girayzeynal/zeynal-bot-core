"""Prospective native calendar witnesses and a separately fitted context ablation.

Start-to-start gap is not measured physiological rest; geodesic venue distance
is not an observed itinerary. Missing coordinates never become zero travel.
"""
from datetime import datetime,timedelta
import math
import time
from zoneinfo import ZoneInfo

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.distributions import Forecast
from hybrid_engine.nba_dynamic import _vector
from season_archive_inventory import archive_catalog

PREFIX='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='


def urls(target):
    day=datetime.fromtimestamp(target['fixture_start_utc'],ZoneInfo('America/New_York')).date()
    return [PREFIX+(day-timedelta(days=i)).strftime('%Y%m%d')+'&limit=1000' for i in range(8)]


def _coordinates(venue):
    raw=venue.get('location') or {};lat=raw.get('latitude');lon=raw.get('longitude')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (lat,lon)):return None
    if not -90<=lat<=90 or not -180<=lon<=180:return None
    return (lat,lon)


def _distance(a,b):
    la,lo=map(math.radians,a);lb,lob=map(math.radians,b)
    v=math.sin((lb-la)/2)**2+math.cos(la)*math.cos(lb)*math.sin((lob-lo)/2)**2
    return 6371*2*math.asin(math.sqrt(min(1,max(0,v))))


def capture(target,receipts,*,asof_utc=None):
    # Optional historical decoding is read-only; publication still uses actual
    # wall time in the immutable registry and can never be backdated here.
    actual=int(time.time());now=actual if asof_utc is None else asof_utc;expected=urls(target)
    if type(now) is not int or not 0<now<=actual:raise ValueError('SCHEDULE_ACTUAL_OR_EARLIER_DECODE_CLOCK')
    if target['league']!='NBA' or now>=target['fixture_start_utc']-900:raise Abstain('SCHEDULE_NBA_PREMATCH_WINDOW_REQUIRED')
    if len(receipts)!=8 or {r.get('source_url') for r in receipts}!=set(expected):raise Abstain('SCHEDULE_EIGHT_NATIVE_CALENDAR_DAYS_REQUIRED')
    games={};venues={};states={}
    for r in receipts:
        if (r.get('provider')!='ESPN' or r.get('http_status')!=200 or r.get('status')!='DOCUMENT_RECEIVED' or
            r.get('document_sha256')!=digest(r['document']) or
            any(type(r.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
            not 0<r['observed_at_utc']<=r['ingested_at_utc']<=now or now-r['observed_at_utc']>300):
            raise Abstain('SCHEDULE_FRESH_NATIVE_RECEIPTS_REQUIRED')
        c=archive_catalog(r['document'],provider='ESPN',season_start_year=int(target['season'].split('/')[0]),
            observed_at_utc=r['observed_at_utc'],ingested_at_utc=r['ingested_at_utc'],regular_season_filter=True)
        for g in c['payload']['fixtures']:
            key=g['canonical_id']
            if key in games and games[key]!=g:raise ValueError('SCHEDULE_CONFLICTING_NATIVE_FIXTURE')
            games[key]=g
        for event in r['document']['events']:
            day=datetime.fromisoformat(event['date'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).strftime('%Y%m%d')
            if day!=r['source_url'].split('dates=')[1].split('&')[0]:raise ValueError('SCHEDULE_NATIVE_CALENDAR_DATE_CONFLICT')
            competitions=event['competitions']
            if len(competitions)!=1:raise ValueError('SCHEDULE_SINGLE_NATIVE_COMPETITION')
            q=competitions[0];venues[str(event['id'])]=_coordinates(q.get('venue',{}))
            states[str(event['id'])]=(q.get('status',event.get('status',{})).get('type',{}).get('name'),
                [float(t.get('score',0)) for t in q['competitors']])
    g=games.get(target['fixture_id'])
    if g is None or g['completed'] or any(g[k]!=target[t] for k,t in
        (('start_ts_utc','fixture_start_utc'),('home_team_id','home_team_id'),('away_team_id','away_team_id'))):
        raise Abstain('SCHEDULE_EXACT_UNSTARTED_TARGET_REQUIRED')
    state,scores=states[g['provider_fixture_ids'][0]]
    if state!='STATUS_SCHEDULED' or any(v!=0 for v in scores):raise Abstain('SCHEDULE_EXACT_SCHEDULED_ZERO_SCORE_REQUIRED')
    current=venues.get(g['provider_fixture_ids'][0]);values={}
    for side in ('home','away'):
        tid=target[side+'_team_id'];prior=[p for p in games.values() if p['completed'] and p['start_ts_utc']<g['start_ts_utc'] and tid in (p['home_team_id'],p['away_team_id'])]
        if not prior:raise Abstain('SCHEDULE_PREVIOUS_TEAM_GAME_NOT_IN_VERIFIED_WINDOW')
        previous=max(prior,key=lambda p:p['start_ts_utc']);last=venues.get(previous['provider_fixture_ids'][0])
        a=datetime.fromtimestamp(previous['start_ts_utc'],ZoneInfo('America/New_York')).date()
        b=datetime.fromtimestamp(g['start_ts_utc'],ZoneInfo('America/New_York')).date()
        values[side]=dict(start_gap_hours=(g['start_ts_utc']-previous['start_ts_utc'])/3600,
            back_to_back_calendar_days=(b-a).days==1,previous_fixture_id=previous['canonical_id'],
            venue_geodesic_km=None if current is None or last is None else _distance(last,current))
    p=dict(format='PROSPECTIVE_NBA_SCHEDULE_CONTEXT_V1',target=target,observed_at_utc=now,
        source_available_max_utc=max(r['ingested_at_utc'] for r in receipts),source_receipt_sha256s=[digest(r) for r in receipts],
        values=values,actual_itinerary_observed=False,physiological_rest_measured=False,
        player_effects=False,production_enabled=False)
    return dict(payload=p,sha256=digest(p))


def _features(context,side,travel):
    a=context['values'][side];b=context['values']['away' if side=='home' else 'home']
    values=[min(168.,a['start_gap_hours'])/48-1,float(a['back_to_back_calendar_days']),
            min(168.,b['start_gap_hours'])/48-1,float(b['back_to_back_calendar_days'])]
    if travel:
        if a['venue_geodesic_km'] is None or b['venue_geodesic_km'] is None:raise Abstain('SCHEDULE_NATIVE_VENUE_COORDINATES_UNAVAILABLE')
        values.extend([a['venue_geodesic_km']/1000,b['venue_geodesic_km']/1000])
    return values


def fit(base,contexts):
    """Context coefficients use only prospectively captured, later settled rows.

    This is an exploratory residual-rate ablation, not the registered V3 primary.
    All actual player/PBP effects remain in their independent, guarded studies.
    """
    p=base['payload']
    if digest(p)!=base['sha256']:raise ValueError('SCHEDULE_BASE_MODEL_PIN')
    rows={r['fixture_id']:r for r in p['training']};selected=[]
    for w in contexts:
        c=w['payload'];t=c['target'];r=rows.get(t['fixture_id'])
        if digest(c)!=w['sha256']:raise ValueError('SCHEDULE_CONTEXT_PIN')
        if r is None:continue
        if (c['format']!='PROSPECTIVE_NBA_SCHEDULE_CONTEXT_V1' or t['season']!=p['season'] or
            not 0<c['source_available_max_utc']<=c['observed_at_utc']<t['fixture_start_utc']-900 or
            t['fixture_start_utc']!=r['start'] or t['home_team_id']!=r['home'] or t['away_team_id']!=r['away']):
            raise ValueError('SCHEDULE_CONTEXT_IDENTITY_OR_PREMATCH_CLOCK')
        selected.append((r,c))
    if len({r['fixture_id'] for r,c in selected})!=len(selected):raise ValueError('SCHEDULE_DUPLICATE_CONTEXT')
    if len(selected)<30:raise Abstain('SCHEDULE_THIRTY_PROSPECTIVE_LABELED_CONTEXTS_REQUIRED')
    travel=all(c['values'][s]['venue_geodesic_km'] is not None for r,c in selected for s in ('home','away'))
    x=[];y=[]
    for r,c in selected:
        for j,(s,o) in enumerate((('home','away'),('away','home'))):
            v=_vector(p['teams'],r[s],r[o],s=='home');rate=float(v@np.asarray(p['coefficients']))
            x.append(_features(c,s,travel));y.append(100*np.asarray(r['quarters'])[:,j].sum()/r['pace']-rate)
    x=np.asarray(x);y=np.asarray(y)
    # Missing or constant schedule exposure is not evidence of a fitted effect.
    active=np.flatnonzero(np.std(x,axis=0)>1e-6)
    if len(active)==0:raise Abstain('SCHEDULE_EXPOSURE_VARIATION_REQUIRED')
    z=x[:,active];precision=z.T@z/100+np.eye(len(active));cov=np.linalg.inv(precision)
    coef=np.linalg.solve(precision,z.T@y/100)
    body=dict(format='EXPLORATORY_NBA_SCHEDULE_RATE_ABLATION_V1',base_sha256=base['sha256'],
        training_ids=sorted(r['fixture_id'] for r,c in selected),fit_at_utc=int(time.time()),
        active_columns=active.tolist(),coefficients=coef.tolist(),covariance=cov.tolist(),
        calendar_gap_fitted=any(i in (0,2) for i in active),
        calendar_b2b_fitted=any(i in (1,3) for i in active),
        venue_distance_proxy_fitted=travel and any(i in (4,5) for i in active),actual_itinerary_fitted=False,
        travel_columns_present=travel,
        production_enabled=False)
    return dict(payload=body,sha256=digest(body))


def predict(base,model,forecast,context):
    p=model['payload'];c=context['payload'];now=int(time.time())
    if digest(p)!=model['sha256'] or digest(c)!=context['sha256'] or p['base_sha256']!=base['sha256']:
        raise ValueError('SCHEDULE_ABLATION_MODEL_AND_CONTEXT_PIN')
    if (c['target']['fixture_id'] in p['training_ids'] or
        not max(p['fit_at_utc'],c['observed_at_utc'])<=now<c['target']['fixture_start_utc']-900):
        raise Abstain('SCHEDULE_ABLATION_FUTURE_PREMATCH_REQUIRED')
    if (c['target']['league'],c['target']['season'])!=('NBA',base['payload']['season']):raise ValueError('SCHEDULE_ABLATION_TARGET_COHORT')
    x=np.asarray([_features(c,s,p['travel_columns_present']) for s in ('home','away')])[:,p['active_columns']]
    pace=forecast.metadata['box_pace'];shift=(x@np.asarray(p['coefficients']))*pace/100
    cov=x@np.asarray(p['covariance'])@x.T*(pace/100)**2
    profile=forecast.quarter_means/forecast.scores
    rng=np.random.default_rng(20261118);noise=rng.standard_normal((len(forecast.samples),2))@np.linalg.cholesky(cov+np.eye(2)*1e-9).T
    samples=np.maximum(0,np.rint(forecast.samples+profile[None,:,:]*(shift+noise)[:,None,:])).astype(np.int32)
    means=forecast.quarter_means+profile*shift
    if np.any(means<0):raise Abstain('SCHEDULE_ABLATION_SCORE_OUT_OF_RANGE')
    return Forecast('NBA_SCHEDULE_PROXY_ABLATION_V1',means,samples=samples,
        metadata=dict(forecast.metadata,calendar_gap_fitted=p['calendar_gap_fitted'],calendar_b2b_fitted=p['calendar_b2b_fitted'],
            venue_distance_proxy_fitted=p['venue_distance_proxy_fitted'],actual_itinerary_fitted=False,
            physiological_rest_measured=False,context_model_sha256=model['sha256'],
            ablation='EXPLORATORY_RESIDUAL_RATE_MODEL_NOT_REGISTERED_PRIMARY',method='PRIMARY_RQMC_PLUS_CONTEXT_PARAMETER_MC'))
