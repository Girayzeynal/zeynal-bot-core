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
                actual_native_regulation_result_available=actual is not None))
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
    args=parser.parse_args()
    print(json.dumps(inspect_file(args.report,args.ledger,args.assets),
                     ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
