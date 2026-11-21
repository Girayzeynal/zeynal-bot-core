"""Read-only, sign-separated diagnosis of an existing signed quality report.

Negative means forecast total below verified regulation total. Positive original
cases are used only for an immutable fingerprint/count; no corrections, replays,
calibration, forecast generation or model changes occur.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from core.team_identity import digest

VERSION = "ZEYNAL_NEGATIVE_ERROR_AUDIT_READ_ONLY_V1"
MAX_REPORT_BYTES = 64 * 1024 * 1024
TOLERANCE = 1e-7


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("NEGATIVE_REVIEW_NONFINITE_ERROR")
    return float(value)


def analyze(document):
    """Consume an existing verified quality JSON envelope, never edit it."""
    if not isinstance(document, dict) or "payload" not in document:
        raise ValueError("NEGATIVE_REVIEW_WRAPPER_REQUIRED")
    payload = document["payload"]
    if digest(payload) != document.get("sha256"):
        raise ValueError("NEGATIVE_REVIEW_REPORT_PIN_MISMATCH")
    if payload.get("format") != "PHASE92_READ_ONLY_QUALITY_REPORT_V1":
        raise ValueError("NEGATIVE_REVIEW_UNSUPPORTED_REPORT")
    analysis = payload.get("error_review")
    if not isinstance(analysis, dict) or analysis.get("format") != "FROZEN_FORECAST_ERROR_REVIEW_V1":
        raise ValueError("NEGATIVE_REVIEW_ERROR_AUDIT_MISSING")
    output = []
    for group in analysis["groups"]:
        cases = group["cases"]
        if group["n"] != len(cases):
            raise ValueError("NEGATIVE_REVIEW_CASE_COUNT_CONFLICT")
        seen = set()
        below, above, flat = [], [], []
        paired = {}
        for pair in group.get("matched_input_baseline", {}).get("pairs", []):
            key = (pair["fixture_id"], pair["snapshot_sha256"])
            if key in paired:
                raise ValueError("NEGATIVE_REVIEW_DUPLICATE_PAIR")
            paired[key] = pair
        for case in cases:
            fid = case["fixture_id"]
            sha = case["snapshot_sha256"]
            key = (fid, sha)
            if key in seen:
                raise ValueError("NEGATIVE_REVIEW_DUPLICATE_FIXTURE")
            seen.add(key)
            predicted = _number(case["prediction_total"])
            actual = _number(case["regulation_total"])
            signed = _number(case["signed_total_error"])
            if not math.isclose(predicted-actual, signed, rel_tol=0, abs_tol=1e-5):
                raise ValueError("NEGATIVE_REVIEW_SIGN_IDENTITY_CONFLICT")
            if signed < -TOLERANCE:
                profile = case.get("input_profile")
                if case.get("input_profile_status") != "FROZEN_INPUTS_VERIFIED":
                    profile = None
                history = profile.get("history", {}) if profile else {}
                pair = paired.get(key)
                if pair and not math.isclose(
                        _number(pair["frozen_model_error"]), signed,
                        rel_tol=0, abs_tol=1e-5):
                    raise ValueError("NEGATIVE_REVIEW_BASELINE_PAIR_CONFLICT")
                below.append(dict(
                    fixture_id=fid,
                    provider_fixture_ids=case.get("provider_fixture_ids", []),
                    home=case.get("home"), away=case.get("away"),
                    predicted_regulation_total=predicted,
                    actual_regulation_total=actual,
                    signed_error=signed,
                    quarter_signed_errors=case.get("period_total_errors"),
                    native_input_profile_verified=profile is not None,
                    new_games_since_fit_by_side=(
                        {side: item["new_games_since_fit"] for side, item in history.items()}
                        if history else None),
                    fit_age_days=(profile["fit_age_seconds"]/86400 if profile else None),
                    training_games=(profile["training_games"] if profile else None),
                    historical_cross_mean_signed_error=(
                        _number(pair["retrospective_baseline_error"]) if pair else None),
                    findings=case.get("findings", [])))
            elif signed > TOLERANCE:
                # Fingerprint original positive records; never alter or retarget them.
                above.append(dict(fixture_id=fid, snapshot_sha256=sha,
                                  original_signed_error=signed))
            else:
                flat.append(dict(fixture_id=fid, snapshot_sha256=sha))
        negatives = sorted(below, key=lambda c: (c["signed_error"], c["fixture_id"]))
        quarters = [c["quarter_signed_errors"] for c in negatives
                    if isinstance(c["quarter_signed_errors"], list)
                    and len(c["quarter_signed_errors"]) == 4]
        base_pairs = [c for c in negatives if c["historical_cross_mean_signed_error"] is not None]
        n = len(negatives)
        output.append(dict(
            cohort=group["cohort"], settled=group["n"], day_clusters=group["day_clusters"],
            negative_count=n, positive_untouched_count=len(above), zero_count=len(flat),
            negative_mean_signed_error=(sum(c["signed_error"] for c in negatives)/n if n else None),
            negative_mae=(sum(abs(c["signed_error"]) for c in negatives)/n if n else None),
            negative_quarter_mae=(
                [sum(abs(q[i]) for q in quarters)/len(quarters) for i in range(4)]
                if quarters else None),
            negative_matched_reference=dict(
                pairs=len(base_pairs),
                model_mae=(sum(abs(c["signed_error"]) for c in base_pairs)/len(base_pairs)
                           if base_pairs else None),
                retrospective_reference_mae=(
                    sum(abs(c["historical_cross_mean_signed_error"]) for c in base_pairs) /
                    len(base_pairs) if base_pairs else None),
                warning="POST_OUTCOME_NEGATIVE_ONLY_SELECTION__EXPLORATORY_NOT_A_PREGAME_TRIGGER"),
            most_negative_cases=negatives[:12],
            positive_original_case_fingerprint=digest(sorted(above, key=lambda c: c["fixture_id"])),
            positive_cases_modified=False,
            score_or_model_adjustment_performed=False))
    return dict(format=VERSION, source_report_sha256=document["sha256"],
                signed_error_definition="PREDICTED_REGULATION_TOTAL_MINUS_ACTUAL_REGULATION_TOTAL",
                positive_deviations="PROTECTED_NO_ADJUSTMENT",
                negative_deviations="DIAGNOSTIC_ONLY",
                cohorts=output, model_changed=False, original_forecasts_changed=False,
                calibration_fit=False, prediction_generation=False,
                caveat="The eventual error sign is unknown before tipoff; retrospective negative labels cannot be used as an inference-time correction rule.")


def report_file(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("NEGATIVE_REVIEW_REGULAR_EXISTING_REPORT_REQUIRED")
    with path.open("rb") as handle:
        raw = handle.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("NEGATIVE_REVIEW_REPORT_TOO_LARGE")
    before = hashlib.sha256(raw).hexdigest()
    result = analyze(json.loads(raw))
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise ValueError("NEGATIVE_REVIEW_REPORT_CHANGED_DURING_READ")
    result["report_bytes_unchanged"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True,
                        help="Exact existing quality-<sha>.json path; never chooses a report automatically")
    args = parser.parse_args()
    print(json.dumps(report_file(args.report), ensure_ascii=False,
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
