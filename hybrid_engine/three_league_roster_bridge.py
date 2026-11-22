"""Three-league player evidence bridge; research-only, no model/Telegram mutation.

Three DISTINCT layers:
1. Official club-season registration/membership (not game availability);
2. Fixture-specific official OUT/AVAILABLE/uncertain status (not projected minutes);
3. Explicit pregame projected minutes + time-eligible fitted player coefficients.

This module allows source observations to be matched, compared, and handed to
a future independently validated player-aware model. It NEVER interprets a
transfer headline as a roster addition, assumes a registered player will play,
or silently feeds untrained effects to production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from time import time

LEAGUES=("NBA","EUROLEAGUE","EUROCUP")
SIDES=("home","away")
VERSION="THREE_LEAGUE_PREMATCH_PLAYER_BRIDGE_V1"
MAX_PLAYERS=45


def digest(item):
    return hashlib.sha256(json.dumps(item,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _int(x,tag):
    if type(x) is not int or x<=0:raise ValueError(tag+"_UTC_REQUIRED")
    return x


def _pin(p,tag):
    if type(p) is not str or len(p)!=64 or any(c not in "0123456789abcdef" for c in p):
        raise ValueError(tag+"_SHA_REQUIRED")
    return p


def _players(values):
    if type(values) is not list or len(values)>MAX_PLAYERS:
        raise ValueError("BRIDGE_BOUNDED_PLAYER_DIRECTORY_REQUIRED")
    seen=set();out=[]
    for row in values:
        if type(row) is not dict or set(row)!={"player_id","name"}:
            raise ValueError("BRIDGE_EXACT_PLAYER_IDENTITY_REQUIRED")
        pid,name=row["player_id"],row["name"]
        if (type(pid) is not str or not pid or len(pid)>64 or
            type(name) is not str or not name.strip() or len(name)>110 or pid in seen):
            raise ValueError("BRIDGE_UNIQUE_PLAYER_ID_REQUIRED")
        seen.add(pid);out.append(dict(player_id=pid,name=name.strip()))
    return sorted(out,key=lambda x:x["player_id"])


def snapshot(*,league,season,team_id,observed_at_utc,source_url,source_body_sha256,players,
             source_kind,fixture_tipoff_utc=None):
    """Versioned, append-only OBSERVATION; digest does NOT authenticate source."""
    if league not in LEAGUES or type(season) is not str or not season or (
        type(team_id) is not str or not team_id or len(team_id)>80):
        raise ValueError("BRIDGE_EXACT_LEAGUE_SEASON_TEAM_REQUIRED")
    if source_kind not in ("NBA_OFFICIAL_ROSTER_DIRECTORY",
                          "EUROPE_OFFICIAL_SEASON_REGISTRATION"):
        raise ValueError("BRIDGE_OFFICIAL_DIRECTORY_SOURCE_REQUIRED")
    if (source_kind=="EUROPE_OFFICIAL_SEASON_REGISTRATION") != (league!="NBA"):
        raise ValueError("BRIDGE_DIRECTORY_LEAGUE_SCOPE")
    observed=_int(observed_at_utc,"BRIDGE_OBSERVED")
    if observed>int(time()):raise ValueError("BRIDGE_FUTURE_OBSERVATION")
    if fixture_tipoff_utc is not None and not observed<_int(fixture_tipoff_utc,"BRIDGE_TIPOFF"):
        raise ValueError("BRIDGE_POSTTIPOFF_NOT_PREGAME")
    if type(source_url) is not str or not source_url.startswith("https://") or len(source_url)>1200:
        raise ValueError("BRIDGE_SOURCE_URL_REQUIRED")
    _pin(source_body_sha256,"BRIDGE_SOURCE_BODY")
    canonical=_players(players)
    if not canonical:raise ValueError("BRIDGE_EMPTY_OFFICIAL_REGISTRATION")
    return dict(payload=dict(
        format=VERSION,record_type="OFFICIAL_SEASON_MEMBERSHIP_OBSERVATION_NOT_ACTIVE_LINEUP",
        league=league,season=season,team_id=team_id,observed_at_utc=observed,
        source_url=source_url,source_body_sha256=source_body_sha256,
        source_kind=source_kind,players=canonical,
        original_forecasts_changed=False,match_availability_verified=False,
        forecast_minutes_verified=False,model_input_allowed=False),
        sha256=digest(dict(
            format=VERSION,record_type="OFFICIAL_SEASON_MEMBERSHIP_OBSERVATION_NOT_ACTIVE_LINEUP",
            league=league,season=season,team_id=team_id,observed_at_utc=observed,
            source_url=source_url,source_body_sha256=source_body_sha256,
            source_kind=source_kind,players=canonical,
            original_forecasts_changed=False,match_availability_verified=False,
            forecast_minutes_verified=False,model_input_allowed=False)))


def verify(w):
    if not isinstance(w,dict) or set(w)!={"payload","sha256"}:
        raise ValueError("BRIDGE_SIGNED_ENVELOPE_REQUIRED")
    if digest(w["payload"])!=_pin(w["sha256"],"BRIDGE_RECORD"):
        raise ValueError("BRIDGE_SOURCE_ENVELOPE_TAMPERED")
    p=w["payload"]
    required={"format","record_type","league","season","team_id","observed_at_utc",
              "source_url","source_body_sha256","source_kind","players",
              "original_forecasts_changed","match_availability_verified",
              "forecast_minutes_verified","model_input_allowed"}
    if set(p)!=required or p["format"]!=VERSION or any(p[k] is not False for k in
        ("original_forecasts_changed","match_availability_verified",
         "forecast_minutes_verified","model_input_allowed")):
        raise ValueError("BRIDGE_OBSERVATION_SCOPE_REQUIRED")
    rebuilt=snapshot(league=p["league"],season=p["season"],team_id=p["team_id"],
        observed_at_utc=p["observed_at_utc"],source_url=p["source_url"],
        source_body_sha256=p["source_body_sha256"],source_kind=p["source_kind"],
        players=p["players"])
    if rebuilt!=w:raise ValueError("BRIDGE_NONCANONICAL_OBSERVATION")
    return p


def europe_pair(ctx,*,getter=None,clock=time):
    """Wire the EXISTING EuroLeague/EuroCup native season player adapter.

    Reports partial failures without inventing all-season player coverage.
    """
    league=ctx.get("league")
    if league not in ("EUROLEAGUE","EUROCUP"):
        raise ValueError("BRIDGE_EURO_SCOPE")
    from hybrid_engine.europe_native_roster_source import pair
    if getter is None:result=pair(ctx,clock=clock)
    else:result=pair(ctx,getter=getter,clock=clock)
    observed={}
    for side in SIDES:
        row=result["teams"][side]
        if row.get("status")!="OFFICIAL_SEASON_REGISTRATION_OBSERVED":
            observed[side]=dict(status="SOURCE_UNAVAILABLE_OR_INCOMPLETE",
                                 source_status=row.get("status"),roster=None)
            continue
        players=row["registered_players"]
        if not players or any(type(x.get("player_id")) is not str or not x["player_id"] for x in players):
            observed[side]=dict(status="PLAYER_IDS_MISSING",roster=None)
            continue
        document=snapshot(league=league,season=ctx["season"],
            team_id=str(ctx[side]["provider_id"]),observed_at_utc=row["observed_at_utc"],
            source_url=row["source_url"],source_body_sha256=row["body_sha256"],
            source_kind="EUROPE_OFFICIAL_SEASON_REGISTRATION",
            players=[dict(player_id=x["player_id"],name=x["name"]) for x in players],
            fixture_tipoff_utc=ctx.get("fixture_start_utc"))
        observed[side]=dict(status="REGISTRATION_SNAPSHOT_READY_NOT_LINEUP",roster=document)
    return dict(format="THREE_LEAGUE_EURO_PAIR_BRIDGE_V1",
        league=league,fixture_id=ctx.get("fixture_id"),
        teams=observed,model_input_allowed=False,
        roster_season_not_match_availability=True)


def compare(old,new,*,decision_utc):
    """Automatic directory change detection, NOT automatic transfer confirmation."""
    a,b=verify(old),verify(new)
    if any(a[k]!=b[k] for k in ("league","season","team_id","source_kind")):
        raise ValueError("BRIDGE_CROSS_TEAM_OR_LEAGUE_COMPARISON")
    cut=_int(decision_utc,"BRIDGE_DECISION")
    if not 0<a["observed_at_utc"]<=b["observed_at_utc"]<=cut:
        raise ValueError("BRIDGE_ASOF_CUTOFF_CONFLICT")
    before={p["player_id"]:p["name"] for p in a["players"]}
    after={p["player_id"]:p["name"] for p in b["players"]}
    return dict(format="THREE_LEAGUE_MEMBERSHIP_DELTA_V1",
        league=b["league"],season=b["season"],team_id=b["team_id"],
        first_observed_at_utc=a["observed_at_utc"],
        newer_observed_at_utc=b["observed_at_utc"],previous_sha256=old["sha256"],
        current_sha256=new["sha256"],
        newly_registered_player_ids=sorted(after.keys()-before.keys()),
        no_longer_registered_player_ids=sorted(before.keys()-after.keys()),
        continued_player_ids=sorted(before.keys() & after.keys()),
        classification="SOURCE_DECLARED_REGISTRATION_CHANGE_NOT_PROVEN_TRANSFER",
        can_automatically_update_observed_roster=False,
        can_append_to_isolated_research_registry=True,
        source_claim_independently_authenticated=False,
        confirms_transfer_contract=False,
        determines_match_eligibility=False,changes_forecast=False)


def fixture_gate(*,fixture,home_roster,away_roster,availability,exposures,fit):
    """Shared 3-league forecast-preflight contract (NOT score adjustment).

    Any current official directory can only narrow identity. The current
    availability, projected minutes and *fitted historical exposures* are
    separately required; no guessed replacement player or synthetic bonus.
    """
    if not isinstance(fixture,dict) or set(fixture)!={"league","season","fixture_id",
       "home_team_id","away_team_id","decision_utc","tipoff_utc"}:
        raise ValueError("BRIDGE_EXACT_FIXTURE_REQUIRED")
    league=fixture["league"]
    if league not in LEAGUES or fixture["home_team_id"]==fixture["away_team_id"]:
        raise ValueError("BRIDGE_FIXTURE_LEAGUE_OR_TEAM")
    decision=_int(fixture["decision_utc"],"BRIDGE_DECISION")
    if decision>=_int(fixture["tipoff_utc"],"BRIDGE_TIPOFF"):
        raise ValueError("BRIDGE_AFTER_TIPOFF")
    current={}
    for side,wrapper in (("home",home_roster),("away",away_roster)):
        try:
            roster=verify(wrapper)
        except (ValueError,KeyError,TypeError):
            return dict(status="BLOCKED_OFFICIAL_ROSTER_MISSING",blocked_side=side,
                        model_player_input=None,production_model_changed=False)
        if (roster["league"]!=league or roster["season"]!=fixture["season"] or
            roster["team_id"]!=fixture[side+"_team_id"] or
            roster["observed_at_utc"]>decision):
            raise ValueError("BRIDGE_ROSTER_FIXTURE_OR_CLOCK_CONFLICT")
        current[side]=set(row["player_id"] for row in roster["players"])
    if current["home"] & current["away"]:
        raise ValueError("BRIDGE_PLAYER_ID_DUPLICATED_ACROSS_TEAMS")
    if not all(isinstance(x,dict) for x in (availability,exposures,fit)):
        return dict(status="BLOCKED_PLAYER_STATUS_MINUTES_OR_FIT_MISSING",
                    model_player_input=None,production_model_changed=False)
    # No field may be silently filled. Require an independently fitted model
    # and fixture-bound *time-eligible* statuses/minutes for both teams.
    if (fit.get("status")!="DECLARED_HISTORICAL_PREFIT_EXPOSURE_MODEL" or
        type(fit.get("trained_until_utc")) is not int or
        fit["trained_until_utc"]>decision or
        fit.get("training_includes_target") is not False or
        fit.get("source_attestation")!="INDEPENDENT_VERIFICATION_PENDING"):
        return dict(status="BLOCKED_FITTED_PLAYER_COEFFICIENTS_NOT_VERIFIED",
                    model_player_input=None,production_model_changed=False)
    for record,tag in ((availability,"STATUS"),(exposures,"MINUTES")):
        if (record.get("fixture_id")!=fixture["fixture_id"] or
            type(record.get("observed_at_utc")) is not int or
            record["observed_at_utc"]>decision or
            record.get("scope")!="PREGAME_NOT_BACKFILLED"):
            return dict(status="BLOCKED_"+tag+"_PREGAME_EVIDENCE",
                        model_player_input=None,production_model_changed=False)
    player_context={}
    duration=48 if league=="NBA" else 40
    for side in SIDES:
        statuses=availability.get(side);minutes=exposures.get(side)
        if not isinstance(statuses,dict) or not isinstance(minutes,dict):
            return dict(status="BLOCKED_PLAYER_EVIDENCE_"+side.upper(),
                        model_player_input=None,production_model_changed=False)
        if not set(minutes)<=current[side] or not set(statuses)>=set(minutes):
            return dict(status="BLOCKED_UNKNOWN_PLAYER_ID_"+side.upper(),
                        model_player_input=None,production_model_changed=False)
        if any(statuses[pid]!="AVAILABLE" for pid in minutes):
            return dict(status="BLOCKED_UNAVAILABLE_OR_UNCERTAIN_PLAYER_"+side.upper(),
                        model_player_input=None,production_model_changed=False)
        if len(minutes)<5 or any(type(m) not in (int,float) or not math.isfinite(m)
              or m<0 or m>duration for m in minutes.values()) or abs(sum(minutes.values())-duration*5)>1e-5:
            return dict(status="BLOCKED_ROTATION_EXPOSURE_"+side.upper(),
                        model_player_input=None,production_model_changed=False)
        player_context[side]=dict(expected_minutes=dict(minutes),
                                  registered_ids_count=len(current[side]))
    return dict(status="RESEARCH_CONTEXT_PRECHECK_ONLY",
        model_player_input=player_context,
        source_attestation_independently_verified=False,
        numeric_effect_coefficients_applied=False,
        transfer_news_used_as_roster=False,
        fitted_player_contribution_validated=False,
        scoring_engine_connected=False,production_model_changed=False)



def existing_nba_minutes_candidate(context,review,rosters,boxes,*,generated_at_utc):
    """Connect already-implemented native NBA player_minutes projection.

    This is not a new heuristic minutes formula. Native source/identity,
    published time, injury corroboration, 6 old box games and 240 minutes
    are all checked by the existing player_minutes implementation.
    Caller may archive the exact returned prospective packet *separately*
    before tipoff; this function never writes, fits, or issues a forecast.
    """
    from hybrid_engine.data import Abstain
    from hybrid_engine.player_minutes import projection,validate_minutes
    if not isinstance(context,dict) or context.get("league")!="NBA":
        raise ValueError("BRIDGE_EXISTING_MINUTES_NBA_ONLY")
    try:
        wrapped=projection(context,review,rosters,boxes,
                           generated_at_utc=generated_at_utc)
        expected={k:context[k] for k in
                  ("league","season","fixture_id","fixture_start_utc")}
        expected.update(home_team_id=context["home"]["provider_id"],
                        away_team_id=context["away"]["provider_id"])
        p=validate_minutes(wrapped,asof_utc=generated_at_utc,fixture=expected)
    except Abstain as exc:
        return dict(status="BLOCKED_ACTUAL_PREGAME_PLAYER_INPUTS",
                    reason=str(exc),minutes_projection=None,
                    model_fit_completed=False,scoring_engine_connected=False,
                    production_changed=False)
    except (KeyError,ValueError,TypeError) as exc:
        return dict(status="BLOCKED_PLAYER_INPUT_CONTRACT_OR_IDENTITY",
                    reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__,
                    minutes_projection=None,model_fit_completed=False,
                    scoring_engine_connected=False,production_changed=False)
    return dict(status="VALIDATED_PROSPECTIVE_NBA_MINUTES_RESEARCH_ONLY",
                minutes_projection=wrapped,
                fixture_id=p["fixture_id"],minutes_sha256=wrapped["sha256"],
                home_projected_player_count=len(p["home"]),
                away_projected_player_count=len(p["away"]),
                source_available_max_utc=p["source_available_max_utc"],
                roster_source_attestation_not_independent=True,
                model_fit_completed=False,scoring_engine_connected=False,
                original_forecast_changed=False,production_changed=False)


def readiness():
    """Real repository integrations, not a live availability/transfer claim."""
    from hybrid_engine.official_club_coverage import summary
    coverage=summary()
    return dict(format="THREE_LEAGUE_ROSTER_WIRING_AUDIT_V1",
        leagues=list(LEAGUES),membership_inventory=coverage["league_totals"],
        club_count=coverage["members_total"],
        observed_official_club_news_pilots=coverage["pilot_source_pages_observed"],
        not_connected_club_news_sites=coverage["source_pages_not_yet_verified"],
        native_euro_season_registration_adapter=True,
        native_nba_roster_complete_adapter=False,
        existing_nba_player_minutes_projection_adapter=True,
        nba_existing_player_minutes_bridge_added=True,
        existing_nba_player_shadow_offline_fit_module=True,
        existing_three_league_adaptive_team_pace_module=True,
        historic_box_players_can_be_archived=True,
        automatic_registration_snapshot_comparison_added=True,
        fully_automatic_transfer_news_to_current_roster=False,
        independent_match_availability_verified=False,
        real_fitted_player_minutes_and_rotation_connected=False,
        production_score_model_player_inputs=False,
        archived_forecasts_modified=False,production_changed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness",action="store_true")
    args=parser.parse_args()
    if not args.readiness:parser.error("Only --readiness is allowed; no hidden source fetch or deploy")
    print(json.dumps(readiness(),ensure_ascii=False,sort_keys=True,indent=2))


if __name__=="__main__":main()
