"""Read-only first-publication error census and leakage-safe exploratory bias shadow.

Input MUST be LedgerReports.read output: it authenticates immutable snapshot
receipts, native fixture identity and regulation-only finals. This module never
writes an archive, changes a prediction, fits a live model or promotes a shadow.
A new version is used instead of mutating sealed 100-game protocols.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
import time

VERSION = "FIRST_FORECAST_WALK_FORWARD_V1"
PRIOR_STRENGTH = 8.0
MAX_ROWS = 1000


def _stamp(value):
    return type(value) is int and value > 0


def _score_pair(value):
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(type(x) in (int, float) and math.isfinite(x) and x >= 0 for x in value)
    )


def _summarize(rows):
    if not rows:
        return dict(n=0, team_mae=None, total_mae=None, total_rmse=None,
                    signed_total_bias=None, home_mae=None, away_mae=None)
    e = [[float(p - a) for p, a in zip(r["prediction"], r["actual"])] for r in rows]
    totals = [x[0] + x[1] for x in e]
    n = len(rows)
    return dict(
        n=n,
        team_mae=sum(abs(x) for pair in e for x in pair) / (2 * n),
        total_mae=sum(abs(x) for x in totals) / n,
        total_rmse=math.sqrt(sum(x*x for x in totals) / n),
        signed_total_bias=sum(totals) / n,
        home_mae=sum(abs(x[0]) for x in e) / n,
        away_mae=sum(abs(x[1]) for x in e) / n,
    )


def review(verified_report, *, asof_utc):
    """Chronologically review every *first* archived fixture, n>=1.

    Only labels AVAILABLE before a later forecast's generation time may train
    its exploratory bias correction. A fixed eight-prior shrinkage is a
    research design choice, not a tuned or validated optimum. Different fitted
    SHAs may occur within one declared chronological model-version strategy,
    but exact-fit descriptives stay separate and are never pooled for
    inferential model superiority.
    """
    if (not _stamp(asof_utc) or asof_utc > int(time.time())
            or not isinstance(verified_report, dict)
            or verified_report.get("status") != "VERIFIED_LIVE_REPORT"
            or verified_report.get("scope") != "REGULATION_ONLY"
            or verified_report.get("query_read_only") is not True
            or verified_report.get("research_backtests_included") is not False):
        raise ValueError("FIRST_FORECAST_VERIFIED_READONLY_LEDGER_REQUIRED")
    rows = verified_report.get("forecasts")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("FIRST_FORECAST_ROW_BUDGET")
    excluded = Counter()
    first = {}
    conflicts = set()
    observations = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("FIRST_FORECAST_INVALID_ROW")
        identity = tuple(row.get(k) for k in ("league", "season", "fixture_id",
                                              "model_version", "model_digest"))
        if not all(isinstance(x, str) and x for x in identity):
            excluded["INCOMPLETE_IDENTITY"] += 1
            continue
        generated, created, archived, tipoff = (
            row.get(k) for k in ("prediction_generated_at_utc", "created_utc",
                                 "first_archived_at_utc", "fixture_start_utc"))
        pin = row.get("snapshot_sha256")
        # Older authenticated live snapshots may lack a separate generation
        # timestamp. Their created/commit clocks prove PREMATCH publication for
        # descriptive error metrics, but not a point-in-time shadow target.
        # Never silently substitute a later timestamp as if it were generated.
        if (not all(_stamp(t) for t in (created, archived, tipoff))
                or not created <= archived < tipoff
                or (generated is not None
                    and (not _stamp(generated) or generated > created))
                or not isinstance(pin, str) or len(pin) != 64
                or any(c not in "0123456789abcdef" for c in pin)
                or not _score_pair(row.get("prediction"))):
            excluded["INVALID_FIRST_PREMATCH_SNAPSHOT"] += 1
            continue
        if archived > asof_utc:
            excluded["FUTURE_ARCHIVE_AT_ASOF"] += 1
            continue
        actual = row.get("actual")
        if actual is not None:
            available = row.get("label_available_utc")
            if not _score_pair(actual) or not _stamp(available) or available <= tipoff:
                raise ValueError("FIRST_FORECAST_NATIVE_FINAL_OR_CLOCK_CONFLICT")
            periods = row.get("actual_periods")
            if (not isinstance(periods, dict) or set(periods) != {"home", "away"}
                    or any(not isinstance(periods[s], list) or len(periods[s]) < 4
                           or any(type(x) is not int or x < 0 for x in periods[s])
                           for s in ("home", "away"))
                    or any(sum(periods[s][:4]) != actual[i]
                           for i, s in enumerate(("home", "away")))):
                raise ValueError("FIRST_FORECAST_REGULATION_RESULT_REQUIRED")
        key = identity[:3]
        # A conflicting verified result for a fixture must not be hidden by
        # selecting an earlier original from a different predictor version.
        if actual is not None:
            previous = observations.get(key)
            observed = (tuple(actual), tipoff)
            if previous is not None and previous != observed:
                raise ValueError("FIRST_FORECAST_CONFLICTING_NATIVE_FINAL")
            observations[key] = observed
        candidate = dict(row)
        candidate["_explicit_generation_clock"] = generated is not None
        candidate["_prematch_clock_utc"] = generated if generated is not None else created
        old = first.get(key)
        if old is None or (archived, candidate["_prematch_clock_utc"], pin) < (
                old["first_archived_at_utc"], old["_prematch_clock_utc"],
                old["snapshot_sha256"]):
            first[key] = candidate
            conflicts.discard(key)
        if old is not None and archived == old["first_archived_at_utc"] and (
                old["snapshot_sha256"] != pin):
            conflicts.add(key)
    chosen = []
    for key, row in first.items():
        if key in conflicts:
            excluded["AMBIGUOUS_SIMULTANEOUS_FIRST_FORECAST"] += 1
        else:
            chosen.append(row)
    chosen.sort(key=lambda r: (r["_prematch_clock_utc"],
                               r["first_archived_at_utc"], r["fixture_id"]))
    settled, pending = [], 0
    for r in chosen:
        if r.get("actual") is None or r["label_available_utc"] > asof_utc:
            pending += 1
        else:
            settled.append(r)
    by_fit, by_strategy, by_league = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in settled:
        fit = (r["league"], r["season"], r["model_version"], r["model_digest"])
        strat = fit[:3]
        by_fit[fit].append(r)
        by_strategy[strat].append(r)
        by_league[(r["league"], r["season"])].append(r)
    walk = []
    for strategy, cohort in sorted(by_strategy.items()):
        # Forecast ordering, NOT eventual result ordering, controls admissions.
        # An older game's late-settled result is excluded from a later forecast
        # until that native final is actually available.
        cohort.sort(key=lambda r: (r["_prematch_clock_utc"], r["fixture_id"]))
        # An original without explicit generation time is still part of the
        # historical error census and may supply a later AVAILABLE label.
        # It cannot be retrospectively "predicted again" at an invented clock.
        targets = [r for r in cohort if r["_explicit_generation_clock"]]
        shadow = []
        for r in targets:
            prior = [p for p in cohort
                     if p["fixture_id"] != r["fixture_id"]
                     and p["label_available_utc"] < r["prediction_generated_at_utc"]]
            n = len(prior)
            gain = n / (n + PRIOR_STRENGTH)
            error = [
                sum(p["prediction"][i] - p["actual"][i] for p in prior) / n
                if n else 0.0 for i in range(2)
            ]
            corrected = [max(0.0, r["prediction"][i] - gain*error[i])
                         for i in range(2)]
            shadow.append(dict(
                fixture_id=r["fixture_id"], prediction=corrected,
                actual=r["actual"], prior_available_labels=n,
                latest_prior_label_utc=max((p["label_available_utc"] for p in prior),
                                           default=None),
                original_snapshot_sha256=r["snapshot_sha256"],
                prediction_generated_at_utc=r["prediction_generated_at_utc"],
                adjustment=[corrected[i] - r["prediction"][i] for i in range(2)],
            ))
        walk.append(dict(
            league=strategy[0], season=strategy[1], model_version=strategy[2],
            exact_fit_versions=len({r["model_digest"] for r in cohort}),
            strategy_kind="CHRONOLOGICAL_MODEL_VERSION_NOT_SINGLE_FIT",
            original=_summarize(targets), exploratory_shadow=_summarize(shadow),
            descriptive_all_first_forecasts=_summarize(cohort),
            excluded_shadow_targets_missing_generation=len(cohort)-len(targets),
            prior_strength=PRIOR_STRENGTH,
            predictions_with_prior=sum(s["prior_available_labels"] > 0 for s in shadow),
            trace=shadow,
            comparison_status=("DESCRIPTIVE_SHADOW_NOT_PROSPECTIVE_SUPERIORITY"
                               if targets else "SHADOW_NOT_RUN_NO_VERIFIED_GENERATION_CLOCK"),
        ))
    return dict(
        format=VERSION, asof_utc=asof_utc,
        source="LEDGER_REPORTS_NATIVE_AUTHENTICATED_FIRST_COMMIT",
        first_forecasts=len(chosen),
        first_proven_snapshot_utc=min((r["created_utc"] for r in chosen), default=None),
        first_prediction_utc=min(
            (r["prediction_generated_at_utc"] for r in chosen
             if r["_explicit_generation_clock"]), default=None),
        first_forecasts_missing_generation_utc=sum(
            not r["_explicit_generation_clock"] for r in chosen),
        matched_verified_finals=len(settled), pending=pending,
        exclusions=dict(sorted(excluded.items())),
        league_season_descriptives=[
            dict(league=k[0], season=k[1], metrics=_summarize(v),
                 note="CROSS_FIT_DESCRIPTIVE_ONLY_NOT_ONE_FITTED_MODEL")
            for k, v in sorted(by_league.items())],
        exact_fit_descriptives=[
            dict(league=k[0], season=k[1], model_version=k[2],
                 model_digest=k[3], metrics=_summarize(v))
            for k, v in sorted(by_fit.items())],
        walk_forward_shadow=walk,
        historical_100_game_gate_required=False,
        calibration_applied_to_production=False,
        prior_outcomes_only=True,
        no_predictor_fitted_or_modified=True,
        automatic_promotion=False, superiority_claim=False,
        qualification="Exploratory sequential error correction; no independent prospective validation",
    )


def render(report):
    lines = ["ZEYNAL | İLK TAHMİNDEN İTİBAREN HATA DENETİMİ | SALT OKUNUR",
             f"İlk arşiv: {report['first_forecasts']} · Doğrulanmış sonuç: "
             f"{report['matched_verified_finals']} · Bekleyen: {report['pending']}",
             "100 maç şartı yok; önceki tahminler değiştirilmedi."]
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    def tsi(value):
        return datetime.fromtimestamp(value, timezone.utc).astimezone(
            ZoneInfo("Europe/Istanbul")).strftime("%Y-%m-%d %H:%M:%S TSİ")
    if report["first_proven_snapshot_utc"] is not None:
        lines.append("İlk kanıtlı snapshot zamanı: " +
                     tsi(report["first_proven_snapshot_utc"]))
    if report["first_prediction_utc"] is not None:
        lines.append("İlk açık üretim zamanı: " + tsi(report["first_prediction_utc"]))
    if report["first_forecasts_missing_generation_utc"]:
        lines.append("Ayrı üretim zamanı bulunmayan ilk kayıt: " +
                     str(report["first_forecasts_missing_generation_utc"]) +
                     " (hata ölçümünde var, shadow hedefinden çıkarıldı).")
    for group in report["league_season_descriptives"]:
        m = group["metrics"]
        lines.append(f"{group['league']} · {group['season']} · n={m['n']} · "
                     f"Toplam MAE {m['total_mae']:.2f} · "
                     f"Toplam bias {m['signed_total_bias']:+.2f}")
    for g in report["walk_forward_shadow"]:
        a, b = g["original"], g["exploratory_shadow"]
        if not b["n"]:
            lines.append(f"Deneysel {g['league']} {g['model_version'][:48]}: "
                         "SHADOW YOK — ayrı üretim zaman damgası doğrulanmadı; "
                         f"ilk tahminli gerçek maç={g['descriptive_all_first_forecasts']['n']}.")
        else:
            lines.append(f"Deneysel {g['league']} {g['model_version'][:48]} · n={a['n']} · "
                         f"Geçmiş sonucu mevcut {g['predictions_with_prior']} · "
                         f"ilk MAE {a['total_mae']:.2f} / shadow MAE {b['total_mae']:.2f}")
    if report["exclusions"]:
        lines.append("Dışlananlar: " + ", ".join(
            f"{k}={n}" for k,n in report["exclusions"].items()))
    lines.append("Shadow sonucu canlı tahmin değildir; üstünlük/kalibrasyon onayı yok.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, help="Existing verified SQLite ledger, read-only")
    parser.add_argument("--league", choices=("NBA",), default="NBA")
    parser.add_argument("--asof-utc", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Full trace instead of concise Turkish text")
    args = parser.parse_args(argv)
    from ledger_reports import LedgerReports
    asof = int(time.time()) if args.asof_utc is None else args.asof_utc
    result = review(LedgerReports(args.ledger).read(args.league), asof_utc=asof)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))


if __name__ == "__main__":
    main()
