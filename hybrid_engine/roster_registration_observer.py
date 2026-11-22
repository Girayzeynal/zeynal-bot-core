"""Safe, append-only EUROLeague/EuroCup native registered-player observations.

This is a registration-change observer, NOT a transfer confirmer and NOT a
match-availability or betting/prediction update. The automatic operation is
only: fetch official registered people -> source-pin and append new snapshot ->
compute ID changes vs the earlier observed registry version. No backdating.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

from hybrid_engine.three_league_roster_bridge import europe_pair, verify, compare

MAX_OBSERVATIONS_PER_TEAM=128


def _safe_path(root):
    p=Path(root).expanduser().absolute()
    if (str(p)=="/data" or str(p).startswith("/data/") or p.is_symlink()
       or (p.exists() and not p.is_dir())):
        raise ValueError("ROSTER_ISOLATED_DIRECTORY_REQUIRED")
    if p.exists() and p.resolve()!=p:
        raise ValueError("ROSTER_SYMLINK_PATH_REFUSED")
    return p


def _prefix(p):
    val=(p["league"],p["season"].replace("/","-"),p["team_id"])
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",x) for x in val):
        raise ValueError("ROSTER_SAFE_STORAGE_IDENTITY_REQUIRED")
    return "-".join(val)+"-"


def record(root,wrapper,*,decision_utc=None):
    """Record only new as-observed club membership; never change older bytes."""
    p=verify(wrapper)
    if p["league"] not in ("EUROLEAGUE","EUROCUP"):
        raise ValueError("ROSTER_NATIVE_EURO_ONLY_OBSERVER")
    if decision_utc is not None and p["observed_at_utc"]>decision_utc:
        raise ValueError("ROSTER_CANNOT_USE_FUTURE_OBSERVATION")
    folder=_safe_path(root);folder.mkdir(parents=True,exist_ok=True)
    prefix=_prefix(p);old=[]
    for path in folder.glob(prefix+"*.json"):
        if len(old)>=MAX_OBSERVATIONS_PER_TEAM:
            raise ValueError("ROSTER_SNAPSHOT_STORAGE_LIMIT")
        if path.is_symlink() or not path.is_file() or path.stat().st_size>1024*1024:
            raise ValueError("ROSTER_EXISTING_OBSERVATION_UNTRUSTED")
        item=json.loads(path.read_text(encoding="utf-8"))
        v=verify(item)
        if _prefix(v)!=prefix or path.name!=prefix+item["sha256"]+".json":
            raise ValueError("ROSTER_EXISTING_SNAPSHOT_IDENTITY_CONFLICT")
        old.append(item)
    old.sort(key=lambda x:(x["payload"]["observed_at_utc"],x["sha256"]))
    existing=next((v for v in old if v["sha256"]==wrapper["sha256"]),None)
    if existing is not None:
        return dict(status="UNCHANGED_PREVIOUSLY_SAVED_OBSERVATION",
            league=p["league"],team_id=p["team_id"],current_sha256=wrapper["sha256"],
            registration_delta=None,
            current_players=len(p["players"]),model_input_allowed=False,
            historical_forecasts_changed=False)
    if old:
        latest=old[-1]
        if latest["payload"]["observed_at_utc"]>=p["observed_at_utc"]:
            raise ValueError("ROSTER_REVERSE_TIME_OR_CONFLICTING_EQUAL_CLOCK")
        delta=compare(latest,wrapper,decision_utc=p["observed_at_utc"])
    else:delta=None
    location=folder/(prefix+wrapper["sha256"]+".json")
    payload=json.dumps(wrapper,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n"
    # O_EXCL avoids overwriting historical observations, even across processes.
    flags=os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os,"O_NOFOLLOW"):flags|=os.O_NOFOLLOW
    fd=os.open(location,flags,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush();os.fsync(stream.fileno())
    except BaseException:
        # Corrupt unpublished new file may be removed; previous ones never are.
        try:location.unlink()
        except OSError:pass
        raise
    return dict(status="APPENDED_OBSERVED_OFFICIAL_REGISTRATION",
        league=p["league"],team_id=p["team_id"],current_sha256=wrapper["sha256"],
        current_players=len(p["players"]),registration_delta=delta,
        actual_transfer_confirmed=False,
        player_match_availability_verified=False,
        model_input_allowed=False,
        historical_forecasts_changed=False,production_changed=False)


def observe(league,season,home,away,*,root=None,getter=None,clock=None):
    """Existing official Europe pair adapter, one read per club; opt-in capture."""
    if league not in ("EUROLEAGUE","EUROCUP") or home==away:
        raise ValueError("ROSTER_EURO_EXACT_DIFFERENT_CLUBS_REQUIRED")
    ctx=dict(league=league,season=season,fixture_id=None,
        home=dict(provider_id=home),away=dict(provider_id=away))
    kw={}
    if getter is not None:kw["getter"]=getter
    if clock is not None:kw["clock"]=clock
    result=europe_pair(ctx,**kw)
    out={}
    for side in ("home","away"):
        r=result["teams"][side]
        if r["status"]!="REGISTRATION_SNAPSHOT_READY_NOT_LINEUP":
            out[side]=dict(status="REGISTRATION_SOURCE_UNAVAILABLE_OR_INCOMPLETE",
                           source_status=r["status"],snapshot_created=False)
            continue
        w=r["roster"]
        if root is None:
            out[side]=dict(status="DRY_RUN_OFFICIAL_SEASON_REGISTRATION",
                club_id=w["payload"]["team_id"],player_count=len(w["payload"]["players"]),
                current_sha256=w["sha256"],snapshot_created=False,
                model_input_allowed=False)
        else:out[side]=record(root,w)
    return dict(format="THREE_LEAGUE_OFFICIAL_EURO_ROSTER_OBSERVER_V1",
        league=league,season=season,results=out,
        scheduled_polling_installed=False,
        newsroom_transfer_feed_connected=False,
        original_predictions_unchanged=True,production_changed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--league",required=True,choices=("EUROLEAGUE","EUROCUP"))
    p.add_argument("--season",default="2026/2027")
    p.add_argument("--home",required=True)
    p.add_argument("--away",required=True)
    p.add_argument("--save-directory",help="Explicit opt-in append-only isolated directory")
    args=p.parse_args()
    result=observe(args.league,args.season,args.home,args.away,
                   root=args.save_directory)
    print(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False))
    return 0 if all(x["status"] in (
        "DRY_RUN_OFFICIAL_SEASON_REGISTRATION",
        "APPENDED_OBSERVED_OFFICIAL_REGISTRATION",
        "UNCHANGED_PREVIOUSLY_SAVED_OBSERVATION")
            for x in result["results"].values()) else 2


if __name__=="__main__":raise SystemExit(main())
