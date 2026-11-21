"""Upper-total-quantile sensitivity on *negative* original outcomes only.

A fixed what-if change to a numeric P95 boundary is not Monte Carlo sampling,
an audited new forecast, calibration, or evidence for a deployable correction.
Never alter saved quantiles, score predictions, input reports or positive cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from core.team_identity import digest

VERSION = "ZEYNAL_NEGATIVE_UPPER_TAIL_SENSITIVITY_READ_ONLY_V1"
FACTORS = (1.0, 1.10, 1.20)
MAX_REPORT_BYTES = 64 * 1024 * 1024
TOLERANCE = 1e-5


def _finite(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("TAIL_NONFINITE_NUMERIC_FIELD")
    return float(value)


def _fixture_key(row):
    return row["fixture_id"], row["snapshot_sha256"]


def _identity(row):
    return tuple(row[field] for field in ("league", "season", "model_version", "model_digest"))


def analyze(doc):
    if not isinstance(doc, dict) or "payload" not in doc:
        raise ValueError("TAIL_SOURCE_WRAPPER_REQUIRED")
    payload = doc["payload"]
    if digest(payload) != doc.get("sha256"):
        raise ValueError("TAIL_SOURCE_PIN_FAILED")
    if payload.get("format") != "PHASE92_READ_ONLY_QUALITY_REPORT_V1":
        raise ValueError("TAIL_SOURCE_FORMAT_REQUIRED")
    audit = payload.get("archive_audit")
    if not isinstance(audit, dict) or audit.get("performance_status") != "READ_ONLY_NATIVE_VERIFIED":
        raise ValueError("TAIL_NATIVE_AUDIT_REQUIRED")
    performance = audit.get("performance")
    if not isinstance(performance, dict) or performance.get("status") != "VERIFIED_LIVE_REPORT":
        raise ValueError("TAIL_LIVE_RESULT_EVIDENCE_REQUIRED")
    error_review = payload.get("error_review")
    if not isinstance(error_review, dict) or error_review.get("format") != "FROZEN_FORECAST_ERROR_REVIEW_V1":
        raise ValueError("TAIL_ORIGINAL_ERROR_REVIEW_REQUIRED")

    by_key = {}
    for row in performance["forecasts"]:
        key = _fixture_key(row)
        if key in by_key:
            raise ValueError("TAIL_DUPLICATE_ORIGINAL_FORECAST")
        by_key[key] = row
    used_keys = set()
    groups_out = []
    for group in error_review["groups"]:
        cohort = group["cohort"]
        ident = _identity(cohort)
        if group["n"] != len(group["cases"]):
            raise ValueError("TAIL_GROUP_CASE_COUNT")
        negative_cases = []
        protected_positive_count = 0
        zero_count = 0
        missing_band_count = 0
        for case in group["cases"]:
            key = _fixture_key(case)
            if key in used_keys:
                raise ValueError("TAIL_DUPLICATE_EVALUATED_FORECAST")
            used_keys.add(key)
            original = by_key.get(key)
            if original is None or _identity(original) != ident:
                raise ValueError("TAIL_ORIGINAL_FORECAST_MISSING_OR_MODEL_CONFLICT")
            if original.get("actual") is None or original.get("label_available_utc") is None:
                raise ValueError("TAIL_NATIVE_FINAL_MISSING")
            prediction = sum(map(_finite, original["prediction"]))
            actual = sum(map(_finite, original["actual"]))
            case_error = _finite(case["signed_total_error"])
            if (abs(prediction-actual-case_error)>TOLERANCE or
                abs(prediction-_finite(case["prediction_total"]))>TOLERANCE or
                abs(actual-_finite(case["regulation_total"]))>TOLERANCE):
                raise ValueError("TAIL_ORIGINAL_SCORE_OR_SIGN_CONFLICT")
            if case_error > 0:
                # Intentionally do not inspect bands or compute any alternative
                # bounds for the protected positive original forecast.
                protected_positive_count += 1
                continue
            if case_error == 0:
                zero_count += 1
                continue
            bandset = original.get("intervals")
            if not bandset or bandset.get("status") != "RAW_MODEL_QUANTILES_NOT_CALIBRATED" or bandset.get("scope") != "REGULATION_ONLY" or bandset.get("scenarios",0)<10000:
                missing_band_count += 1
                continue
            q = bandset.get("markets",{}).get("TOTAL")
            if not q:
                missing_band_count += 1
                continue
            p50, p90, p95 = [_finite(q[k]) for k in ("p50","p90","p95")]
            if not 0 <= p50 <= p90 <= p95:
                raise ValueError("TAIL_QUANTILE_ORDER_CONFLICT")
            negative_cases.append(dict(
                fixture_id=case["fixture_id"],
                provider_fixture_ids=case.get("provider_fixture_ids",[]),
                home=case.get("home"), away=case.get("away"),
                actual_regulation_total=actual,
                predicted_regulation_total=prediction,
                negative_signed_error=case_error,
                original_p50=p50, original_p90=p90, original_p95=p95,
                original_p95_excess=max(0.0,actual-p95),
                fixed_boundary_sensitivity=[
                    dict(upper_tail_span_factor=factor,
                         shadow_p95_boundary=p50+factor*(p95-p50),
                         above_shadow_boundary=actual>p50+factor*(p95-p50),
                         added_boundary_points=(factor-1.0)*(p95-p50))
                    for factor in FACTORS],
                original_p95_changed=False))
        all_negative = sum(_finite(c["signed_total_error"])<0 for c in group["cases"])
        if len(negative_cases)+missing_band_count != all_negative or all_negative+protected_positive_count+zero_count!=group["n"]:
            raise ValueError("TAIL_SIGN_PARTITION_CONFLICT")
        summary = []
        for idx, factor in enumerate(FACTORS):
            hits = sum(c["fixed_boundary_sensitivity"][idx]["above_shadow_boundary"] for c in negative_cases)
            mean_increase = (sum(c["fixed_boundary_sensitivity"][idx]["added_boundary_points"]
                                 for c in negative_cases)/len(negative_cases)
                             if negative_cases else None)
            summary.append(dict(upper_tail_span_factor=factor,
                                negative_cases_with_bands=len(negative_cases),
                                number_above_boundary=hits,
                                conditional_exceedance_fraction=(hits/len(negative_cases)
                                                                 if negative_cases else None),
                                mean_added_boundary_points=mean_increase))
        cases_sorted = sorted(negative_cases,
                              key=lambda x: (-x["original_p95_excess"],x["fixture_id"]))
        groups_out.append(dict(cohort=cohort,settled=group["n"],
                               negative_count=all_negative,
                               protected_positive_count=protected_positive_count,
                               zero_count=zero_count,
                               missing_negative_interval_count=missing_band_count,
                               original_p90_exceedances=sum(c["actual_regulation_total"]>c["original_p90"] for c in negative_cases),
                               original_p95_exceedances=sum(c["original_p95_excess"]>0 for c in negative_cases),
                               sensitivity_summary=summary,
                               original_p95_exceedance_cases=[
                                   c for c in cases_sorted if c["original_p95_excess"]>0][:25],
                               original_quantiles_modified=False,
                               protected_positive_forecasts_modified=False))
    return dict(format=VERSION,source_report_sha256=doc["sha256"],
                cohort_results=groups_out,factors=list(FACTORS),
                outcome_selected_negative_only=True,
                not_a_new_simulation=True,
                not_a_model_calibration=True,
                no_forecast_recomputation=True,
                original_forecasts_modified=False,
                positive_originals_modified=False,
                production_changed=False,
                warning="FIXED_POSTHOC_QUANTILE_BOUNDARY_STRESS_NOT_MONTE_CARLO_OR_PREGAME_MODEL; POSITIVE_CASES_NOT_MODIFIED_OR_REEVALUATED")


def analyze_file(path):
    path=Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("TAIL_EXISTING_REGULAR_FILE_REQUIRED")
    with path.open("rb") as handle:
        raw=handle.read(MAX_REPORT_BYTES+1)
    if len(raw)>MAX_REPORT_BYTES:
        raise ValueError("TAIL_REPORT_SIZE_LIMIT")
    before=hashlib.sha256(raw).hexdigest()
    result=analyze(json.loads(raw))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=before:
        raise ValueError("TAIL_REPORT_CHANGED_DURING_READ")
    result["report_bytes_unchanged"]=True
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report",required=True)
    args=parser.parse_args()
    print(json.dumps(analyze_file(args.report),ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
