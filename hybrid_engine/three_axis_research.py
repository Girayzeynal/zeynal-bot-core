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
from hybrid_engine.distributions import Forecast, periods_for_scores
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
        scores,weights,past_shares,*,seed=20261124,concentration=None):
    """Research-only: Dirichlet quarter paths; team totals remain exactly frozen.

    Requires six verified, *past-only* shares per team; caller must provide
    historical evidence with labels older than the forecast cut.
    No fitted concentration is claimed to be empirically calibrated.
    """
    scores=np.asarray(scores)
    weights=np.asarray(weights,dtype=float)
    if (scores.ndim!=2 or scores.shape[1]!=2 or
            not np.issubdtype(scores.dtype,np.integer) or
            np.any(scores<0) or weights.shape!=(4,2) or
            not np.isfinite(weights).all() or np.any(weights<=0)):
        raise ValueError("RESEARCH_QUARTER_VALID_NONNEGATIVE_COUNTS_AND_WEIGHTS")
    if type(seed) is not int or seed<0:
        raise ValueError("RESEARCH_QUARTER_NONNEGATIVE_SEED")
    out=np.empty((len(scores),4,2),dtype=np.int32)
    concentrations=[]
    rng=np.random.default_rng(seed)
    for j,side in enumerate(("home","away")):
        arr=np.asarray(past_shares[side],dtype=float)
        if (arr.ndim!=2 or arr.shape[1]!=4 or len(arr)<MIN_QUARTER_HISTORY or
                not np.isfinite(arr).all() or np.any(arr<0) or
                np.any(arr.sum(axis=1)<=0)):
            raise Abstain("SIX_VERIFIED_PAST_QUARTER_GAMES_PER_SIDE_REQUIRED")
        arr=arr/arr.sum(axis=1,keepdims=True)
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
    if not np.array_equal(out.sum(axis=1),scores):
        raise ValueError("STOCHASTIC_QUARTERS_TEAM_SCORE_CONSERVATION")
    return out,dict(format="RESEARCH_DIRICHLET_CONDITIONAL_QUARTERS_V1",
        seed=seed,concentration=concentrations,
        training_games=[len(past_shares[x]) for x in ("home","away")],
        total_scores_unchanged=True,uncertainty_calibrated=False,
        source_history_cutoff_verified_by_caller=True,production_enabled=False)


def player_input_gate(wrapped,*,asof_utc,fixture):
    """A genuine archived preforecast minutes package is a prerequisite.

    This checks the proof, not minutes accuracy or effect coefficients.
    Never equates a player missing from reports with AVAILABLE.
    """
    if wrapped is None:
        return dict(status="BLOCKED_NO_VERIFIED_PREMATCH_MINUTES",
            player_effect_applied=False,production_enabled=False)
    if not isinstance(wrapped,dict) or not isinstance(fixture,dict):
        raise ValueError("PLAYER_PROOF_AND_NATIVE_FIXTURE_REQUIRED")
    p=validate_minutes(wrapped,asof_utc=asof_utc,fixture=fixture)
    if p["generated_at_utc"]>asof_utc or p["source_available_max_utc"]>p["generated_at_utc"]:
        raise ValueError("PLAYER_SOURCE_AFTER_PREDICTION")
    if p["fixture_start_utc"]<=asof_utc:
        raise Abstain("PLAYER_INPUT_AFTER_TIPOFF_NOT_PREMATCH_RESEARCH")
    return dict(status="EVIDENCE_VALID_NOT_AN_EFFECT_MODEL",
        minute_input_sha256=wrapped["sha256"],
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
