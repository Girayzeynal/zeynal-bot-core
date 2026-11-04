"""Explicit NBA prematch orchestration; no silent prediction persistence.

Caller supplies an initialized ESPN adapter and ledger. All team IDs and
fixture identity are checked before the immutable ledger is touched.
"""
from datetime import datetime, timezone

from prematch_ledger_bridge import record_faz13_for_espn_fixture
from prematch_series_audit import audit_prematch_series
from baseline_numeric_reconciliation import reconcile_team_average
from providers.espn_pace_evidence import pace_available_before
from prediction_inputs import validate_prediction_inputs
from providers.espn_turkey_fixture_lookup import resolve_named_nba_fixture_for_turkey_date


async def persist_resolved_nba_prematch(
    *, adapter, ledger, core, baseline_store=None,
    observed_at_utc: int | None = None,
) -> dict:
    """Resolve ESPN identity and persist only a genuine pre-tipoff FAZ13 output.

    Returns the matched fixture and whether a new immutable row was inserted.
    Callers must ensure the adapter uses an authentic ESPN endpoint and that
    FAZ13 baseline provenance is independently validated. Original input copies
    are mandatory. baseline_store is retained for caller compatibility; its
    current files are never used to reconstruct a prediction's historical inputs.
    """
    ctx = getattr(core, "ctx", None)
    if ctx is None or getattr(ctx, "league", None) != "NBA":
        raise ValueError("Only NBA FAZ13 output is supported")
    if any(not isinstance(getattr(ctx, field, None), str)
           or not getattr(ctx, field).strip() for field in ("date", "home", "away")):
        raise ValueError("Incomplete FAZ13 fixture context")
    observed = int(datetime.now(timezone.utc).timestamp()) if observed_at_utc is None else observed_at_utc
    if type(observed) is not int or observed <= 0:
        raise ValueError("Invalid observation timestamp")
    home_ref = await adapter.resolve_team(ctx.home)
    away_ref = await adapter.resolve_team(ctx.away)
    if not isinstance(home_ref, dict) or not isinstance(away_ref, dict):
        raise ValueError("ESPN team resolution failed")
    home_id, away_id = home_ref.get("id"), away_ref.get("id")
    if any(not isinstance(v, str) or not v.strip() for v in (home_id, away_id)):
        raise ValueError("ESPN team IDs missing")
    from providers.espn_turkey_fixture_lookup import resolve_nba_fixture_for_turkey_date
    fixture = await resolve_nba_fixture_for_turkey_date(
        adapter, ctx.date, home_team_id=home_id, away_team_id=away_id)
    if observed >= fixture["start_ts_utc"]:
        raise ValueError("ESPN fixture has already started")
    meta = getattr(core, "meta", None)
    if not isinstance(meta, dict) or type(meta.get("generated_at")) is not int:
        raise ValueError("Original FAZ13 timestamp missing")
    if meta["generated_at"] > observed:
        raise ValueError("FAZ13 prediction timestamp is in the future")
    # A quality label without evidence is insufficient for canonical records.
    # The source labels below are metadata, not independent authentication.
    for side in ("home", "away"):
        sources = meta.get(f"{side}_sources")
        games = meta.get(f"{side}_baseline_games")
        if (not isinstance(sources, list) or not sources
                or any(not isinstance(src, str) or not src.strip()
                       or src == "MANUAL_BASELINE" for src in sources)
                or type(games) is not int or games < 6):
            raise ValueError(f"Missing auditable {side} baseline source/sample metadata")

    snapshot = meta.get("input_snapshot")
    if snapshot is None:
        raise ValueError("Canonical NBA persistence requires original input snapshot")
    baseline_store = validate_prediction_inputs(
        snapshot, league="NBA", prediction_utc=meta["generated_at"],
        expected_home=meta.get("expected_home"), expected_away=meta.get("expected_away"))
    if snapshot["payload"]["context"] != {k: getattr(ctx, k) for k in ("date", "home", "away")}:
        raise ValueError("Original input snapshot fixture context mismatch")
    # A point-in-time audit of arbitrary rows does not prove FAZ13 used
    # those rows. Audit the input copy captured by FAZ13, never current files.
    for side, team in (("home", ctx.home), ("away", ctx.away)):
        sources = meta[f"{side}_sources"]
        if sources != ["TEAM_BASELINE_STORE"]:
            raise ValueError(f"Unbound {side} baseline source cannot enter canonical ledger")
        key = meta.get(f"{side}_baseline_key")
        if not isinstance(key, str) or not key.strip() or key != team:
            raise ValueError(f"Missing exact {side} baseline key binding")
        evidence = audit_prematch_series(
            baseline_store, league="NBA", team=key,
            prediction_utc=meta["generated_at"], min_games=6,
        )
        declared_count = meta[f"{side}_baseline_games"]
        if declared_count != evidence["eligible_games"]:
            raise ValueError(f"{side} baseline sample count differs from audited series")
        rows = baseline_store.get_series("NBA", key, 100000)
        eligible_rows = [
            row for row in rows
            if type(getattr(row, "ts_utc", None)) is int
            and 0 < row.ts_utc < meta["generated_at"]
            and getattr(row, "timestamp_precision", None) == "exact"
            and isinstance(getattr(row, "game_id", None), str)
            and bool(row.game_id.strip())
            and isinstance(getattr(row, "source", None), str)
            and bool(row.source.strip())
            and row.source != "MANUAL_BASELINE"
            and pace_available_before(row, league="NBA", prediction_utc=meta["generated_at"])
        ]
        average = getattr(core, f"{side}_avg", None)
        if average is None:
            raise ValueError(f"Missing FAZ13 {side} numerical averages")
        reconcile_team_average(
            average, eligible_rows, prediction_utc=meta["generated_at"]
        )
    # The bridge validates finite metadata, but must not trust score fields
    # that disagree with the two independently reconciled team averages.
    home_avg = core.home_avg
    away_avg = core.away_avg
    expected = {
        "expected_home": (home_avg.points_for + away_avg.points_against) / 2,
        "expected_away": (away_avg.points_for + home_avg.points_against) / 2,
    }
    expected["expected_total"] = expected["expected_home"] + expected["expected_away"]
    import math
    for field, calculated in expected.items():
        stated = meta.get(field)
        if (type(stated) not in (int, float)
                or not math.isfinite(stated)
                or abs(stated - calculated) > 0.011):
            raise ValueError(f"FAZ13 {field} disagrees with reconciled baseline")
    inserted = record_faz13_for_espn_fixture(
        ledger, core, fixture, resolved_home_team_id=home_id,
        resolved_away_team_id=away_id)
    return {"fixture": fixture, "inserted": inserted}
