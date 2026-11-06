"""Source-replayable, league-separated REGULATION research. Never live forecasts.

Quarter means are a transparent experimental baseline, not trained elite models.
No fabricated player/lineup/pace inputs or deployment coefficient changes.
"""
import math
from statistics import fmean,stdev

from faz40_archive import select_games,require,LEAGUES,MODES
from prediction_inputs import digest
from prematch_monte_carlo import PrematchSimulationInput,PrematchMonteCarloEngine

MODEL='FAZ40_REGULATION_QUARTER_MEAN_V1'
MISSING=('VERIFIED_PLAYER_MINUTES','VERIFIED_PLAYER_EFFICIENCY','LINEUP_STINTS',
         'ROTATION_EFFECTS','PLAY_BY_PLAY_GARBAGE_TIME','VERIFIED_INJURIES','MARKET_DATA',
         'PACE_NOT_USED_IN_THIS_MODEL')


def target_identity(f):
    return {k:f[k] for k in ('league','season_end_year','start_utc','home_team_id','away_team_id','canonical_id')}


def team_form(games,team,target_start):
    rows=[]
    for game in games:
        f=game['facts']
        if team not in (f['home_team_id'],f['away_team_id']):continue
        side='home' if team==f['home_team_id'] else 'away';other='away' if side=='home' else 'home'
        rows.append(dict(start=f['start_utc'],home=side=='home',q=f['quarters_'+side],
                         against=f['quarters_'+other],opponent=f[other+'_team_id']))
    if not rows:return dict(games=0,values=None)
    own=[sum(r['q']) for r in rows];conceded=[sum(r['against']) for r in rows]
    deficits=[r for r in rows if sum(r['q'][:2])<sum(r['against'][:2])]
    home=[sum(r['q']) for r in rows if r['home']];away=[sum(r['q']) for r in rows if not r['home']]
    opponent_values=[]
    for row in rows:
        opponent_games=[g['facts'] for g in games if row['opponent'] in
                        (g['facts']['home_team_id'],g['facts']['away_team_id'])]
        opponent_values.extend(g['regulation_home'] if row['opponent']==g['home_team_id'] else g['regulation_away']
                               for g in opponent_games)
    return dict(games=len(rows),values=dict(
        quarter_for=[fmean(r['q'][i] for r in rows) for i in range(4)],
        quarter_against=[fmean(r['against'][i] for r in rows) for i in range(4)],
        regulation_for=fmean(own),regulation_against=fmean(conceded),
        observed_score_std=stdev(own) if len(own)>=2 else None,
        second_half_delta_mean=fmean(sum(r['q'][2:])-sum(r['q'][:2]) for r in rows),
        halftime_deficit_games=len(deficits),
        halftime_deficit_to_regulation_win_rate=(sum(sum(r['q'])>sum(r['against']) for r in deficits)/len(deficits)) if deficits else None,
        home_away_scoring_difference=fmean(home)-fmean(away) if min(len(home),len(away))>=2 else None,
        opponent_scoring_form=fmean(opponent_values) if opponent_values else None,
        hours_since_previous_tipoff=(target_start-max(r['start'] for r in rows))/3600,
        games_in_previous_7_days=sum(target_start-7*86400<=r['start']<target_start for r in rows)))


def project(records,target,cutoff_utc,*,mode='INGESTION_TIME',minimum_team_games=5,
            simulations=10000,seed=20261106,score_correlation=0.0):
    require(type(target) is dict and set(target)==set('league season_end_year start_utc home_team_id away_team_id canonical_id'.split()),'TARGET_MUST_NOT_CONTAIN_LABELS')
    require(target['league'] in LEAGUES and type(target['start_utc']) is int and
            type(cutoff_utc) is int and cutoff_utc<target['start_utc'],'PRESTART_CUTOFF_REQUIRED')
    require(target['home_team_id']!=target['away_team_id'],'DISTINCT_TEAMS_REQUIRED')
    identity={k:v for k,v in target.items() if k!='canonical_id'}
    require(digest(identity)==target['canonical_id'],'TARGET_CANONICAL_ID_MISMATCH')
    require(type(minimum_team_games) is int and minimum_team_games>=2,'INVALID_TEAM_SAMPLE_THRESHOLD')
    require(type(simulations) is int and simulations>=10000 and type(seed) is int,'MINIMUM_10000_SIMULATIONS_REQUIRED')
    games=select_games(records,league=target['league'],season_end_year=target['season_end_year'],cutoff_utc=cutoff_utc,mode=mode)
    require(all(g['facts']['start_utc']<cutoff_utc and g['available_utc']<cutoff_utc for g in games),'FEATURE_CUTOFF_LEAK')
    forms={side:team_form(games,target[side+'_team_id'],target['start_utc']) for side in ('home','away')}
    base=dict(model=MODEL,target=target,cutoff_utc=cutoff_utc,scope='REGULATION_ONLY',
              usage='SYNTHETIC_TEST' if games and games[0]['usage']=='SYNTHETIC_TEST' else 'RETROSPECTIVE_RESEARCH',
              availability_policy=mode,team_features=forms,missing=list(MISSING),calibration_status='NOT_ESTABLISHED',
              source_game_ids=[g['facts']['canonical_id'] for g in games],
              source_observation_sha256=sorted({h for g in games for h in g['observation_sha256']}),
              source_universe_sha256=digest(games),production_coefficients_changed=False)
    if any(f['games']<minimum_team_games for f in forms.values()):
        return dict(base,status='ABSTAIN_INSUFFICIENT_HISTORY',prediction=None,simulation=None)
    hv,av=forms['home']['values'],forms['away']['values']
    if any(v['observed_score_std'] is None or v['observed_score_std']<=0 for v in (hv,av)):
        return dict(base,status='ABSTAIN_DEGENERATE_VARIANCE',prediction=None,simulation=None)
    quarters={side:[(forms[side]['values']['quarter_for'][i]+forms['away' if side=='home' else 'home']['values']['quarter_against'][i])/2 for i in range(4)]
              for side in ('home','away')}
    prediction={side:dict(quarters=q,first_half=sum(q[:2]),second_half=sum(q[2:]),total=sum(q)) for side,q in quarters.items()}
    prediction.update(total=prediction['home']['total']+prediction['away']['total'],
                      home_margin=prediction['home']['total']-prediction['away']['total'])
    actual_seed=int(digest(dict(seed=seed,game=target['canonical_id']))[:16],16)
    sim=PrematchMonteCarloEngine().simulate(PrematchSimulationInput(
        home_mean=prediction['home']['total'],away_mean=prediction['away']['total'],
        home_std=hv['observed_score_std'],away_std=av['observed_score_std'],
        score_correlation=score_correlation,simulations=simulations,seed=actual_seed))
    result=dict(simulations=sim.simulations,seed=sim.seed,score_correlation=score_correlation,
                variance_method='OBSERVED_TEAM_SCORE_STD_NOT_RESIDUAL_CALIBRATION',
                probabilities=[sim.home_regulation_win_probability,sim.away_regulation_win_probability,sim.regulation_tie_probability],
                outcome_order=['HOME_REGULATION_WIN','AWAY_REGULATION_WIN','REGULATION_TIE'],
                total_quantiles=sim.total_quantiles,expected_total=sim.expected_total,
                home_std=hv['observed_score_std'],away_std=av['observed_score_std'],
                sampling_diagnostics=sim.sampling_diagnostics)
    return dict(base,status='PROJECTED_RESEARCH',prediction=prediction,simulation=result,
                assumptions=['Quarter matchup arithmetic means; no causal opponent/fatigue correction fitted',
                             'Tipoff spacing is a schedule proxy, not measured rest/recovery',
                             'Match-level Monte Carlo only; engine period allocations are not quarter forecasts'])


def metrics(rows,*,minimum_games=30):
    require(type(minimum_games) is int and minimum_games>=2,'INVALID_EVALUATION_THRESHOLD')
    require(type(rows) is list,'EVALUATION_ROWS_REQUIRED')
    if not rows:return None
    require(len({(r['league'],r['season_end_year'],r['scope'],r['model'],r['usage']) for r in rows})==1,'MIXED_EVALUATION_COHORTS')
    require(len({r['canonical_id'] for r in rows})==len(rows),'DUPLICATE_EVALUATION_GAME')
    for row in rows:
        require(row['league'] in LEAGUES and row['model']==MODEL and row['scope']=='REGULATION_ONLY' and
                row['usage'] in ('SYNTHETIC_TEST','RETROSPECTIVE_RESEARCH'),'INVALID_EVALUATION_IDENTITY')
        require(all(type(row[k]) is int and row[k]>0 for k in ('cutoff_utc','start_utc','result_observed_utc')) and
                row['cutoff_utc']<row['start_utc']<row['result_observed_utc'],'INVALID_EVALUATION_CHRONOLOGY')
        require(all(type(row[k]) in (int,float) and math.isfinite(row[k]) and row[k]>=0 for k in
                    ('expected_home','expected_away')) and
                all(type(row[k]) is int and row[k]>=0 for k in ('actual_home','actual_away')),'INVALID_EVALUATION_SCORES')
        p=row['probabilities']
        require(type(p) is list and len(p)==3 and all(type(v) in (float,int) and math.isfinite(v) and 0<=v<=1 for v in p)
                and abs(sum(p)-1)<1e-10,'INVALID_REGULATION_PROBABILITIES')
    if len(rows)<minimum_games:return None
    result=dict(games=len(rows),calibration_status='NOT_ESTABLISHED',statistical_superiority_claimed=False)
    for name,errors in [('home',[r['expected_home']-r['actual_home'] for r in rows]),
                        ('away',[r['expected_away']-r['actual_away'] for r in rows]),
                        ('total',[(r['expected_home']+r['expected_away'])-(r['actual_home']+r['actual_away']) for r in rows]),
                        ('margin',[(r['expected_home']-r['expected_away'])-(r['actual_home']-r['actual_away']) for r in rows])]:
        result[name+'_mae']=fmean(abs(e) for e in errors)
        result[name+'_rmse']=math.sqrt(fmean(e*e for e in errors))
    brier=[];loss=[];bins=[[] for _ in range(10)]
    for row in rows:
        p=row['probabilities'];h,a=row['actual_home'],row['actual_away'];index=0 if h>a else 1 if h<a else 2
        brier.append(sum((v-float(i==index))**2 for i,v in enumerate(p)))
        loss.append(-math.log(max(p[index],1e-15)))
        bins[min(9,int(p[0]*10))].append((p[0],float(index==0)))
    result.update(multiclass_brier=fmean(brier),multiclass_log_loss=fmean(loss),
                  home_event_calibration_bins=[dict(n=len(b),predicted=fmean(p for p,y in b),observed=fmean(y for p,y in b)) if b else dict(n=0,predicted=None,observed=None) for b in bins],
                  home_event_ece=sum(len(b)/len(rows)*abs(fmean(p for p,y in b)-fmean(y for p,y in b)) for b in bins if b))
    return result


def walk_forward(records,*,league,season_end_year,mode='INGESTION_TIME',minimum_team_games=5,
                 minimum_evaluation_games=30,simulations=10000,seed=20261106,score_correlation=0.0):
    require(league in LEAGUES and type(season_end_year) is int and 2001<=season_end_year<=2100,
            'INVALID_RESEARCH_PARTITION')
    require(mode in MODES and type(minimum_team_games) is int and minimum_team_games>=2 and
            type(minimum_evaluation_games) is int and minimum_evaluation_games>=2,'INVALID_RESEARCH_CONFIGURATION')
    require(type(simulations) is int and simulations>=10000 and type(seed) is int,'MINIMUM_10000_SIMULATIONS_REQUIRED')
    # Export labels by canonical identity; future labels are never sent as targets.
    require(type(records) is list,'ARCHIVE_LIST_REQUIRED')
    if not records:return dict(status='NO_ARCHIVE',evaluated_games=0,metrics=None,folds=[],prospective_records_created=0)
    import time
    labels=select_games(records,league=league,season_end_year=season_end_year,cutoff_utc=int(time.time()),mode='ARCHIVED_SOURCE_CLOCK')
    folds=[];rows=[]
    for item in labels:
        f=item['facts'];target=target_identity(f);cutoff=f['start_utc']-1
        out=project(records,target,cutoff,mode=mode,minimum_team_games=minimum_team_games,simulations=simulations,seed=seed,score_correlation=score_correlation)
        fold=dict(canonical_id=f['canonical_id'],target=target,provider_aliases=item['provider_aliases'],start_utc=f['start_utc'],cutoff_utc=cutoff,
                  status=out['status'],source_game_ids=out['source_game_ids'],
                  source_observation_sha256=out['source_observation_sha256'])
        if out['prediction'] is not None:
            p=out['prediction'];row=dict(canonical_id=f['canonical_id'],league=league,season_end_year=season_end_year,
                scope='REGULATION_ONLY',model=MODEL,usage=item['usage'],expected_home=p['home']['total'],expected_away=p['away']['total'],
                actual_home=f['regulation_home'],actual_away=f['regulation_away'],probabilities=out['simulation']['probabilities'],
                cutoff_utc=cutoff,start_utc=f['start_utc'],result_observed_utc=item['available_utc'])
            rows.append(row);fold.update(prediction=p,simulation=out['simulation'],actual_regulation=dict(home=f['regulation_home'],away=f['regulation_away']),
                home_error=p['home']['total']-f['regulation_home'],away_error=p['away']['total']-f['regulation_away'],
                total_error=p['total']-f['regulation_home']-f['regulation_away'],
                margin_error=p['home_margin']-(f['regulation_home']-f['regulation_away']),
                error_diagnosis='DESCRIPTIVE_ONLY_NO_CAUSAL_INJURY_LINEUP_OR_GARBAGE_TIME_ATTRIBUTION')
        folds.append(fold)
    evaluated=metrics(rows,minimum_games=minimum_evaluation_games)
    return dict(status='RESEARCH_EVALUATED' if evaluated is not None else 'INSUFFICIENT_EVALUATION_SAMPLE',
        model=MODEL,league=league,season_end_year=season_end_year,availability_policy=mode,
        usage=labels[0]['usage'] if labels else 'RETROSPECTIVE_RESEARCH',input_games=len(labels),evaluated_games=len(rows),
        minimum_evaluation_games=minimum_evaluation_games,metrics=evaluated,folds=folds,
        source_attestation='NOT_INDEPENDENTLY_VERIFIED',calibration_status='NOT_ESTABLISHED',
        parameters_fitted=False,production_coefficients_changed=False,prospective_records_created=0,missing=list(MISSING))
