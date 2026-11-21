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


def inspect(data, ledger, assets):
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
    if len(forecasts)>MAX_FIXTURES:
        raise ValueError("DIRECTION_FIXTURE_BUDGET")
    results=[]
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
                overtime_points_excluded=overtime_points))
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
                fixture_quotes=[r for r in results if r["archived_total_quotes_before_prediction"]][:100],
                no_quote_fixture_count=len(results)-coverage["fixtures_with_total_quote"],
                actual_original_direction_decision_hit_rate=None,
                actual_bookmaker_direction_settlement_rate=None,
                warning="NO_SAVED_PUBLISHED_DIRECTION_OR_VERIFIED_BOOKMAKER_OT_RULE_IN_THIS_REPORT; MEAN_VS_QUOTE_IS_RETROSPECTIVE_RESEARCH_ONLY",
                market_lines_manufactured=0,
                positive_signed_original_cases_modified=False,
                model_changed=False, original_forecasts_changed=False,
                production_changed=False, no_new_predictions=True)


def inspect_file(quality,ledger,assets):
    path=Path(quality).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("DIRECTION_EXISTING_QUALITY_REPORT_REQUIRED")
    with path.open("rb") as stream: raw=stream.read(MAX_REPORT+1)
    if len(raw)>MAX_REPORT:raise ValueError("DIRECTION_REPORT_BUDGET")
    before=hashlib.sha256(raw).hexdigest()
    result=inspect(json.loads(raw),ledger,assets)
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
    args=parser.parse_args()
    report=inspect_file(args.report,args.ledger,args.assets)
    if args.summary_only:
        report={k:report[k] for k in (
            "format","counts","no_quote_fixture_count","direction_research",
            "actual_original_direction_decision_hit_rate",
            "actual_bookmaker_direction_settlement_rate",
            "original_forecasts_changed","positive_signed_original_cases_modified",
            "production_changed","quality_report_bytes_unchanged")}
        report["direction_research"]["mismatches_sorted_by_original_mean_line_distance"]=(
            report["direction_research"]["mismatches_sorted_by_original_mean_line_distance"][:8])
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
