"""Read-only NBA player-coefficient pilot using *past actual* box minutes.

Historical postgame minutes ARE legitimate training covariates after publication,
but they are NOT a retrospective prematch minute forecast. This separate ridge
model does not replace the prospective player_shadow contract or frozen score.
The conditional no-player case is hypothetical and does not allege an injury.
"""
import argparse
from collections import Counter,defaultdict
import json
import math
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.availability import effective_box_time
from hybrid_engine.data import STRICT,available_at,regulation,local_path
from hybrid_engine.player_minutes import historical_minutes,capped_rotation
from hybrid_engine.boxes import checked_stats
from ledger_reports import LedgerReports

VERSION="HISTORICAL_NBA_PLAYER_BOX_ASSOCIATION_PILOT_V1"
MAX_GAMES=1000
MAX_PARAMETERS=512
MIN_GAMES=30
MIN_TEAM_HISTORY=6


def verified_box_rows(cohort,cutoff_utc):
    """Only pinned, final, regular-time boxes available before the fit cutoff."""
    if type(cutoff_utc) is not int or cutoff_utc>int(time.time()) or cutoff_utc<=0:
        raise ValueError("PLAYER_PILOT_REAL_CUTOFF_REQUIRED")
    out=[];skipped=Counter();seen=set()
    if len(cohort)>MAX_GAMES*4:raise ValueError("PLAYER_PILOT_COHORT_BUDGET")
    for versions in cohort:
        if not versions:continue
        valid=[r for r in versions if r.get("league")=="NBA" and
               r.get("fixture_start_utc",cutoff_utc)>=0 and
               r["fixture_start_utc"]<cutoff_utc and
               r.get("box") is not None and regulation(r) is not None and
               r.get("periods") and len(r["periods"]["home"])==len(r["periods"]["away"])==4 and
               available_at(r,STRICT)<=cutoff_utc and
               effective_box_time(r["box"])<=cutoff_utc]
        if not valid:
            skipped["NO_VERIFIED_PAST_BOX_AT_CUTOFF"]+=1;continue
        r=max(valid,key=lambda x:(effective_box_time(x["box"]),available_at(x,STRICT)))
        b=r["box"];fid=r["fixture_id"]
        if fid in seen:raise ValueError("PLAYER_PILOT_DUPLICATE_FIXTURE")
        seen.add(fid)
        if (b.get("scope")!="FINAL_WITH_OT" or b.get("regulation_eligible") is not True or
                any(b.get(k)!=r.get(k) for k in
                    ("fixture_id","fixture_start_utc","home_team_id","away_team_id","league","season")) or
                b.get("source_digest")!=digest(b.get("source")) or
                not r["fixture_start_utc"]<effective_box_time(b)<=cutoff_utc):
            skipped["BOX_PROVENANCE_OR_IDENTITY_UNVERIFIED"]+=1;continue
        if [b["teams"][s]["points"] for s in ("home","away")]!=regulation(r):
            skipped["BOX_REGULATION_SCORE_CONFLICT"]+=1;continue
        minute_map={}
        try:
            for side in ("home","away"):
                team=r[side+"_team_id"]
                people=[p for p in b["players"] if p.get("team_id")==team]
                if len(people)<6 or len(people)>30:raise ValueError("PLAYER_PILOT_INCOMPLETE_TEAM_BOX")
                actual={}
                for p in people:
                    pid=p["player_id"]
                    if (type(pid) is not str or not pid.isdigit() or pid in actual):
                        raise ValueError("PLAYER_PILOT_PLAYER_IDENTITY")
                    actual[pid]=historical_minutes(p)
                if abs(sum(actual.values())-240)>3 or sum(v>0 for v in actual.values())<6:
                    raise ValueError("PLAYER_PILOT_MINUTE_TOTAL_NOT_240")
                minute_map[side]=actual
        except (ValueError,KeyError,TypeError):
            skipped["INVALID_PAST_PLAYER_MINUTES"]+=1;continue
        out.append(dict(fixture_id=fid,league=r["league"],season=r["season"],
            fixture_start_utc=r["fixture_start_utc"],
            home_team_id=r["home_team_id"],away_team_id=r["away_team_id"],
            score=regulation(r),minutes=minute_map,
            source_sha256=b["source_digest"],available_at_utc=max(
                effective_box_time(b),available_at(r,STRICT))))
        if len(out)>MAX_GAMES:raise ValueError("PLAYER_PILOT_VERIFIED_GAME_BUDGET")
    return sorted(out,key=lambda r:(r["fixture_start_utc"],r["fixture_id"])),dict(skipped)


def fit_box_association(games,cutoff_utc):
    """Partial-pooling association; actual historical minutes are NOT pregame."""
    if len(games)<MIN_GAMES: return dict(status="INSUFFICIENT_REAL_HISTORICAL_PLAYER_BOXES",
                                       verified_games=len(games),minimum_games=MIN_GAMES)
    if len({(r["league"],r["season"]) for r in games})!=1:
        raise ValueError("PLAYER_PILOT_SEPARATE_SEASON_REQUIRED")
    if len({r["fixture_id"] for r in games})!=len(games):
        raise ValueError("PLAYER_PILOT_DUPLICATE_GAMES")
    if any(r["available_at_utc"]>cutoff_utc or r["fixture_start_utc"]>=cutoff_utc for r in games):
        raise ValueError("PLAYER_PILOT_TARGET_OR_LATE_LABEL_IN_TRAINING")
    teams=sorted({r[s+"_team_id"] for r in games for s in ("home","away")})
    appearances=Counter()
    for g in games:
        for side in ("home","away"):
            for pid,minutes in g["minutes"][side].items():
                if minutes>0:appearances[pid]+=1
    # Model parameter cap: choose a *fixed* source-blind frequency subset
    # before constructing X. Unknown/rare players contribute zero prior mean.
    capacity=MAX_PARAMETERS-2-2*len(teams)
    if capacity<0:raise ValueError("PLAYER_PILOT_TEAM_PARAMETER_BUDGET")
    ranked=sorted(appearances,key=lambda p:(-appearances[p],p))
    players=sorted(ranked[:capacity])
    n=2+2*len(teams)+len(players)
    team_ix={t:i for i,t in enumerate(teams)}
    player_ix={p:i for i,p in enumerate(players)}
    X=np.zeros((2*len(games),n),dtype=float);y=np.zeros(2*len(games),dtype=float)
    for i,g in enumerate(games):
        for j,side in enumerate(("home","away")):
            other="away" if side=="home" else "home"
            row=2*i+j;own=g[side+"_team_id"];opp=g[other+"_team_id"]
            X[row,0]=1;X[row,1]=int(side=="home")
            X[row,2+team_ix[own]]=1
            X[row,2+len(teams)+team_ix[opp]]=1
            for pid,minutes in g["minutes"][side].items():
                if pid in player_ix:X[row,2+2*len(teams)+player_ix[pid]]=minutes/48
            y[row]=g["score"][j]
    scale=np.r_[30.,3.,np.full(2*len(teams),4.),np.full(len(players),2.)]
    noise=max(1.,float(np.var(y,ddof=1)))
    precision=X.T@X/noise+np.diag(1/(scale*scale))
    prior=np.zeros(n,dtype=float);prior[0]=float(y.mean())
    coef=np.linalg.solve(precision,X.T@y/noise+prior/(scale*scale))
    if not np.isfinite(coef).all():
        raise ValueError("PLAYER_PILOT_NONFINITE_COEFFICIENTS")
    return dict(status="REAL_HISTORICAL_BOX_MODEL_FITTED_RESEARCH_ONLY",
        format=VERSION,cutoff_utc=cutoff_utc,season=games[0]["season"],
        training_games=len(games),training_fixture_ids=[g["fixture_id"] for g in games],
        training_sha256=digest([dict(fixture_id=g["fixture_id"],box_sha256=g["source_sha256"],
                                    available_at_utc=g["available_at_utc"]) for g in games]),
        teams=teams,players=players,player_appearance_games=dict(appearances),
        omitted_rare_players=len(ranked)-len(players),coefficients=coef.tolist(),
        confirmed_lineup=False,measured_pbp_pace=False,causal_player_effect=False,
        calibration_status="NOT_CALIBRATED",production_enabled=False,
        original_predictions_unchanged=True)


def rotation(games,team,cutoff_utc):
    """Past-six observed rotation PRIOR, never a confirmed future lineup."""
    recent=[g for g in games if team in (g["home_team_id"],g["away_team_id"]) and
            g["available_at_utc"]<=cutoff_utc and g["fixture_start_utc"]<cutoff_utc]
    recent=sorted(recent,key=lambda g:(g["fixture_start_utc"],g["fixture_id"]))[-6:]
    if len(recent)<MIN_TEAM_HISTORY:return None
    if cutoff_utc-recent[-1]["fixture_start_utc"]>14*86400:return None
    minutes=defaultdict(float)
    for g in recent:
        side="home" if g["home_team_id"]==team else "away"
        for pid,value in g["minutes"][side].items(): minutes[pid]+=value/6
    ids=sorted(minutes)
    try:values=capped_rotation([minutes[k] for k in ids])
    except ValueError:return None
    return dict(zip(ids,values))


def projected_pair(model,home_team_id,away_team_id,home_rotation,away_rotation):
    if model.get("status")!="REAL_HISTORICAL_BOX_MODEL_FITTED_RESEARCH_ONLY":
        raise ValueError("PLAYER_PILOT_NO_FITTED_ARTIFACT")
    teams=model["teams"];players=model["players"];coef=np.asarray(model["coefficients"])
    if len(coef)!=2+2*len(teams)+len(players):
        raise ValueError("PLAYER_PILOT_COEFFICIENT_IDENTITY")
    ix={t:i for i,t in enumerate(teams)};pix={p:i for i,p in enumerate(players)}
    outputs=[]
    for side,own,other,exposures in (
            ("home",home_team_id,away_team_id,home_rotation),
            ("away",away_team_id,home_team_id,away_rotation)):
        if own not in ix or other not in ix or abs(sum(exposures.values())-240)>1e-5:
            raise ValueError("PLAYER_PILOT_TEAM_OR_ROTATION_UNSUPPORTED")
        x=np.zeros(len(coef));x[0]=1;x[1]=float(side=="home")
        x[2+ix[own]]=1;x[2+len(teams)+ix[other]]=1
        for pid,minute in exposures.items():
            if pid in pix:x[2+2*len(teams)+pix[pid]]=minute/48
        outputs.append(float(x@coef))
    return outputs


def scenario(model,games,fixture,asof_utc):
    if not asof_utc<fixture["fixture_start_utc"]-900:
        return dict(status="CLOSED_PREGAME_WINDOW")
    if fixture["fixture_id"] in model["training_fixture_ids"]:
        raise ValueError("PLAYER_PILOT_TRAINING_TARGET_OVERLAP")
    ids=[fixture[s+"_team_id"] for s in ("home","away")]
    rotations=[rotation(games,team,asof_utc) for team in ids]
    if any(r is None for r in rotations):
        return dict(status="UNVERIFIED_RECENT_PLAYER_ROTATION")
    base=projected_pair(model,*ids,*rotations)
    paths=[]
    for j,side in enumerate(("home","away")):
        original=rotations[j]
        eligible=sorted((p for p in original if original[p]>0 and
                         p in model["player_appearance_games"]),
                        key=lambda pid:(-original[pid],pid))
        if not eligible:continue
        pid=eligible[0]
        changed=dict(original);changed[pid]=0.
        try:
            keys=sorted(changed);vals=capped_rotation([changed[k] for k in keys])
        except ValueError:continue
        shifted=dict(zip(keys,vals))
        other=rotations[1-j]
        after=projected_pair(model,*ids,
            shifted if j==0 else other,other if j==0 else shifted)
        paths.append(dict(side=side,player_id=pid,
            hypothetical_removed_minutes=round(original[pid],3),
            base_total=round(sum(base),3),
            conditional_total=round(sum(after),3),
            conditional_total_delta=round(sum(after)-sum(base),3),
            verified_injured=False,confirmed_lineup=False,real_world_accuracy_verified=False))
    return dict(status="CONDITIONAL_HISTORICAL_PLAYER_SENSITIVITY_NOT_AN_INJURY_FORECAST",
        fixture_id=fixture["fixture_id"],start_utc=fixture["fixture_start_utc"],
        predicted_home=round(base[0],3),predicted_away=round(base[1],3),
        total=round(sum(base),3),scenarios=paths,
        pregame_rotation_source="SIX_PREVIOUS_PAST_GAME_BOXES_NOT_CURRENT_TEAM_ROSTER",
        first_forecast_unchanged=True,production_enabled=False)


def run_readonly(data_directory,*,now_utc=None):
    now=int(time.time()) if now_utc is None else now_utc
    root=local_path(data_directory);storage=root/"adaptive-v2"/"inputs"
    ledger=root/"live-nba"/"nba-hybrid.sqlite"
    if not (storage/"native").is_dir() or not ledger.is_file():
        return dict(format=VERSION,status="INPUT_ARCHIVE_NOT_PRESENT",
                    original_forecasts_modified=False,source_calls=0)
    from hybrid_engine.adaptive_data import FeatureStore
    store=FeatureStore(storage,[root/"live-nba"/"assets"],
                       lambda *args,**kwargs: (_ for _ in ()).throw(RuntimeError("NETWORK_FORBIDDEN")))
    cohort=store.cohort("NBA",2026,now)
    games,excluded=verified_box_rows(cohort,now)
    model=fit_box_association(games,now)
    report=dict(format=VERSION,status=model["status"],asof_utc=now,
        verified_player_box_games=len(games),excluded=excluded,
        fitted_players=len(model.get("players",[])),
        historical_player_training_games=model.get("training_games",0),
        source_calls=0,score_archive_writes=0,original_forecasts_modified=False,
        calibrated=False,live_player_effect_applied=False,production_enabled=False,
        future_scenarios=[])
    if model["status"]!="REAL_HISTORICAL_BOX_MODEL_FITTED_RESEARCH_ONLY":return report
    live=LedgerReports(ledger).read("NBA")
    if live["status"]!="VERIFIED_LIVE_REPORT":
        report["status"]="FROZEN_FORECAST_LEDGER_NOT_VERIFIED";return report
    future=sorted((r for r in live["forecasts"] if r["actual"] is None and
                   r["fixture_start_utc"]>now+900),key=lambda r:r["fixture_start_utc"])
    for r in future[:3]:
        target=dict(fixture_id=r["fixture_id"],fixture_start_utc=r["fixture_start_utc"],
                    home_team_id=None,away_team_id=None)
        # Original ledger rows expose team labels; exact provider IDs remain
        # in their separately pinned snapshot. Do not guess a team ID from name.
        from hybrid_engine.player_inputs import load_snapshot
        try:
            snap=load_snapshot(ledger,r["fixture_id"])
            target["home_team_id"]=snap["home"]["provider_id"]
            target["away_team_id"]=snap["away"]["provider_id"]
            result=scenario(model,games,target,now)
        except (ValueError,KeyError,TypeError):
            result=dict(status="FUTURE_FIXTURE_SNAPSHOT_OR_ROTATION_UNVERIFIED")
        report["future_scenarios"].append(dict(home=r["home"],away=r["away"],**result))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory",required=True)
    args=parser.parse_args()
    print(json.dumps(run_readonly(args.data_directory),ensure_ascii=False,sort_keys=True))
if __name__=="__main__":main()
