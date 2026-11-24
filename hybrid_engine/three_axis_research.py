"""Isolated research components for NBA score error, period uncertainty and players.

Never modifies first forecasts, active V3, source records, or Telegram outputs.
All paths are exploratory; no calibration or superiority is asserted here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import time

import numpy as np

from hybrid_engine.data import Abstain
from hybrid_engine.first_forecast_walkforward import review as first_forecast_review
from hybrid_engine.player_minutes import validate_minutes
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

VERSION="NBA_THREE_AXIS_RESEARCH_V2"
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
    latest=eligible[-1][0]
    weights=np.array([2**(-(latest-ts)/(86400*BIAS_HALF_LIFE_DAYS)) for ts,_ in eligible])
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


def _history_from_cut(cut, target, side):
    """Validate the original, pre-forecast feature cut; no current-data backfill."""
    from hybrid_engine.data import STRICT, available_at
    t=cut["target"]
    cutoff=cut["cutoff_utc"]
    if (cut["evaluation_class"]!=STRICT or t["fixture_id"]!=target["fixture_id"]
            or t["league"]!=target["league"] or t["season"]!=target["season"]
            or t["fixture_start_utc"]!=target["fixture_start_utc"]
            or not 0<cutoff<=target["prediction_generated_at_utc"]):
        raise ValueError("QUARTER_FROZEN_CUT_IDENTITY_OR_CLOCK")
    tid=t[side+"_team_id"]
    history=[]
    for r in cut["history"]:
        if (r["fixture_id"]==t["fixture_id"] or r["league"]!=t["league"] or
                r["season"]!=t["season"]):
            raise ValueError("QUARTER_FROZEN_HISTORY_IDENTITY")
        ts=max(r["observed_at_utc"],r["ingested_at_utc"],available_at(r,STRICT))
        if not r["fixture_start_utc"]<ts<=cutoff:
            raise ValueError("QUARTER_FROZEN_HISTORY_CLOCK")
        own="home" if r["home_team_id"]==tid else "away" if r["away_team_id"]==tid else None
        if own is None: continue
        q=np.asarray(r["periods"][own][:4],dtype=float)
        if q.shape!=(4,) or not np.isfinite(q).all() or np.any(q<0) or q.sum()<=0:
            raise ValueError("QUARTER_FROZEN_HISTORY_PERIODS")
        history.append((r["fixture_id"],ts,q/q.sum()))
    return history


def frozen_cut_loader(ledger_path, assets_directory):
    """Read the exact original snapshot and replay its pinned input provenance."""
    import sqlite3
    from contextlib import closing
    from hybrid_engine.data import local_path
    from hybrid_engine.prediction_audit import Assets,audit_snapshot
    from live_analysis_ledger import LiveAnalysisLedger
    path=local_path(ledger_path)
    assets=Assets(assets_directory)
    def load(row):
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=.2)) as db:
            db.execute("PRAGMA query_only=ON")
            found=db.execute("""SELECT s.payload,s.sha256,r.snapshot_sha256,r.completed_utc
                FROM live_analysis_snapshots s JOIN live_analysis_commit_receipts r
                USING(league,fixture_id,model_digest)
                WHERE s.league=? AND s.fixture_id=? AND s.model_digest=?""",
                (row["league"],row["fixture_id"],row["model_digest"])).fetchone()
        if not found or found[1]!=row["snapshot_sha256"] or found[2]!=found[1] or found[3]!=row["first_archived_at_utc"]:
            raise ValueError("QUARTER_EXACT_ARCHIVED_RECEIPT_REQUIRED")
        snapshot=LiveAnalysisLedger._decode(found[0],found[1],expected=(row["league"],row["fixture_id"],row["model_digest"]))
        audit_snapshot(snapshot,assets.root)
        return assets.read(snapshot["input_asset"])
    return load


def stochastic_quarters_from_frozen_scores(
        scores,verified_ledger,*,target_sha256,seed=20261124,concentration=None,frozen_cut=None):
    """Research-only Dirichlet quarter paths, with native-ledger past-label embargo.

    The integer team-score scenario totals are supplied independently and held
    unchanged. Quarter means blend the pinned original forecast with native past shares.
    Native histories come from the verified ledger or the original audited feature cut.
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
    weights=np.asarray(target.get('predicted_quarters'),dtype=float)
    frozen_means=np.asarray(target.get('prediction'),dtype=float)
    if (weights.shape!=(4,2) or frozen_means.shape!=(2,) or
            not np.isfinite(weights).all() or not np.isfinite(frozen_means).all() or
            not np.allclose(weights.sum(axis=0),frozen_means,rtol=0,atol=1e-6)):
        raise ValueError('QUARTER_ORIGINAL_SNAPSHOT_MEANS_REQUIRED')
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
        for r in ([] if frozen_cut is not None else rows):
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
        if frozen_cut is not None:
            history=_history_from_cut(frozen_cut,target,side)
        if len({x[0] for x in history})!=len(history):
            raise ValueError("QUARTER_DUPLICATE_NATIVE_HISTORY_FIXTURE")
        history.sort(key=lambda a:(a[1],a[0]))
        if frozen_cut is not None:
            # Match the original model recent-team window by fixture IDs.
            recent=set(frozen_cut["features"][side]["recent_game_ids"])
            history=[h for h in history if h[0] in recent]
        if len(history)<MIN_QUARTER_HISTORY:
            raise Abstain("SIX_VERIFIED_PAST_QUARTER_GAMES_PER_SIDE_REQUIRED")
        arr=np.asarray([h[2] for h in history],dtype=float)
        frozen=weights[:,j]/weights[:,j].sum()
        # Fixed prior strength: adjust the mean as well as the uncertainty.
        # Only native past quarter shares enter this estimate.
        w=(8.*frozen+arr.sum(axis=0))/(8.+len(arr))
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
            latest_label_available_utc=history[-1][1],
            original_weights=frozen.tolist(),research_weights=w.tolist())
    if not np.array_equal(out.sum(axis=1),scores):
        raise ValueError("STOCHASTIC_QUARTERS_TEAM_SCORE_CONSERVATION")
    return out,dict(format="RESEARCH_DIRICHLET_CONDITIONAL_QUARTERS_V1",
        seed=seed,concentration=concentrations,history=trace,
        target_original_snapshot_sha256=target_sha256,
        target_generated_at_utc=cutoff,
        history_source="ORIGINAL_FROZEN_FEATURE_CUT" if frozen_cut is not None else "FIRST_FORECAST_LEDGER_ONLY",
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
    # This is a prospective input gate, not a retroactive archive rewrite.
    if publication["first_archived_at_utc"] >= fixture["fixture_start_utc"] - PREMATCH_MINIMUM_LEAD_SECONDS:
        return dict(status="BLOCKED_PLAYER_PUBLICATION_AFTER_PREMATCH_CUTOFF",
            player_effect_applied=False,production_enabled=False)
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


def _point_metrics(rows):
    if not rows:
        return None
    pred=np.asarray([r["forecast_before"] for r in rows],dtype=float)
    cand=np.asarray([r["forecast_candidate"] for r in rows],dtype=float)
    actual=np.asarray([r["regulation_actual"] for r in rows],dtype=float)
    result={}
    for name, weights in (("home",[1,0]),("away",[0,1]),("total",[1,1]),("margin",[1,-1])):
        old=(pred-actual)@weights
        new=(cand-actual)@weights
        result[name]=dict(original_mae=float(np.abs(old).mean()),
            candidate_mae=float(np.abs(new).mean()),original_bias=float(old.mean()),
            candidate_bias=float(new.mean()),original_rmse=float(np.sqrt(np.mean(old**2))),
            candidate_rmse=float(np.sqrt(np.mean(new**2))))
    return result


def quarter_comparison(ledger, *, asof_utc, scenarios=4096, cut_loader=None):
    """Paired conditional allocation audit on original forecasts, no final score input.

    Fixed rounded predicted team totals isolate allocation quality; interval
    scores are NOT full predictive uncertainty or calibrated market odds.
    """
    from hybrid_engine.distributions import periods_for_scores
    if type(scenarios) is not int or not 1024<=scenarios<=10000:
        raise ValueError("QUARTER_AUDIT_SCENARIO_BUDGET")
    base=first_forecast_review(ledger,asof_utc=asof_utc)
    by_sha={r["snapshot_sha256"]:r for r in ledger["forecasts"]}
    if len(by_sha)!=len(ledger["forecasts"]):
        raise ValueError("QUARTER_AMBIGUOUS_SNAPSHOT")
    trace=[]; reasons=Counter()
    for group in base["walk_forward_shadow"]:
        for entry in group["trace"]:
            row=by_sha[entry["original_snapshot_sha256"]]
            if row["league"]!="NBA":
                continue
            if row.get("predicted_quarters") is None:
                reasons["MISSING_ORIGINAL_QUARTERS"]+=1
                continue
            scores=np.tile(np.rint(row["prediction"]).astype(np.int32),(scenarios,1))
            try:
                cut=cut_loader(row) if cut_loader is not None else None
                candidate,meta=stochastic_quarters_from_frozen_scores(
                    scores,ledger,target_sha256=row["snapshot_sha256"],frozen_cut=cut)
            except Abstain as exc:
                reasons[str(exc)]+=1
                continue
            except (OSError,ValueError,KeyError,TypeError) as exc:
                if cut_loader is None: raise
                reasons["FROZEN_SOURCE_REJECTED:"+type(exc).__name__+":"+str(exc)[:140]]+=1
                continue
            old=periods_for_scores(scores,np.asarray(row["predicted_quarters"],dtype=float))
            actual=np.asarray([row["actual_periods"][s][:4] for s in ("home","away")]).T
            markets={}
            for name, sl in (("1Q",slice(0,1)),("2Q",slice(1,2)),("3Q",slice(2,3)),
                             ("4Q",slice(3,4)),("1H",slice(0,2)),("2H",slice(2,4))):
                y=float(actual[sl].sum())
                a=old[:,sl,:].sum(axis=(1,2)); b=candidate[:,sl,:].sum(axis=(1,2))
                def crps(samples):
                    ordered=np.sort(samples.astype(float))
                    n=len(ordered)
                    return float(np.abs(ordered-y).mean() -
                        np.dot(2*np.arange(n)-n+1,ordered)/(n*n))
                markets[name]=dict(original_abs_error=abs(float(a.mean())-y),
                    candidate_abs_error=abs(float(b.mean())-y),
                    original_crps=crps(a),candidate_crps=crps(b))
            trace.append(dict(fixture_id=row["fixture_id"],snapshot_sha256=row["snapshot_sha256"],
                season=row["season"],model_version=row["model_version"],
                forecast_generated_at_utc=row["prediction_generated_at_utc"],
                fixed_predicted_scores=scores[0].tolist(),markets=markets,history=meta["history"]))
    cohorts=[]
    for season,version in sorted({(r["season"],r["model_version"]) for r in trace}):
        rows=[r for r in trace if (r["season"],r["model_version"])==(season,version)]
        metrics={}
        for name in ("1Q","2Q","3Q","4Q","1H","2H"):
            items=[r["markets"][name] for r in rows]
            metrics[name]={k:float(np.mean([i[k] for i in items])) for k in items[0]}
        cohorts.append(dict(season=season,model_version=version,n=len(rows),metrics=metrics))
    return dict(status="CONDITIONAL_ALLOCATION_ONLY_NOT_FULL_FORECAST_CALIBRATION",
        verified_finals=base["matched_verified_finals"],paired_n=len(trace),
        history_source="ORIGINAL_FROZEN_FEATURE_CUT" if cut_loader is not None else "FIRST_FORECAST_LEDGER_ONLY",
        excluded=dict(reasons),scenarios=scenarios,cohorts=cohorts,trace=trace,
        actual_target_scores_used_as_inputs=False,production_enabled=False,automatic_promotion=False)


def candidate_admission_diagnostics(metrics, *, paired_n):
    """Fail-closed research diagnostics, never a production promotion decision.

    A lower total MAE must not conceal worse team/margin errors. The existing
    2% relative improvement benchmark is a screening threshold only.
    Historical replay is not independent prospective evidence.
    """
    reasons = []
    if type(paired_n) is not int or paired_n <= 0 or not metrics:
        reasons.append("NO_PAIRED_EVIDENCE")
    else:
        for component in ("home", "away", "total", "margin"):
            m = metrics.get(component, {})
            vals = [m.get(k) for k in ("original_mae", "candidate_mae",
                                       "original_rmse", "candidate_rmse")]
            if any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 for v in vals):
                reasons.append("INVALID_" + component.upper() + "_METRICS")
                continue
            old, new, old_rmse, new_rmse = vals
            if component == "total":
                if old == 0 or (old-new)/old < .02:
                    reasons.append("TOTAL_RELATIVE_MAE_IMPROVEMENT_BELOW_2_PERCENT")
            elif new > old + 1e-9:
                reasons.append(component.upper() + "_MAE_WORSENED")
            if new_rmse > old_rmse + 1e-9:
                reasons.append(component.upper() + "_RMSE_WORSENED")
    return dict(status="REJECT_RESEARCH_SCREEN" if reasons else "EXPLORATORY_SCREEN_PASSED",
                reasons=reasons, paired_n=paired_n,
                independent_prospective_evidence=False,
                production_enabled=False, automatic_promotion=False)


def margin_preserving_comparison(rows):
    """Common-mode correction: retain the original margin, isolate total error."""
    pairs=[]
    for r in rows:
        old=r["forecast_before"]
        shift=sum(r["adjustment"])/2.
        shift=max(shift,-min(old))
        candidate=[v+shift for v in old]
        if not math.isclose(candidate[0]-candidate[1],old[0]-old[1],abs_tol=1e-9,rel_tol=0):
            raise ValueError("COMMON_MODE_MARGIN_INVARIANT")
        pairs.append(dict(r,forecast_candidate=candidate))
    return dict(status="EXPLORATORY_COMMON_MODE_NOT_PRODUCTION",n=len(pairs),
        score_components=_point_metrics(pairs),margin_preserved=True,
        adjusted_n=sum(r["forecast_before"]!=r["forecast_candidate"] for r in pairs),
        production_enabled=False)


def main(argv=None):
    import argparse
    import json
    from ledger_reports import LedgerReports
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger",required=True)
    parser.add_argument("--asof-utc",type=int,default=None)
    parser.add_argument("--summary-only",action="store_true")
    parser.add_argument("--assets-directory",default=None,help="Original frozen forecast assets; read only")
    parser.add_argument("--player-directory",default=None,help="Existing native player evidence directory; read only")
    args=parser.parse_args(argv)
    asof=int(time.time()) if args.asof_utc is None else args.asof_utc
    ledger=LedgerReports(args.ledger).read("NBA")
    result=conditional_bias_comparison(ledger,asof_utc=asof)
    for g in result["cohorts"]:
        g["score_components"]=_point_metrics(g["trace"])
        g["margin_preserving_candidate"]=margin_preserving_comparison(g["trace"])
        g["admission_diagnostics"]=candidate_admission_diagnostics(g["score_components"],paired_n=g["n"])
        common=g["margin_preserving_candidate"]
        common["admission_diagnostics"]=candidate_admission_diagnostics(common["score_components"],paired_n=common["n"])
        g["adjusted_n"]=sum(any(x!=0 for x in r["adjustment"]) for r in g["trace"])
    loader=frozen_cut_loader(args.ledger,args.assets_directory) if args.assets_directory else None
    result["quarter_audit"]=quarter_comparison(ledger,asof_utc=asof,cut_loader=loader)
    result["player_audit"]={"status":"NOT_CHECKED_NO_PLAYER_DIRECTORY","player_effect_applied":False}
    if args.player_directory is not None:
        from pathlib import Path
        from hybrid_engine.player_shadow import readiness,performance
        from hybrid_engine.player_inputs import recent_collection_diagnostics
        if not Path(args.player_directory).is_dir():
            raise ValueError("EXISTING_PLAYER_DIRECTORY_REQUIRED")
        result["player_audit"]={"readiness":readiness(args.player_directory),
            "performance":performance(args.player_directory,args.ledger,asof_utc=asof),
            "collection_diagnostics":recent_collection_diagnostics(args.player_directory,limit=5),
            "player_effect_applied":False}
    if args.summary_only:
        result["quarter_audit"].pop("trace",None)
        result["cohorts"]=[{k:v for k,v in g.items() if k!="trace"} for g in result["cohorts"]]
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
