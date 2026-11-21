"""Read-only inventory of authentic pre-forecast NBA TOTAL market-line evidence.

A direction computed today against an original quote is a retrospective research
comparison, not proof an ALT/UST decision was originally published. ESPN quotes
lack an attested bookmaker overtime settlement contract, so direction win rates
are intentionally not calculated. Never changes forecasts or positive errors.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from core.team_identity import digest
from hybrid_engine.market_evidence_report import observed_market_evidence
from live_analysis_ledger import LiveAnalysisLedger

VERSION = "ZEYNAL_PREGAME_DIRECTION_EVIDENCE_CENSUS_V1"
MAX_REPORT = 64 * 1024 * 1024
MAX_ORIGINAL = 512 * 1024
MAX_FIXTURES = 1000


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("DIRECTION_FINITE_VALUE_REQUIRED")
    return float(value)


def side(value, line):
    return "UST" if value > line else "ALT" if value < line else "ESIT"


def quote_row(observation, forecast, actual):
    """Pure, traceable mean-vs-line comparison. NOT original recorded direction."""
    if observation.get("market") != "TOTAL":
        raise ValueError("DIRECTION_ONLY_TOTAL_MARKET")
    if observation.get("settlement_scope") not in ("UNKNOWN", "REGULATION_ONLY"):
        raise ValueError("DIRECTION_UNRECOGNIZED_SCOPE")
    mean = finite(forecast)
    line = finite(observation["line"])
    if line <= 0 or line > 1000:
        raise ValueError("DIRECTION_INVALID_TOTAL_LINE")
    inferred = side(mean, line)
    return dict(
        bookmaker=observation["bookmaker"], market="FULL_TOTAL", line=line,
        original_model_total=mean,
        original_model_mean_relative_to_line=inferred,
        # This is a newly COMPUTED research classifier, never an old pick.
        original_direction_publication_proven=False,
        reconstructed_from_frozen_mean_only=True,
        native_quote_sha256=observation["quote_sha256"],
        quote_observed_utc=observation["observed_at_utc"],
        age_at_original_prediction_seconds=observation["age_at_prediction_seconds"],
        quote_fresh_at_prediction=(observation["freshness_status"]=="FRESH_AT_PREDICTION"),
        bookmaker_settlement_scope=observation["settlement_scope"],
        actual_regulation_total=(None if actual is None else finite(actual)),
        research_regulation_only_side=(None if actual is None else side(finite(actual), line)),
        official_bookmaker_direction_result=None,
        reason_no_real_direction_hit_rate=(
            "NO_PROVEN_ORIGINAL_PUBLISHED_PICK_AND_BOOKMAKER_SETTLEMENT_UNVERIFIED"))



def research_direction_summary(fixtures):
    """Descriptive original-mean-vs-quote regulation comparison, not published picks.

    Exactly one FRESH original TOTAL quote per settled fixture is admitted to
    the per-game headline to avoid counting bookmakers as independent games.
    Multiple books/lines are reported as ambiguous, not cherry-picked.
    """
    matrix=Counter()
    by_book={}
    by_gap={}
    signed_groups={}
    by_overtime={}
    disagreements=[]
    status=Counter()
    for fixture in fixtures:
        observed=fixture["observed_total_quote_rows"]
        if not fixture["actual_native_regulation_result_available"]:
            status["without_verified_final"]+=1
            continue
        if not observed:
            status["with_final_but_no_quote"]+=1
            continue
        fresh=[x for x in observed if x["quote_fresh_at_prediction"]]
        if not fresh:
            status["only_stale_quotes"]+=1
            continue
        if len(fresh)!=1:
            status["multiple_fresh_quotes_ambiguous_fixture"]+=1
            continue
        q=fresh[0]
        pred=q["original_model_mean_relative_to_line"]
        realized=q["research_regulation_only_side"]
        if realized is None:
            raise ValueError("DIRECTION_MISSING_SETTLED_REGULATION_SIDE")
        if pred=="ESIT":
            status["model_on_barem_no_direction"]+=1
            continue
        if realized=="ESIT":
            status["regulation_push_not_decided"]+=1
            continue
        if pred not in ("ALT","UST") or realized not in ("ALT","UST"):
            raise ValueError("DIRECTION_UNKNOWN_SIDE")
        if not q["reconstructed_from_frozen_mean_only"] or q["original_direction_publication_proven"]:
            raise ValueError("DIRECTION_RESEARCH_SCOPE_CONFLICT")
        mean=finite(q["original_model_total"])
        actual=finite(q["actual_regulation_total"])
        line=finite(q["line"])
        distance=abs(mean-line)
        if distance<3: bucket="0-3"
        elif distance<7: bucket="3-7"
        else: bucket="7+"
        ok=pred==realized
        matrix[pred+"_"+realized]+=1
        status["eligible_unique_fixtures"]+=1
        status["research_direction_matched" if ok else "research_direction_mismatched"]+=1
        for target,key in ((by_book,q["bookmaker"]),(by_gap,bucket),
                           (signed_groups,"PRED_MINUS_ACTUAL_POSITIVE" if mean>actual else "PRED_MINUS_ACTUAL_NEGATIVE" if mean<actual else "ZERO"),
                           (by_overtime,"OVERTIME_PRESENT" if (fixture.get("overtime_points_excluded") or 0)>0 else
                            "NO_OVERTIME" if fixture.get("overtime_points_excluded") is not None else "OVERTIME_UNKNOWN")):
            item=target.setdefault(key,dict(n=0,matched=0,mismatched=0))
            item["n"]+=1
            item["matched" if ok else "mismatched"]+=1
        if not ok:
            disagreements.append(dict(
                fixture_id=fixture["fixture_id"],
                provider_fixture_ids=fixture["provider_fixture_ids"],
                home=fixture.get("home"),away=fixture.get("away"),
                bookmaker=q["bookmaker"],line=line,
                model_total=mean,actual_regulation_total=actual,
                frozen_model_minus_line=mean-line,
                absolute_model_line_distance=distance,
                mean_vs_line_side=pred,actual_regulation_side=realized,
                quote_age_seconds=q["age_at_original_prediction_seconds"]))
    n=status["eligible_unique_fixtures"]
    status["settled_unassessable"]=sum(status[k] for k in (
        "with_final_but_no_quote","only_stale_quotes",
        "multiple_fresh_quotes_ambiguous_fixture","model_on_barem_no_direction",
        "regulation_push_not_decided"))
    if status["research_direction_matched"]+status["research_direction_mismatched"]!=n:
        raise ValueError("DIRECTION_RESEARCH_PARTITION_CONFLICT")
    return dict(
        label="RECONSTRUCTED_FROZEN_MEAN_VS_ORIGINAL_LINE__RESEARCH_ONLY",
        status_counts=dict(status),
        eligible_unique_fixtures=n,
        matched=status["research_direction_matched"],
        mismatched=status["research_direction_mismatched"],
        descriptive_regulation_direction_agreement=(status["research_direction_matched"]/n if n else None),
        confusion_matrix=dict(matrix),
        research_side_counts=dict(
            model_ALT=matrix["ALT_ALT"]+matrix["ALT_UST"],
            model_UST=matrix["UST_ALT"]+matrix["UST_UST"],
            actual_regulation_ALT=matrix["ALT_ALT"]+matrix["UST_ALT"],
            actual_regulation_UST=matrix["ALT_UST"]+matrix["UST_UST"]),
        descriptive_constant_side_references=dict(
            always_ALT=(matrix["ALT_ALT"]+matrix["UST_ALT"])/n if n else None,
            always_UST=(matrix["ALT_UST"]+matrix["UST_UST"])/n if n else None,
            reference_class="POSTHOC_BASE_RATES_NOT_PREGAME_PICKS_OR_VALIDATED_STRATEGY"),
        by_bookmaker=dict(sorted(by_book.items())),
        by_original_mean_line_gap=dict(sorted(by_gap.items())),
        by_score_error_sign=dict(sorted(signed_groups.items())),
        by_overtime_status=dict(sorted(by_overtime.items())),
        mismatches_sorted_by_original_mean_line_distance=sorted(
            disagreements,key=lambda x:(-x["absolute_model_line_distance"],x["fixture_id"])),
        published_pregame_direction_accuracy=None,
        official_bookmaker_settlement_accuracy=None,
        confidence_calibration_proven=False,
        no_selection_or_correction_performed=True,
        caveat="ORIGINAL_MEAN_VS_QUOTE_RECONSTRUCTED_AFTER_OUTCOME; NOT THE HISTORIC TELEGRAM DECISION. MARKET OVERTIME SCOPE NOT VERIFIED. DO NOT FLIP DIRECTIONS OR TUNE GAP BUCKETS USING THESE RESULTS.")


def frozen_qmc_report(rows):
    """Original-sample-sha-verified raw O/U probability side, regulation ONLY.

    This is not a recovered published Telegram selection nor bookmaker-bet
    settlement. It cannot attest a decision issued before tipoff.
    """
    matrix=Counter()
    differences=[]
    no_side=0
    valid=0
    proper_pairs=[]
    conditional_side_records=[]
    for row in rows:
        evidence=row.get("frozen_qmc_evidence")
        if evidence is None:
            continue
        valid+=1
        direction=evidence["raw_more_likely_side"]
        actual=evidence["research_regulation_only_side"]
        if direction=="ESIT" or actual=="ESIT":
            no_side+=1
            continue
        if direction not in ("ALT","UST") or actual not in ("ALT","UST"):
            raise ValueError("DIRECTION_REPLAY_SIDE_CONFLICT")
        matrix[direction+"_"+actual]+=1
        pmodel=evidence.get("model_conditional_over_probability")
        pmarket=evidence.get("market_no_vig_over_probability")
        if pmodel is not None and pmarket is not None:
            y=1 if actual=="UST" else 0
            pmodel=finite(pmodel)
            pmarket=finite(pmarket)
            if not 0<=pmodel<=1 or not 0<pmarket<1:
                raise ValueError("DIRECTION_MODEL_OR_PRICE_PROBABILITY_RANGE")
            proper_pairs.append((pmodel,pmarket,y))
            pside=pmodel if direction=="UST" else 1-pmodel
            reference_side=pmarket if direction=="UST" else 1-pmarket
            if pside<0.5-1e-12:
                raise ValueError("DIRECTION_MODEL_SIDE_PROBABILITY_CONFLICT")
            conditional_side_records.append(dict(
                fixture_id=row["fixture_id"],
                provider_fixture_ids=row["provider_fixture_ids"],
                predicted_side=direction,actual_regulation_side=actual,
                matched=(direction==actual),
                original_line=finite(evidence["line"]),
                original_model_direction_probability=pside,
                original_market_implied_direction_probability=reference_side,
                model_brier_over=(pmodel-y)**2,
                market_brier_over=(pmarket-y)**2))
        if direction!=evidence["original_mean_side"]:
            differences.append(dict(fixture_id=row["fixture_id"],
                provider_fixture_ids=row["provider_fixture_ids"],
                original_model_mean_side=evidence["original_mean_side"],
                sample_probability_side=direction,
                raw_under_probability=evidence["raw_under_probability"],
                raw_over_probability=evidence["raw_over_probability"],
                line=evidence["line"],
                actual_regulation_side=actual))
    decided=sum(matrix.values())
    price_model_comparison=None
    if proper_pairs:
        import math
        n=len(proper_pairs)
        def scores(index):
            probs=[v[index] for v in proper_pairs]
            observed=[v[2] for v in proper_pairs]
            return dict(
                brier=sum((p-y)**2 for p,y in zip(probs,observed))/n,
                log_loss=-sum(
                    y*math.log(max(1e-15,min(1-1e-15,p)))+
                    (1-y)*math.log(1-max(1e-15,min(1-1e-15,p)))
                    for p,y in zip(probs,observed))/n,
                mean_probability_over=sum(probs)/n)
        price_model_comparison=dict(
            n=n, original_qmc_conditional_on_no_push=scores(0),
            timestamped_bookmaker_no_vig_reference=scores(1),
            realized_regulation_over_frequency=sum(v[2] for v in proper_pairs)/n,
            caveat="POSTHOC DESCRIPTIVE ONE-COHORT RESEARCH; BOOKMAKER PRICE SETTLEMENT UNKNOWN, NOT CERTIFIED ODDS FAIRNESS OR FUTURE ROI")
    by_side={}
    for side in ("ALT","UST"):
        subset=[r for r in conditional_side_records if r["predicted_side"]==side]
        if not subset:
            continue
        n=len(subset)
        by_side[side]=dict(
            n=n,matched=sum(r["matched"] for r in subset),
            mismatched=sum(not r["matched"] for r in subset),
            mean_model_selected_side_probability=(
                sum(r["original_model_direction_probability"] for r in subset)/n),
            mean_market_selected_side_probability=(
                sum(r["original_market_implied_direction_probability"] for r in subset)/n),
            mean_qmc_brier_over=sum(r["model_brier_over"] for r in subset)/n,
            mean_market_brier_over=sum(r["market_brier_over"] for r in subset)/n)
    wrongly_confident=sorted(
        (dict(fixture_id=r["fixture_id"],
              provider_fixture_ids=r["provider_fixture_ids"],
              predicted_side=r["predicted_side"],
              actual_regulation_side=r["actual_regulation_side"],
              original_line=r["original_line"],
              original_model_selected_side_probability=(
                  r["original_model_direction_probability"]),
              original_market_selected_side_probability=(
                  r["original_market_implied_direction_probability"]))
         for r in conditional_side_records if not r["matched"]),
        key=lambda r:(-r["original_model_selected_side_probability"],r["fixture_id"]))
    return dict(
        class_="FROZEN_QMC_SAMPLE_SHA_VERIFIED_REPLAY_RESEARCH_ONLY",
        eligible_replays=valid,undecided_replays=no_side,
        assessed_unique_fixtures=decided,
        matched=matrix["ALT_ALT"]+matrix["UST_UST"],
        mismatched=matrix["ALT_UST"]+matrix["UST_ALT"],
        confusion_matrix=dict(matrix),
        paired_raw_probability_vs_market_price=price_model_comparison,
        by_original_qmc_selected_side=by_side,
        strongest_probability_wrong_side_examples=wrongly_confident[:8],
        descriptive_regulation_direction_agreement=(
            (matrix["ALT_ALT"]+matrix["UST_UST"])/decided if decided else None),
        simulated_direction_differs_from_original_mean_count=len(differences),
        original_mean_vs_sample_direction_disagreements=differences,
        published_direction_proven=False,
        calibrated_probabilities=False,
        bookmaker_settlement_proven=False,
        warning="REPLAY OF ORIGINAL PINNED PREMATCH SAMPLES AFTER RESULT; NOT A PUBLISHED DECISION, NOT A VALIDATED BETTING EDGE.")


def original_recent_history_reference(rows):
    """Compare original QMC and already frozen pre-forecast last-N reference.

    All directions are RECONSTRUCTED after the fact from original pregame
    features. No new probabilities, candidate model or published tips are made.
    """
    from collections import Counter
    counts=Counter()
    per_side={"ALT":Counter(),"UST":Counter()}
    fit_age={}
    since_fit={}
    examples=[]
    for row in rows:
        q=row.get("frozen_qmc_evidence")
        if q is None:
            continue
        history=row.get("native_pregame_history_reference")
        if history is None:
            counts["missing_verified_history_reference"]+=1
            continue
        raw=finite(history["preforecast_recent_cross_mean_total"])
        line=finite(q["line"])
        realized=q["research_regulation_only_side"]
        original=q["raw_more_likely_side"]
        baseline=side(raw,line)
        if baseline=="ESIT" or realized=="ESIT" or original=="ESIT":
            counts["undecided_or_push"]+=1
            continue
        if any(x not in ("ALT","UST") for x in (original,baseline,realized)):
            raise ValueError("DIRECTION_REFERENCE_UNKNOWN_SIDE")
        original_ok=original==realized
        reference_ok=baseline==realized
        counts["paired_evaluable"]+=1
        counts["original_qmc_matched"]+=int(original_ok)
        counts["recent_history_reference_matched"]+=int(reference_ok)
        counts["both_matched"]+=int(original_ok and reference_ok)
        counts["original_only_matched"]+=int(original_ok and not reference_ok)
        counts["reference_only_matched"]+=int(reference_ok and not original_ok)
        counts["both_mismatched"]+=int(not original_ok and not reference_ok)
        per_side[original]["n"]+=1
        per_side[original]["qmc_matched"]+=int(original_ok)
        per_side[original]["reference_matched"]+=int(reference_ok)
        age=finite(history["fit_age_days"])
        if age<0:raise ValueError("DIRECTION_NEGATIVE_FIT_AGE")
        age_bucket="0-3d" if age<3 else "3-7d" if age<7 else "7d+"
        new_games=int(history["new_games_since_fit"])
        if new_games<0:raise ValueError("DIRECTION_INVALID_NEW_GAMES")
        new_bucket="0" if new_games==0 else "1-4" if new_games<5 else "5+"
        for target,key in ((fit_age,age_bucket),(since_fit,new_bucket)):
            group=target.setdefault(key,dict(n=0,qmc_matched=0,reference_matched=0))
            group["n"]+=1
            group["qmc_matched"]+=int(original_ok)
            group["reference_matched"]+=int(reference_ok)
        if baseline!=original:
            examples.append(dict(
                provider_fixture_ids=row["provider_fixture_ids"],
                original_qmc_side=original,
                recent_history_reference_side=baseline,
                observed_regulation_side=realized,
                original_qmc_matched=original_ok,
                reference_matched=reference_ok,
                original_total=finite(row["saved_score_total"]),
                preforecast_recent_cross_mean_total=raw,
                original_bookmaker_line=line,
                native_new_games_since_model_fit=new_games,
                original_model_fit_age_days=age))
    return dict(
        record_type="POSTHOC_ORIGINAL_INPUT_REFERENCE_NOT_A_PREGAME_PUBLICATION",
        counts=dict(counts),
        paired_by_original_qmc_side={k:dict(v) for k,v in per_side.items()},
        by_frozen_model_age_days=dict(sorted(fit_age.items())),
        by_new_games_since_fit=dict(sorted(since_fit.items())),
        examples_where_reference_direction_differs_from_qmc=examples[:12],
        original_forecasts_modified=False,
        reference_was_published_forecast=False,
        candidate_selected=False,
        warning="The frozen recent-history reference is a post-result COMPARISON of original available inputs, not a tip, a training algorithm or independent forward validation. Gap buckets are not allowed as new decision thresholds.")

def inspect(data, ledger, assets, *, replay_qmc=False):
    if not isinstance(data, dict) or digest(data.get("payload"))!=data.get("sha256"):
        raise ValueError("DIRECTION_QUALITY_REPORT_PIN_REQUIRED")
    root = Path(ledger).expanduser().absolute()
    directory = Path(assets).expanduser().absolute()
    if root.is_symlink() or not root.is_file() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("DIRECTION_EXISTING_UNMUTATED_LOCAL_SOURCES_REQUIRED")
    p=data["payload"]
    if p.get("format")!="PHASE92_READ_ONLY_QUALITY_REPORT_V1":
        raise ValueError("DIRECTION_QUALITY_REPORT_FORMAT_REQUIRED")
    a=p.get("archive_audit") or {}
    perf=a.get("performance") or {}
    if a.get("performance_status")!="READ_ONLY_NATIVE_VERIFIED" or perf.get("status")!="VERIFIED_LIVE_REPORT":
        raise ValueError("DIRECTION_NATIVE_VERIFIED_REPORT_REQUIRED")
    forecasts=perf.get("forecasts") or []
    error_cases={}
    if replay_qmc:
        reviewed=p.get("error_review") or {}
        if reviewed.get("format")!="FROZEN_FORECAST_ERROR_REVIEW_V1":
            raise ValueError("DIRECTION_NATIVE_HISTORY_REVIEW_REQUIRED")
        for group in reviewed["groups"]:
            for case in group["cases"]:
                key=(case["fixture_id"],case["snapshot_sha256"])
                if key in error_cases:
                    raise ValueError("DIRECTION_DUPLICATE_ERROR_REVIEW_CASE")
                error_cases[key]=case
    if len(forecasts)>MAX_FIXTURES:
        raise ValueError("DIRECTION_FIXTURE_BUDGET")
    results=[]
    # Replay reuses original frozen inputs/parameter SHA pins and exact archived
    # simulation sample SHA; all input data remain read-only.
    if replay_qmc:
        import numpy as np
        from hybrid_engine.decision_audit import replay_snapshot
        from hybrid_engine.prediction_audit import Assets

        class LocalAssetReader:
            def __init__(self, folder):
                self.native=Assets(folder)

            def read(self, variant, ref):
                return self.native.read(ref)

        local_reader=LocalAssetReader(directory)
    with closing(sqlite3.connect(root.as_uri()+"?mode=ro",uri=True,timeout=.3)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        for row in forecasts:
            if row["league"]!="NBA":
                continue
            identity=(row["league"],row["fixture_id"],row["model_digest"])
            record=db.execute(
                """SELECT CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END,
                   sha256 FROM live_analysis_snapshots
                   WHERE league=? AND fixture_id=? AND model_digest=?""",
                (MAX_ORIGINAL,*identity)).fetchone()
            if record is None or record[0] is None:
                raise ValueError("DIRECTION_ORIGINAL_SNAPSHOT_UNAVAILABLE")
            snapshot=LiveAnalysisLedger._decode(record[0],record[1],expected=identity)
            if digest(snapshot)!=row["snapshot_sha256"]:
                raise ValueError("DIRECTION_QUALITY_TO_SNAPSHOT_ID_CONFLICT")
            generated=snapshot["prediction_generated_at_utc"]
            tipoff=snapshot["fixture_start_utc"]
            if generated!=row["prediction_generated_at_utc"] or not 0<generated<tipoff:
                raise ValueError("DIRECTION_ORIGINAL_CLOCK_CONFLICT")
            mean=finite(snapshot["prediction"]["total"])
            if abs(mean-sum(map(finite,row["prediction"])))>1e-5:
                raise ValueError("DIRECTION_ORIGINAL_SCORE_CONFLICT")
            actual=(sum(map(finite,row["actual"])) if row["actual"] is not None else None)
            final_with_ot=row.get("final_with_ot")
            overtime_points=None
            if actual is not None and final_with_ot is not None:
                overtime_points=sum(map(finite,final_with_ot))-actual
                if overtime_points < 0:
                    raise ValueError("DIRECTION_NEGATIVE_OVERTIME_POINTS")
            source_assets=snapshot.get("source_assets",[])
            source_refs={str(i):ref for i,ref in enumerate(source_assets)}
            quotes=observed_market_evidence(directory,source_refs,
                                            snapshot["fixture_id"],generated,tipoff)
            full=[q for q in quotes if q["market"]=="TOTAL"]
            records=[quote_row(q,mean,actual) for q in full]
            qmc_evidence=None
            history_reference=None
            eligible_quotes=[q for q in records if q["quote_fresh_at_prediction"]]
            if replay_qmc and actual is not None and len(eligible_quotes)==1:
                quote=eligible_quotes[0]
                line=finite(quote["line"])
                replay,_=replay_snapshot(dict(snapshot=snapshot,variant="local"),
                                         local_reader)
                sample=replay.values("FULL","TOTAL")
                if len(sample)!=snapshot["intervals"]["scenarios"]:
                    raise ValueError("DIRECTION_REPLAY_SCENARIO_COUNT_CONFLICT")
                under=float(np.mean(sample<line))
                push=float(np.mean(sample==line))
                over=float(np.mean(sample>line))
                if abs(under+push+over-1.0)>1e-8:
                    raise ValueError("DIRECTION_REPLAY_PROBABILITY_CONFLICT")
                # Price is copied only from the already pinned original
                # bookmaker quote. No invented odds and no new download.
                matches=[source for source in full
                         if source["quote_sha256"]==quote["native_quote_sha256"]]
                if len(matches)!=1:
                    raise ValueError("DIRECTION_QUOTE_REPLAY_PRICE_PIN")
                native=matches[0]["native_observation"]["payload"]
                over_odds=finite(native["decimal_over_or_home_cover"])
                under_odds=finite(native["decimal_under_or_away_cover"])
                if not 1<over_odds<=1001 or not 1<under_odds<=1001:
                    raise ValueError("DIRECTION_BOOKMAKER_PRICE_RANGE")
                implied_over=(1/over_odds)/(1/over_odds+1/under_odds)
                no_push=over+under
                if no_push<=0:
                    raise ValueError("DIRECTION_NO_SETTLED_QMC_SIDE_MASS")
                case=error_cases.get((row["fixture_id"],row["snapshot_sha256"]))
                if case is not None and case.get("input_profile_status")=="FROZEN_INPUTS_VERIFIED":
                    profile=case["input_profile"]
                    if (profile["snapshot_sha256"]!=row["snapshot_sha256"] or
                        profile["model_digest"]!=row["model_digest"] or
                        profile["generated_at_utc"]!=generated):
                        raise ValueError("DIRECTION_HISTORY_PROFILE_PIN_OR_CLOCK_CONFLICT")
                    base=profile["retrospective_baseline"]
                    if (base["name"]!="PREGAME_LAST_N_FOR_AGAINST_CROSS_MEAN" or
                        base["published_forecast"] is not False or
                        base["fitted_on_outcome"] is not False or
                        base["eligible_for_live_performance"] is not False):
                        raise ValueError("DIRECTION_HISTORY_REFERENCE_CLASS_CONFLICT")
                    if profile["feature_usage"]["current_scoring_average_updates_full_game_mean"] is not False:
                        raise ValueError("DIRECTION_HISTORY_FROZEN_USAGE_CONFLICT")
                    history_reference=dict(
                        preforecast_recent_cross_mean_total=finite(base["total"]),
                        fit_age_days=finite(profile["fit_age_seconds"])/86400,
                        new_games_since_fit=sum(int(v["new_games_since_fit"])
                                                for v in profile["history"].values()),
                        original_profile_snapshot_sha256=profile["snapshot_sha256"])
                qmc_evidence=dict(
                    line=line,
                    original_mean_side=quote["original_model_mean_relative_to_line"],
                    model_conditional_over_probability=over/no_push,
                    market_no_vig_over_probability=implied_over,
                    observed_decimal_over=over_odds,
                    observed_decimal_under=under_odds,
                    bookmaker_price_scope="PRE_FORECAST_OBSERVED_NO_OT_SETTLEMENT_ATTESTATION",
                    raw_more_likely_side="ALT" if under>over else
                        "UST" if over>under else "ESIT",
                    raw_under_probability=under,
                    raw_over_probability=over,
                    raw_push_probability=push,
                    research_regulation_only_side=quote["research_regulation_only_side"],
                    original_sample_sha256=snapshot["intervals"]["sample_sha256"],
                    exact_sample_pin_verified=True,
                    original_telegram_direction_proven=False,
                    calibrated_probability=False,
                    bookmaker_settlement_rule_verified=False)
            results.append(dict(
                fixture_id=snapshot["fixture_id"],
                provider_fixture_ids=snapshot.get("provider_fixture_ids",[]),
                home=snapshot["home"].get("official_name"),
                away=snapshot["away"].get("official_name"),
                original_prediction_utc=generated,
                saved_score_total=mean,
                native_source_asset_count=len(source_assets),
                archived_total_quotes_before_prediction=len(records),
                observed_total_quote_rows=records,
                actual_native_regulation_result_available=actual is not None,
                overtime_points_excluded=overtime_points,
                frozen_qmc_evidence=qmc_evidence,
                native_pregame_history_reference=history_reference))
    coverage=Counter()
    for r in results:
        coverage["fixtures"]+=1
        coverage["settled"]+=int(r["actual_native_regulation_result_available"])
        coverage["native_pregame_total_quotes"]+=len(r["observed_total_quote_rows"])
        coverage["fixtures_with_total_quote"]+=int(bool(r["observed_total_quote_rows"]))
        coverage["fixtures_with_fresh_total_quote"]+=int(any(
            x["quote_fresh_at_prediction"] for x in r["observed_total_quote_rows"]))
        coverage["fixtures_with_quote_and_result"]+=int(
            bool(r["observed_total_quote_rows"]) and r["actual_native_regulation_result_available"])
    return dict(format=VERSION,quality_report_pin=data["sha256"],
                scope="LOCAL_ORIGINAL_NBA_SNAPSHOT_ASSETS_ONLY_NO_REMOTE_FLY",
                counts=dict(coverage),
                direction_research=research_direction_summary(results),
                frozen_qmc_direction_replay=(frozen_qmc_report(results) if replay_qmc else None),
                original_recent_history_reference=(original_recent_history_reference(results)
                                                   if replay_qmc else None),
                fixture_quotes=[r for r in results if r["archived_total_quotes_before_prediction"]][:100],
                no_quote_fixture_count=len(results)-coverage["fixtures_with_total_quote"],
                actual_original_direction_decision_hit_rate=None,
                actual_bookmaker_direction_settlement_rate=None,
                warning="NO_SAVED_PUBLISHED_DIRECTION_OR_VERIFIED_BOOKMAKER_OT_RULE_IN_THIS_REPORT; MEAN_VS_QUOTE_IS_RETROSPECTIVE_RESEARCH_ONLY",
                market_lines_manufactured=0,
                positive_signed_original_cases_modified=False,
                model_changed=False, original_forecasts_changed=False,
                production_changed=False, no_new_predictions=True)


def inspect_file(quality,ledger,assets,*,replay_qmc=False):
    path=Path(quality).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("DIRECTION_EXISTING_QUALITY_REPORT_REQUIRED")
    with path.open("rb") as stream: raw=stream.read(MAX_REPORT+1)
    if len(raw)>MAX_REPORT:raise ValueError("DIRECTION_REPORT_BUDGET")
    before=hashlib.sha256(raw).hexdigest()
    result=inspect(json.loads(raw),ledger,assets,replay_qmc=replay_qmc)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=before:
        raise ValueError("DIRECTION_REPORT_CONCURRENT_CHANGE")
    result["quality_report_bytes_unchanged"]=True
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report",required=True)
    parser.add_argument("--ledger",required=True)
    parser.add_argument("--assets",required=True)
    parser.add_argument("--summary-only",action="store_true",
                        help="Print coverage and direction confusion only, without fixture cards")
    parser.add_argument("--replay-qmc",action="store_true",
                        help="Verify original QMC SHA and compare its raw ALT/UST probability side")
    parser.add_argument("--prob-summary-only",action="store_true",
                        help="Print only QMC direction and paired original bookmaker price-probability audit")
    args=parser.parse_args()
    report=inspect_file(args.report,args.ledger,args.assets,
                        replay_qmc=args.replay_qmc or args.prob_summary_only)
    if args.prob_summary_only:
        q=report["frozen_qmc_direction_replay"]
        report=dict(format=report["format"],counts=report["counts"],
                    frozen_qmc_direction_replay={
                        k:q[k] for k in (
                            "class_","eligible_replays","assessed_unique_fixtures",
                            "matched","mismatched","confusion_matrix",
                            "descriptive_regulation_direction_agreement",
                            "simulated_direction_differs_from_original_mean_count",
                            "paired_raw_probability_vs_market_price",
                            "by_original_qmc_selected_side",
                            "strongest_probability_wrong_side_examples",
                            "published_direction_proven","bookmaker_settlement_proven",
                            "calibrated_probabilities","warning")},
                    original_forecasts_changed=report["original_forecasts_changed"],
                    positive_signed_original_cases_modified=report["positive_signed_original_cases_modified"],
                    production_changed=report["production_changed"],
                    quality_report_bytes_unchanged=report["quality_report_bytes_unchanged"],
                    original_recent_history_reference=report["original_recent_history_reference"])
    elif args.summary_only:
        report={k:report[k] for k in (
            "format","counts","no_quote_fixture_count","direction_research",
            "frozen_qmc_direction_replay",
            "actual_original_direction_decision_hit_rate",
            "actual_bookmaker_direction_settlement_rate",
            "original_forecasts_changed","positive_signed_original_cases_modified",
            "production_changed","quality_report_bytes_unchanged")}
        report["direction_research"]["mismatches_sorted_by_original_mean_line_distance"]=(
            report["direction_research"]["mismatches_sorted_by_original_mean_line_distance"][:8])
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
