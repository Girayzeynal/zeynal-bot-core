"""Experimental source-timed regulation features, independent of reference engines."""
from datetime import datetime,timezone
from statistics import fmean
import time

from period_feature_layer import select_available
from providers.espn_boxscore_pace import estimate_pace_from_summary
from prospective_error_audit import period_final
from prediction_inputs import digest

FEATURES=('home_offense','away_offense','home_defense','away_defense',
          'home_opponent_offense','away_opponent_offense','home_opponent_defense','away_opponent_defense',
          'home_pace','away_pace','home_home_away_effect','away_home_away_effect')


def _compute_features(records,target,cutoff,now):
    if target.get('provider')!='ESPN' or target['home_team_id']==target['away_team_id']:
        raise ValueError('resolved ESPN fixture required')
    selected=select_available(records,cutoff)
    facts=[]
    for record in selected:
        p=record['payload'];raw=p['original_summary']
        event=period_final(raw,p['source_observed_utc'])['event']
        estimate=estimate_pace_from_summary(raw,event,datetime.fromtimestamp(p['source_observed_utc'],timezone.utc))
        if estimate is None:continue
        pace=estimate['pace']
        facts.append(dict(record=record,home=p['home_team_id'],away=p['away_team_id'],pace=pace,
            home_off=100*p['regulation']['home']/pace,away_off=100*p['regulation']['away']/pace))
    missing=[];vector={};references=[]
    for side in ('home','away'):
        team=target[side+'_team_id'];games=[]
        for fact in facts:
            if team not in (fact['home'],fact['away']):continue
            home=team==fact['home'];opp=fact['away'] if home else fact['home']
            games.append(dict(off=fact['home_off'] if home else fact['away_off'],
                defense=fact['away_off'] if home else fact['home_off'],home=home,
                opp=opp,pace=fact['pace'],record=fact['record']))
        if len(games)<5:missing.append(side+':MIN_5_SOURCE_GAMES')
        home_games=[g['off'] for g in games if g['home']];away_games=[g['off'] for g in games if not g['home']]
        if min(len(home_games),len(away_games))<2:missing.append(side+':HOME_AWAY_SPLIT_MIN_2')
        opp_off=[];opp_def=[]
        for game in games:
            opponents=[f for f in facts if game['opp'] in (f['home'],f['away'])]
            if len(opponents)<2:continue
            opp_off.append(fmean(f['home_off'] if game['opp']==f['home'] else f['away_off'] for f in opponents))
            opp_def.append(fmean(f['away_off'] if game['opp']==f['home'] else f['home_off'] for f in opponents))
        if len(opp_off)!=len(games) or not games:missing.append(side+':OPPONENT_FORM_COVERAGE')
        if games and home_games and away_games and opp_off:
            vector.update({side+'_offense':fmean(g['off'] for g in games),
                side+'_defense':fmean(g['defense'] for g in games),
                side+'_opponent_offense':fmean(opp_off),side+'_opponent_defense':fmean(opp_def),
                side+'_pace':fmean(g['pace'] for g in games),
                side+'_home_away_effect':fmean(home_games)-fmean(away_games)})
            references.extend(g['record']['sha256'] for g in games)
    payload=dict(schema_version=1,feature_model='FAZ31_FORM_V1',target=target,cutoff_utc=cutoff,
        created_utc=now,available_utc=now,status='READY' if not missing else 'UNAVAILABLE',
        values=vector if not missing else None,feature_names=list(FEATURES),missing=missing,
        source_records=selected,source_record_sha256=sorted(set(references)),
        assumptions=['pace=0.44 box-score estimate, not measured possessions',
          'sample form and opponent means, not calibrated league ratings',
          'home-away difference is noisy observational association, not causal home advantage'],
        unavailable_optional=['VERIFIED_INJURIES','VERIFIED_ROSTERS','VERIFIED_MARKET','VERIFIED_RECOVERY'])
    return dict(payload=payload,sha256=digest(payload))


def make_features(records,target,cutoff):
    now=int(time.time())
    if type(cutoff) is not int or not 0<cutoff<=now<target['start_ts_utc']:
        raise ValueError('features must be created at actual pre-tipoff cutoff')
    if now>cutoff:raise ValueError('feature capture missed shared cutoff')
    return _compute_features(records,target,cutoff,now)


def replay_features(envelope):
    p=envelope['payload']
    if digest(p)!=envelope['sha256']:raise ValueError('feature digest mismatch')
    if (type(p['created_utc']) is not int or not 0<p['created_utc']<=p['cutoff_utc']<p['target']['start_ts_utc']
            or p['cutoff_utc']>int(time.time()) or p['created_utc']>int(time.time()) or p['available_utc']!=p['created_utc']):
        raise ValueError('feature availability chronology mismatch')
    expected=_compute_features(p['source_records'],p['target'],p['cutoff_utc'],p['created_utc'])
    if expected!=envelope:raise ValueError('feature semantic mismatch')
    return p
