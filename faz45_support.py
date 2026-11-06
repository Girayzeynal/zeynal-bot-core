"""Point-in-time player/PBP research joined to replayed score observations.

No forecast, fitting, future roster inference, coefficient changes or storage.
Historical boxscore starters never become a prematch lineup. Local hashes are
integrity evidence, not independent provider/permission/time attestations.
"""
from collections import Counter,defaultdict
from copy import deepcopy
from statistics import fmean
import time

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import REGISTRY,REGISTRY_PIN,_fixture
from faz41_adapters import normalize
from faz42_history import _validated
from faz41_faz40 import historical_player_features
from faz43_pbp import replay_timeline

KINDS=('PLAYER_MINUTES','PBP_TIMELINE')
SCORE_FIELDS=('quarters_home','quarters_away','overtime_home','overtime_away',
              'regulation_home','regulation_away','final_home','final_away')


def kind(observation):
    p=observation['payload']
    if p['data_type']=='PLAYER_MINUTES':return 'PLAYER_MINUTES'
    require(p['raw'].get('format')=='FAZ43_ESPN_TIMELINE_V1','UNSUPPORTED_SUPPORT_OBSERVATION')
    return 'PBP_TIMELINE'


def validate_support(scores,observations,*,asof_utc,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    """Reuse score/player global identity and source replay guards unchanged."""
    require(type(scores) is list and type(observations) is list,'SUPPORT_LISTS_REQUIRED')
    require(all(o['payload']['data_type']=='OFFICIAL_STAT' for o in scores),'SCORE_INPUTS_ONLY')
    base=_validated(scores,asof_utc,registry,registry_pin)
    minutes=[o for o in observations if kind(o)=='PLAYER_MINUTES']
    rows=_validated(scores+minutes,asof_utc,registry,registry_pin)
    categories={p['usage']=='SYNTHETIC_TEST' for o,p in rows}
    games={};score_refs=defaultdict(list)
    for o,p in base:games[p['fixture']['canonical_id']]=p;score_refs[p['fixture']['canonical_id']].append(o)
    auxiliary=[(o,p,'PLAYER_MINUTES') for o,p in rows[len(base):]]
    for o in observations:
        if kind(o)!='PBP_TIMELINE':continue
        p=replay_timeline(o,fixture=o['payload']['fixture'],cutoff_utc=asof_utc,
            maximum_age_seconds=100*366*86400,require_permitted=False,registry=registry,registry_pin=registry_pin)
        categories.add(p['usage']=='SYNTHETIC_TEST');auxiliary.append((o,p,'PBP_TIMELINE'))
    require(len(categories)<=1,'MIXED_SYNTHETIC_REAL_SUPPORT')
    aliases={(p['provider'],p['provider_fixture_id']):p['fixture']['canonical_id'] for o,p in base}
    seen={};linked=[];unmatched=[]
    for o,p,k in auxiliary:
        cid=p['fixture']['canonical_id'];score=games.get(cid)
        alias=(p['provider'],p['provider_fixture_id'])
        require(alias not in aliases or aliases[alias]==cid,'SUPPORT_PROVIDER_FIXTURE_ID_CONFLICT');aliases[alias]=cid
        if score is None:unmatched.append(o['sha256']);continue
        if k=='PLAYER_MINUTES':
            raw=p['raw']['game'] if p['provider']=='EUROLEAGUE_LIVE' else p['raw']
            n=normalize(raw,provider=p['provider'],league=p['fixture']['league'],season_end_year=p['fixture']['season_end_year'],
                        observed_at_utc=p['observed_at_utc'],data_type='OFFICIAL_STAT')
            claims=n['claims']
        else:
            n=normalize(p['raw']['summary'],provider='ESPN',league='NBA',season_end_year=p['fixture']['season_end_year'],
                        observed_at_utc=p['observed_at_utc'],data_type='OFFICIAL_STAT');claims=n['claims']
        require(n['fixture']==score['fixture'] and all(claims[f]==score['claims'][f] for f in SCORE_FIELDS),'AUXILIARY_SCORE_CONFLICT')
        key=(cid,k,p['provider']);prior=seen.get(key)
        require(prior is None or prior['claims']==p['claims'],'CONFLICTING_SUPPORT_REOBSERVATIONS');seen[key]=p
        linked.append((o,p,k,score_refs[cid]))
    return linked,unmatched


def _permission(p,cutoff,registry):
    policy=registry[p['provider']]
    return policy['usage']=='PERMITTED' and policy['reviewed_at_utc']<cutoff<=policy['expires_at_utc']


def _available(p,cutoff,age):
    return all(p[f]<cutoff for f in ('observed_at_utc','ingested_at_utc','materialized_at_utc')) and cutoff-p['observed_at_utc']<=age


def _player_features(games,team,limit):
    selected=sorted(games,key=lambda x:(x[1]['fixture']['start_utc'],x[1]['fixture']['canonical_id']))[-limit:]
    by_player=defaultdict(list);precisions=Counter();starts=[];overtime=0
    for o,p,score in selected:
        starts.append(p['fixture']['start_utc']);overtime+=bool(score['payload']['claims']['overtime_home'])
        for row in p['claims']['teams'][team]:
            if row.get('did_not_play',False):continue
            require(row['minutes'] is not None,'REPORTED_MINUTES_REQUIRED')
            by_player[row['player_id']].append(row);precisions[row['minutes_precision']]+=1
    return dict(games=len(selected),canonical_game_ids=[p['fixture']['canonical_id'] for o,p,s in selected],
        source_sha256=[dict(player=o['sha256'],score=s['sha256']) for o,p,s in selected],
        last_game_start_utc=max(starts),overtime_games=overtime,scope='FINAL_WITH_OT_NOT_REGULATION_PLAYER_SPLIT',
        minute_precision_counts=dict(precisions),reported_minutes_are_exact_seconds=all(k in ('SOURCE_SECONDS','SECOND_DISPLAY') for k in precisions),
        players=[dict(player_id=pid,appearances=len(rows),reported_minutes_sum=sum(r['minutes'] for r in rows),
            reported_minutes_mean=fmean(r['minutes'] for r in rows),points_sum=sum(r['points'] for r in rows),
            historical_starts=sum(r.get('historical_starter',False) for r in rows),
            historical_starter_status='SOURCE_REPORTED' if all('historical_starter' in r for r in rows) else 'NOT_AVAILABLE')
            for pid,rows in sorted(by_player.items())],
        usage='DESCRIPTIVE_RESEARCH_ONLY_NOT_PLAYER_STRENGTH_OR_FUTURE_ROSTER')


def support_report(scores,observations,fixture,*,cutoff_utc,minimum_team_games=3,last_games=10,
                   maximum_age_seconds=120*86400,registry=REGISTRY,registry_pin=REGISTRY_PIN):
    """Retrospective as-of research; never a live or persisted prediction."""
    _fixture(fixture);now=int(time.time())
    require(type(cutoff_utc) is int and 0<cutoff_utc<=now and cutoff_utc<fixture['start_utc'],'SUPPORT_PREMATCH_CUTOFF_REQUIRED')
    require(type(minimum_team_games) is int and type(last_games) is int and 1<=minimum_team_games<=last_games<=30 and
        type(maximum_age_seconds) is int and maximum_age_seconds>0,'SUPPORT_WINDOW_REQUIRED')
    linked,unmatched=validate_support(scores,observations,asof_utc=now,registry=registry,registry_pin=registry_pin)
    excluded=Counter();usable={k:{} for k in KINDS};matched={k:set() for k in KINDS}
    for o,p,k,score_refs in linked:
        f=p['fixture'];cid=f['canonical_id'];matched[k].add(cid)
        if (f['league'],f['season_end_year'])!=(fixture['league'],fixture['season_end_year']):excluded['OTHER_PARTITION']+=1;continue
        if cid==fixture['canonical_id'] or f['start_utc']>=cutoff_utc:excluded['TARGET_OR_FUTURE_RESULT']+=1;continue
        if not _available(p,cutoff_utc,maximum_age_seconds):excluded['AUXILIARY_NOT_AVAILABLE_AT_CUTOFF']+=1;continue
        refs=[s for s in score_refs if _available(s['payload'],cutoff_utc,maximum_age_seconds)]
        if not refs:excluded['SCORE_NOT_AVAILABLE_AT_CUTOFF']+=1;continue
        if not _permission(p,cutoff_utc,registry):excluded['SOURCE_PERMISSION_NOT_ESTABLISHED']+=1;continue
        refs=[s for s in refs if _permission(s['payload'],cutoff_utc,registry)]
        if not refs:excluded['SCORE_PERMISSION_NOT_ESTABLISHED']+=1;continue
        score=sorted(refs,key=lambda s:(s['payload']['materialized_at_utc'],s['sha256']))[0]
        key=cid
        prior=usable[k].get(key)
        # Player namespaces from two providers are never silently cross-mapped.
        require(prior is None or prior[1]['provider']==p['provider'],'PLAYER_PROVIDER_CROSSWALK_REQUIRED')
        if prior is None or (p['materialized_at_utc'],o['sha256'])>(prior[1]['materialized_at_utc'],prior[0]['sha256']):usable[k][key]=(o,p,score)
    teams={}
    for side in ('home','away'):
        team=fixture[side+'_team_id'];minutes=[v for v in usable['PLAYER_MINUTES'].values() if team in v[1]['claims']['teams']]
        timeline=[v for v in usable['PBP_TIMELINE'].values() if team in (v[1]['fixture']['home_team_id'],v[1]['fixture']['away_team_id'])]
        minute=dict(status='ABSTAIN_INSUFFICIENT_PLAYER_GAMES',eligible_games=len(minutes),features=None)
        if len(minutes)>=minimum_team_games:
            context=historical_player_features([v[0] for v in minutes],target=fixture,cutoff_utc=cutoff_utc,
                maximum_age_seconds=maximum_age_seconds,registry=registry,registry_pin=registry_pin)
            minute.update(status='DESCRIPTIVE_FEATURES_AVAILABLE',features=_player_features(minutes,team,last_games),
                          target_roster_status=context['target_roster_status'],rotation_effect=context['rotation_effect'],player_efficiency=context['player_efficiency'])
        pbp=dict(status='ABSTAIN_INSUFFICIENT_PBP_GAMES',eligible_games=len(timeline),features=None)
        if len(timeline)>=minimum_team_games:
            selected=sorted(timeline,key=lambda v:(v[1]['fixture']['start_utc'],v[1]['fixture']['canonical_id']))[-last_games:]
            changes=[];comebacks=0
            for o,p,score in selected:
                c=p['claims'];home=p['fixture']['home_team_id']==team;sign=1 if home else -1
                first=c['halftime_home']-c['halftime_away'];final=c['regulation_home']-c['regulation_away']
                changes.append(sign*(final-2*first));comebacks+=c['regulation_comeback']==('HOME' if home else 'AWAY')
            pbp.update(status='DESCRIPTIVE_FEATURES_AVAILABLE',features=dict(games=len(selected),
                source_sha256=[dict(timeline=o['sha256'],score=s['sha256']) for o,p,s in selected],
                second_half_minus_first_half_margin_mean=fmean(changes),regulation_comebacks=comebacks,
                garbage_rule_events=sum(p['claims']['garbage_rule_events'] for o,p,s in selected),
                garbage_rule='DESCRIPTIVE_Q4_LE_180S_ABS_MARGIN_GE_20_NOT_FITTED',
                completeness='SCORE_RECONCILED_NOT_INDEPENDENT_SOURCE_ATTESTATION'))
        teams[side]=dict(team_id=team,player_minutes=minute,pbp=pbp,
            prematch_roster='ABSTAIN_NO_REPLAYABLE_PREMATCH_ROSTER',lineup_rotation='ABSTAIN_EXPLICIT_ROLES_NOT_VERIFIED')
    return dict(status='SUPPORT_RESEARCH_AUDIT_NOT_PREDICTION',fixture=deepcopy(fixture),cutoff_utc=cutoff_utc,
        audited_at_utc=now,matched_distinct_games={k:len(v) for k,v in matched.items()},
        usable_distinct_games={k:len(v) for k,v in usable.items()},unmatched_auxiliary_digests=sorted(unmatched),
        excluded=dict(excluded),teams=teams,registry_sha256=registry_pin,
        source_digest=digest(sorted(o['sha256'] for o in scores+observations)),
        prospective_records_created=0,production_coefficients_changed=False,calibration='NOT_ESTABLISHED',
        source_time_attestation='NOT_INDEPENDENTLY_VERIFIED')
