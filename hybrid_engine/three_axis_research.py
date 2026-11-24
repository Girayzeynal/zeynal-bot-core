"""Isolated research components for NBA score error, period uncertainty and players.

Never modifies first forecasts, active V3, source records, or Telegram outputs.
All paths are exploratory; no calibration or superiority is asserted here.
"""
from __future__ import annotations

from collections import defaultdict
import math
import time

import numpy as np

from hybrid_engine.data import Abstain
from hybrid_engine.first_forecast_walkforward import review as first_forecast_review
from hybrid_engine.player_minutes import validate_minutes

VERSION="NBA_THREE_AXIS_RESEARCH_V1"
BIAS_PRIOR_GAMES=8.
BIAS_MAX_ABS_POINTS=8.
BIAS_OBSERVATION_CLIP=30.
BIAS_MIN_TEAM_LABELS=3
BIAS_HALF_LIFE_DAYS=21.
MIN_QUARTER_HISTORY=6


def _match_team_error(row, name):
    """Return the same team's own scoring error, independent of home/away role."""
    if name==row["home"]:
        j=0
    elif name==row["away"]:
        j=1
    else:
        return None
    return float(row["prediction"][j]-row["actual"][j])


def _team_correction(prior, name, cutoff):
    eligible=[]
    for r in prior:
        # STRICT: results must be in hand before this target was predicted.
        if r["label_available_utc"]>=cutoff:
            raise ValueError("CONDITIONAL_BIAS_FUTURE_LABEL")
        err=_match_team_error(r,name)
        if err is not None:
            eligible.append((r["label_available_utc"],err))
    if len(eligible)<BIAS_MIN_TEAM_LABELS:
        return 0.,len(eligible)
    eligible.sort(key=lambda p:p[0])
    eligible=eligible[-16:]
    weights=np.array([2**(-(cutoff-ts)/(86400*BIAS_HALF_LIFE_DAYS)) for ts,_ in eligible])
    errors=np.clip(np.array([e for _,e in eligible]),-BIAS_OBSERVATION_CLIP,BIAS_OBSERVATION_CLIP)
    # A fixed shrinkage design; no labels from the target may tune this.
    effective_n=float(weights.sum()**2 / (weights@weights))
    shrink=effective_n/(effective_n+BIAS_PRIOR_GAMES)
    correction=float(np.clip(shrink*np.average(errors,weights=weights),
                             -BIAS_MAX_ABS_POINTS,BIAS_MAX_ABS_POINTS))
    return correction,len(eligible)


def conditional_bias_comparison(ledger,*,asof_utc):
    """Time-ordered, team-specific candidate against exactly the original first rows."""
    baseline=first_forecast_review(ledger,asof_utc=asof_utc)
    rows_by_sha={r["snapshot_sha256"]:r for r in ledger["forecasts"]}
    if len(rows_by_sha)!=len(ledger["forecasts"]):
        raise ValueError("CONDITIONAL_BIAS_AMBIGUOUS_SNAPSHOT")
    cohorts=[]
    for group in baseline["walk_forward_shadow"]:
        trace=group["trace"]
        original=[]
        for entry in trace:
            r=rows_by_sha.get(entry["original_snapshot_sha256"])
            if r is None or r["fixture_id"]!=entry["fixture_id"]:
                raise ValueError("CONDITIONAL_BIAS_ORIGINAL_PIN_MISMATCH")
            original.append(r)
        output=[]
        for r in original:
            t=r["prediction_generated_at_utc"]
            if type(t) is not int:
                raise ValueError("CONDITIONAL_BIAS_GENERATION_CLOCK_REQUIRED")
            prior=[p for p in original if p["fixture_id"]!=r["fixture_id"] and
                   p["label_available_utc"]<t and
                   p["first_archived_at_utc"]<t]
            corrections=[];counts=[]
            for team in (r["home"],r["away"]):
                correction,n=_team_correction(prior,team,t)
                corrections.append(correction);counts.append(n)
            candidate=[max(0.,float(r["prediction"][j])-corrections[j]) for j in range(2)]
            actual=r["actual"]
            original_err=abs(sum(r["prediction"])-sum(actual))
            candidate_err=abs(sum(candidate)-sum(actual))
            output.append(dict(fixture_id=r["fixture_id"],original_snapshot_sha256=r["snapshot_sha256"],
                generated_at_utc=t,earliest_prior_label_utc=min((p["label_available_utc"] for p in prior),default=None),
                latest_prior_label_utc=max((p["label_available_utc"] for p in prior),default=None),
                prior_fixture_ids=sorted(p["fixture_id"] for p in prior),
                home_team_history=counts[0],away_team_history=counts[1],
                adjustment=[candidate[j]-r["prediction"][j] for j in range(2)],
                original_total_error_abs=original_err,candidate_total_error_abs=candidate_err,
                forecast_before=list(r["prediction"]),forecast_candidate=candidate,
                regulation_actual=list(actual)))
        n=len(output)
        mae_old=sum(x["original_total_error_abs"] for x in output)/n if n else None
        mae_new=sum(x["candidate_total_error_abs"] for x in output)/n if n else None
        cohorts.append(dict(league=group["league"],season=group["season"],
            model_version=group["model_version"],n=n,original_mae=mae_old,
            conditional_mae=mae_new,
            delta_mae=None if n==0 else mae_new-mae_old,
            improved=sum(x["candidate_total_error_abs"]<x["original_total_error_abs"] for x in output),
            worsened=sum(x["candidate_total_error_abs"]>x["original_total_error_abs"] for x in output),
            unchanged=sum(x["candidate_total_error_abs"]==x["original_total_error_abs"] for x in output),
            trace=output))
    return dict(format=VERSION,source="ORIGINAL_NATIVE_VERIFIED_FIRST_FORECASTS",
        asof_utc=asof_utc,original_first_count=baseline["first_forecasts"],
        matched_verified_finals=baseline["matched_verified_finals"],
        original_records_untouched=True,
        target_labels_omitted_from_training=True,
        historical_holdout_reused=True,production_enabled=False,
        automatic_promotion=False,player_effect_applied=False,
        fixed_hyperparameters_not_tuned_on_targets=True,
        confidence_index=None,calibration_status="NOT_CALIBRATED",cohorts=cohorts)


def stochastic_quarters_from_frozen_scores(
        scores,weights,verified_ledger,*,target_sha256,seed=20261124,concentration=None):
    """Research-only Dirichlet quarter paths, with native-ledger past-label embargo.

    The base 2-team integer scenario totals are supplied independently and held
    unchanged. Native quarter histories and native timestamps are recovered from
    the verified ledger, never from a caller-supplied unverified shares array.
    """
    if (not isinstance(verified_ledger,dict) or
            verified_ledger.get("status")!="VERIFIED_LIVE_REPORT" or
            verified_ledger.get("scope")!="REGULATION_ONLY" or
            verified_ledger.get("query_read_only") is not True or
            verified_ledger.get("research_backtests_included") is not False):
        raise ValueError("QUARTER_NATIVE_VERIFIED_LEDGER_REQUIRED")
    rows=verified_ledger["forecasts"]
    targets=[r for r in rows if r["snapshot_sha256"]==target_sha256]
    if len(targets)!=1:
        raise ValueError("QUARTER_EXACT_TARGET_SNAPSHOT_REQUIRED")
    target=targets[0]
    cutoff=target.get("prediction_generated_at_utc")
    if (type(cutoff) is not int or not 0<cutoff<=int(time.time()) or
            cutoff>=target["fixture_start_utc"]):
        raise Abstain("QUARTER_VERIFIED_PREFORECAST_CLOCK_REQUIRED")
    if target["league"]!="NBA":
        raise ValueError("QUARTER_NBA_TARGET_REQUIRED")
    scores=np.asarray(scores)
    weights=np.asarray(weights,dtype=float)
    if (scores.ndim!=2 or scores.shape[1]!=2 or
            not np.issubdtype(scores.dtype,np.integer) or
            np.any(scores<0) or weights.shape!=(4,2) or
            not np.isfinite(weights).all() or np.any(weights<=0) or
            len(scores)<1 or len(scores)>32768 or
            np.any(scores>400)):
        raise ValueError("RESEARCH_QUARTER_VALID_NONNEGATIVE_COUNTS_AND_WEIGHTS")
    if type(seed) is not int or seed<0:
        raise ValueError("RESEARCH_QUARTER_NONNEGATIVE_SEED")
    out=np.empty((len(scores),4,2),dtype=np.int32)
    concentrations=[];trace={}
    rng=np.random.default_rng(seed)
    for j,side in enumerate(("home","away")):
        team=target[side]
        history=[]
        for r in rows:
            if (r["fixture_id"]==target["fixture_id"] or
                    r["league"]!="NBA" or r["season"]!=target["season"] or
                    r["actual"] is None or
                    r["label_available_utc"]>=cutoff):
                continue
            own=("home" if r["home"]==team else
                 "away" if r["away"]==team else None)
            if own is None:continue
            if (r["fixture_start_utc"]>=r["label_available_utc"] or
                    r["first_archived_at_utc"]>=r["fixture_start_utc"] or
                    r["first_archived_at_utc"]>=cutoff):
                raise ValueError("QUARTER_SOURCE_CLOCK_CONFLICT")
            q=np.asarray(r["actual_periods"][own][:4],dtype=float)
            if (q.shape!=(4,) or not np.isfinite(q).all() or
                    np.any(q<0) or q.sum()<=0 or
                    q.sum()!=r["actual"][0 if own=="home" else 1]):
                raise ValueError("QUARTER_VERIFIED_PERIODS_NOT_RECONCILED")
            history.append((r["fixture_id"],r["label_available_utc"],q/q.sum()))
        if len({x[0] for x in history})!=len(history):
            raise ValueError("QUARTER_DUPLICATE_NATIVE_HISTORY_FIXTURE")
        history.sort(key=lambda a:(a[1],a[0]))
        if len(history)<MIN_QUARTER_HISTORY:
            raise Abstain("SIX_VERIFIED_PAST_QUARTER_GAMES_PER_SIDE_REQUIRED")
        arr=np.asarray([h[2] for h in history],dtype=float)
        w=weights[:,j]/weights[:,j].sum()
        if concentration is None:
            variance=arr.var(axis=0,ddof=1)
            guesses=w*(1-w)/np.maximum(variance,1e-7)-1.
            c=float(np.clip(np.median(guesses),4.,1000.))
        else:
            if type(concentration) not in (float,int) or not math.isfinite(concentration) or not 4<=concentration<=1000:
                raise ValueError("QUARTER_CONCENTRATION_OUT_OF_BOUNDS")
            c=float(concentration)
        probs=rng.dirichlet(np.maximum(w*c,1e-6),size=len(scores))
        raw=scores[:,j,None]*probs
        base=np.floor(raw).astype(np.int32)
        remaining=scores[:,j]-base.sum(axis=1)
        ranks=np.argsort(-(raw-base),axis=1,kind="stable")
        idx=np.arange(len(scores))
        for k in range(4):
            base[idx,ranks[:,k]]+=(remaining>k)
        out[:,:,j]=base
        concentrations.append(c)
        trace[side]=dict(past_games=len(history),
            native_fixture_ids=[h[0] for h in history],
            latest_label_available_utc=history[-1][1])
    if not np.array_equal(out.sum(axis=1),scores):
        raise ValueError("STOCHASTIC_QUARTERS_TEAM_SCORE_CONSERVATION")
    return out,dict(format="RESEARCH_DIRICHLET_CONDITIONAL_QUARTERS_V1",
        seed=seed,concentration=concentrations,history=trace,
        target_original_snapshot_sha256=target_sha256,
        target_generated_at_utc=cutoff,
        total_scores_unchanged=True,uncertainty_calibrated=False,
        source_history_cutoff_verified=True,production_enabled=False)


def player_input_gate(publication,*,asof_utc,fixture,archive_directory=None):
    """Require archived prospective minutes AND replayable native source witnesses.

    A standalone self-hashed projected minutes dict is NOT sufficient: its
    hash establishes consistency, not authority. Old injury observations are
    never silently treated as confirmed player availability.
    """
    if publication is None:
        return dict(status="BLOCKED_NO_VERIFIED_PREMATCH_MINUTES",
            player_effect_applied=False,production_enabled=False)
    if (not isinstance(publication,dict) or not isinstance(fixture,dict) or
            not isinstance(publication.get("projection"),dict) or
            type(publication.get("first_archived_at_utc")) is not int):
        raise ValueError("PLAYER_ARCHIVED_PUBLICATION_AND_FIXTURE_REQUIRED")
    if archive_directory is None:
        return dict(status="BLOCKED_NO_REPLAYABLE_NATIVE_PLAYER_WITNESS",
            player_effect_applied=False,production_enabled=False)
    if (publication.get("classification")!="PREMATCH" or
            publication.get("eligible_for_fit") is not True or
            not 0<publication["first_archived_at_utc"]<=asof_utc<
                fixture["fixture_start_utc"]):
        raise ValueError("PLAYER_ARCHIVED_PREMATCH_CLOCK_OR_CLASSIFICATION")
    p=validate_minutes(publication["projection"],asof_utc=asof_utc,fixture=fixture)
    from hybrid_engine.player_inputs import validate_witness
    replay=validate_witness(publication,archive_directory)
    if replay!=p:
        raise ValueError("PLAYER_NATIVE_SOURCE_WITNESS_REPLAY_MISMATCH")
    if (p["generated_at_utc"]>publication["first_archived_at_utc"] or
            p["source_available_max_utc"]>p["generated_at_utc"]):
        raise ValueError("PLAYER_SOURCE_AFTER_PREDICTION")
    return dict(status="REPLAYED_EVIDENCE_ELIGIBLE_FOR_OFFLINE_PAIRED_TEST_ONLY",
        minute_input_sha256=publication["projection"]["sha256"],
        lineup_verified=p["lineup_verified"],
        player_effect_applied=False,production_enabled=False,
        confidence_index=None)


def main(argv=None):
    import argparse
    import json
    from ledger_reports import LedgerReports
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger",required=True)
    parser.add_argument("--asof-utc",type=int,default=None)
    parser.add_argument("--summary-only",action="store_true")
    args=parser.parse_args(argv)
    asof=int(time.time()) if args.asof_utc is None else args.asof_utc
    result=conditional_bias_comparison(LedgerReports(args.ledger).read("NBA"),asof_utc=asof)
    if args.summary_only:
        result["cohorts"]=[{k:v for k,v in g.items() if k!="trace"} for g in result["cohorts"]]
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
