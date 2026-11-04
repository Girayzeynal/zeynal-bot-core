"""Explicit NBA prematch orchestration; no silent prediction persistence.

Caller supplies an initialized ESPN adapter and ledger. All team IDs and
fixture identity are checked before the immutable ledger is touched.
"""
from datetime import datetime, timezone

from prematch_ledger_bridge import record_faz13_for_espn_fixture
from providers.espn_turkey_fixture_lookup import resolve_named_nba_fixture_for_turkey_date


async def persist_resolved_nba_prematch(
    *, adapter, ledger, core, observed_at_utc: int | None = None,
) -> dict:
    """Resolve ESPN identity and persist only a genuine pre-tipoff FAZ13 output.

    Returns the matched fixture and whether a new immutable row was inserted.
    Callers must ensure the adapter uses an authentic ESPN endpoint and that
    FAZ13 baseline provenance is independently validated.
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

    inserted = record_faz13_for_espn_fixture(
        ledger, core, fixture, resolved_home_team_id=home_id,
        resolved_away_team_id=away_id)
    return {"fixture": fixture, "inserted": inserted}
