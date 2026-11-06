"""Fail-closed FAZ40 context integration. Never adjusts production predictions."""
from copy import deepcopy
import re
import time

from prediction_inputs import digest
from faz40_archive import require
from faz40_roster_evidence import seal_roster_observation, validate_roster_observation
from faz41_evidence import (validate_observation,seal_observation,compare_observations,
                           REGISTRY,REGISTRY_PIN,_fixture)
from faz41_adapters import replay
from faz41_news import replay_rss


def _announcement(p):
    raw=p['raw'];require(type(raw) is dict and raw.get('format')=='EXPLICIT_TEAM_ANNOUNCEMENT_V1','EXPLICIT_TEAM_ANNOUNCEMENT_REQUIRED')
    f=p['fixture'];team=raw['team_id'];players=raw['players'];five=raw['starting_five']
    provider=p['provider'];league=f['league'];season=f['season_end_year'];pid=p['provider_fixture_id']
    require((provider=='NBA' and league=='NBA') or (provider=='EUROLEAGUE_LIVE' and league in ('EUROLEAGUE','EUROCUP')),
            'ANNOUNCEMENT_PROVIDER_LEAGUE_MISMATCH')
    if provider=='NBA':valid=bool(re.fullmatch(r'002\d{7}',pid)) and int(pid[3:5])+2001==season
    else:valid=bool(re.fullmatch(('E' if league=='EUROLEAGUE' else 'U')+str(season-1)+r'_[1-9]\d{0,3}',pid))
    require(valid,'ANNOUNCEMENT_PROVIDER_SEASON_MISMATCH')
    require(raw['format']=='EXPLICIT_TEAM_ANNOUNCEMENT_V1' and raw['fixture']==f and
            raw['provider_fixture_id']==p['provider_fixture_id'] and raw['status']=='CONFIRMED' and
            team in (f['home_team_id'],f['away_team_id']) and p['published_at_utc']==raw['published_at_utc'],
            'EXPLICIT_TEAM_ANNOUNCEMENT_REQUIRED')
    require(type(players) is list and type(five) is list and
            all(type(pid) is str and pid and pid==pid.strip() for pid in players+five),
            'CANONICAL_PLAYER_IDS_REQUIRED')
    roster=seal_roster_observation(fixture_id=f['canonical_id'],observed_at_utc=p['observed_at_utc'],
        source=p['source_url'],players=players,starting_five=five,status='CONFIRMED')
    require(raw['published_at_utc']<=p['observed_at_utc']<f['start_utc'],'ANNOUNCEMENT_NOT_PREMATCH')
    expected=dict(team_id=team,players=deepcopy(players),starting_five=deepcopy(five),status='CONFIRMED')
    require(p['claims']==expected and p['data_type']=='OFFICIAL_LINEUP' and p['evidence_level']=='OFFICIAL' and
            p['scope']=='NOT_APPLICABLE','ANNOUNCEMENT_CLAIMS_CANNOT_REPLAY')
    return roster


def capture_announcement(raw, *, provider,source_url,observed_at_utc,ingested_at_utc,
                         usage='RETROSPECTIVE_RESEARCH',registry=REGISTRY,registry_pin=REGISTRY_PIN):
    """Explicit normalized announcement contract; no real provider endpoint claimed."""
    claims={k:deepcopy(raw[k]) for k in ('team_id','players','starting_five','status')}
    out=seal_observation(fixture=raw['fixture'],provider=provider,provider_fixture_id=raw['provider_fixture_id'],
        source_url=source_url,data_type='OFFICIAL_LINEUP',raw=raw,claims=claims,observed_at_utc=observed_at_utc,
        ingested_at_utc=ingested_at_utc,published_at_utc=raw['published_at_utc'],usage=usage,registry=registry,registry_pin=registry_pin)
    _announcement(out['payload']);return out


def prematch_context(observations, *, fixture,cutoff_utc,maximum_age_seconds=3600,
                     registry=REGISTRY,registry_pin=REGISTRY_PIN,news_bindings=None,news_bindings_pin=None):
    _fixture(fixture)
    require(type(cutoff_utc) is int and 0<cutoff_utc<=int(time.time()) and cutoff_utc<fixture['start_utc'],'PREMATCH_CONTEXT_REQUIRED')
    require(digest(registry)==registry_pin,'TRUSTED_REGISTRY_PIN_MISMATCH')
    require(type(observations) is list,'OBSERVATIONS_REQUIRED')
    validation=dict(fixture=fixture,cutoff_utc=cutoff_utc,maximum_age_seconds=maximum_age_seconds,
                    registry=registry,registry_pin=registry_pin,require_permitted=True)
    rows=[];rosters={};listings={};memberships={}
    for o in observations:
        p=validate_observation(o,**validation)
        if p['data_type']=='OFFICIAL_LINEUP':
            roster=_announcement(p);team=p['claims']['team_id']
            validate_roster_observation(roster,fixture_id=fixture['canonical_id'],prediction_utc=cutoff_utc,
                                       tipoff_utc=fixture['start_utc'],require_confirmed=True)
            require(team not in rosters or rosters[team]==roster,'CONFLICTING_TEAM_ANNOUNCEMENTS')
            rosters[team]=roster
        elif p['data_type']=='ROSTER' and p['raw'].get('format')=='FAZ46_ENDPOINT_LISTING_V1':
            from faz46_rosters import replay_listing
            replay_listing(o,**validation);team=p['claims']['team_id']
            require(team not in listings or listings[team]==p['claims'],'CONFLICTING_UNCONFIRMED_SOURCE_LISTINGS')
            listings[team]=deepcopy(p['claims'])
        elif p['data_type'] in ('NEWS_CLAIM','ANALYST_OPINION'):
            replay_rss(o,bindings=news_bindings,bindings_pin=news_bindings_pin,**validation)
        else:replay(o,**validation)
        if p['data_type'] in ('OFFICIAL_LINEUP','ROSTER'):
            team=p['claims']['team_id']
            for player in p['claims']['players']:
                pid=player.removeprefix(p['provider']+':');key=(p['provider'],pid)
                require(key not in memberships or memberships[key]==team,'CROSS_TEAM_PLAYER_ID_CONFLICT');memberships[key]=team
        rows.append(p)
    # Include team namespace in lineup keys: home and away rosters are not conflicting claims.
    comparable=[]
    for o in observations:
        if o['payload']['data_type'] not in ('OFFICIAL_LINEUP','ROSTER'):comparable.append(o)
    comparisons=compare_observations(comparable,**validation) if comparable else []
    require(not any(r['status']=='CONFLICT' for r in comparisons),'SOURCE_CONFLICT_BLOCKS_CONTEXT')
    require(len({r['usage'] for r in rows})<=1,'MIXED_SYNTHETIC_REAL_EVIDENCE')
    missing=[tag for tag in ('VERIFIED_INJURIES','ROTATION_STINTS','LINEUP_COMBINATIONS','PLAYER_EFFICIENCY','MARKET_DATA')]
    for side in ('home','away'):
        if fixture[side+'_team_id'] not in rosters:missing.append(side.upper()+'_CONFIRMED_LINEUP')
    p=dict(schema_version=1,fixture=fixture,cutoff_utc=cutoff_utc,
        usage=rows[0]['usage'] if rows else 'NO_EVIDENCE',evidence_sha256=sorted({o['sha256'] for o in observations}),
        registry_sha256=registry_pin,rosters=rosters,comparisons=comparisons,missing=missing,
        production_coefficients_changed=False,prospective_predictions_created=0,
        source_attestation='NOT_INDEPENDENTLY_VERIFIED')
    if listings:p['unconfirmed_source_rosters']=listings
    return dict(payload=p,sha256=digest(p))


def historical_player_features(observations, *, target,cutoff_utc,maximum_age_seconds=30*86400,
                               registry=REGISTRY,registry_pin=REGISTRY_PIN):
    """Historical minutes only. No assertion of availability/rotation for target."""
    _fixture(target)
    require(type(observations) is list and type(cutoff_utc) is int and 0<cutoff_utc<=int(time.time()) and cutoff_utc<target['start_utc'],'PREMATCH_CONTEXT_REQUIRED')
    require(digest(registry)==registry_pin,'TRUSTED_REGISTRY_PIN_MISMATCH')
    games={};slots={};usages=set()
    for o in observations:
        source=o['payload']['fixture']
        require(source['league']==target['league'] and source['season_end_year']==target['season_end_year'] and
                source['start_utc']<cutoff_utc,'HISTORICAL_PLAYER_PARTITION_OR_TIME_MISMATCH')
        p=replay(o,fixture=source,cutoff_utc=cutoff_utc,maximum_age_seconds=maximum_age_seconds,
                 registry=registry,registry_pin=registry_pin)
        require(p['data_type']=='PLAYER_MINUTES','PLAYER_MINUTES_EVIDENCE_REQUIRED')
        usages.add(p['usage']);require(len(usages)==1,'MIXED_SYNTHETIC_REAL_EVIDENCE')
        cid=source['canonical_id']
        for side in ('home','away'):
            slot=(source[side+'_team_id'],source['start_utc'])
            require(slot not in slots or slots[slot]==cid,'SAME_TEAM_START_CONFLICT');slots[slot]=cid
        if cid in games:require(games[cid]['claims']==p['claims'],'CONFLICTING_PLAYER_OBSERVATIONS')
        else:games[cid]=p
    return dict(games=len(games),source_game_ids=sorted(games),observations=[games[k] for k in sorted(games)],
                target_roster_status='NOT_INFERRED',rotation_effect=None,player_efficiency=None,
                production_coefficients_changed=False)


def research_with_context(records,observations,*,target,cutoff_utc,registry=REGISTRY,registry_pin=REGISTRY_PIN,
                          news_bindings=None,news_bindings_pin=None,history_evidence=None,**research_options):
    from faz40_research import project
    from faz40_archive import replay_game
    context=prematch_context(observations,fixture=target,cutoff_utc=cutoff_utc,registry=registry,registry_pin=registry_pin,
                             news_bindings=news_bindings,news_bindings_pin=news_bindings_pin)
    require(type(records) is list,'ARCHIVE_LIST_REQUIRED')
    categories={replay_game(r)['usage']=='SYNTHETIC_TEST' for r in records};usage=context['payload']['usage']
    require(len(categories)<=1 and (usage=='NO_EVIDENCE' or not categories or (usage=='SYNTHETIC_TEST') in categories),'MIXED_SYNTHETIC_REAL_EVIDENCE')
    require(history_evidence is not None or categories!={False},'SOURCE_BOUND_HISTORY_REQUIRED')
    binding=None
    if history_evidence is not None:
        from faz47_history_binding import bound_projection
        prediction,binding=bound_projection(records,history_evidence,target,cutoff_utc,registry=registry,registry_pin=registry_pin,**research_options)
    else:prediction=project(records,target,cutoff_utc,**research_options)
    require(usage=='NO_EVIDENCE' or (usage=='SYNTHETIC_TEST')==(prediction['usage']=='SYNTHETIC_TEST'),'MIXED_SYNTHETIC_REAL_EVIDENCE')
    p=dict(reference=prediction,evidence=context,evidence_applied_to_coefficients=False,prospective_records_created=0)
    if binding is not None:p['history_source_binding']=binding
    return dict(payload=p,sha256=digest(p))
