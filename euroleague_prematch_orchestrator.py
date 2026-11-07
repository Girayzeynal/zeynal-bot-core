"""Explicit EuroLeague research persistence with original inputs and observed fixtures."""
from datetime import datetime
import math
import time
from zoneinfo import ZoneInfo

from baseline_numeric_reconciliation import reconcile_team_average
from prediction_inputs import validate_prediction_inputs
from prematch_ledger_bridge import record_verified_prematch_projection
from providers.euroleague_fixture_evidence import capture_fixture_evidence
from providers.euroleague_live import BASE, EuroleagueLiveAdapter


async def persist_resolved_euroleague_prematch(*, adapter, ledger, core, year):
    """Require fresh provider observation before inserting; no Telegram/default wiring."""
    if not isinstance(adapter, EuroleagueLiveAdapter):
        raise TypeError("EuroleagueLiveAdapter required")
    ctx, meta = getattr(core, "ctx", None), getattr(core, "meta", None)
    if ctx is None or getattr(ctx, "league", None) != "EUROLEAGUE":
        raise ValueError("Only EuroLeague is enabled; EuroCup has no calibrated profile")
    if (not isinstance(meta, dict) or meta.get("data_quality") != "VERIFIED_BASELINE"
            or any(not isinstance(getattr(ctx, key, None), str) or not getattr(ctx, key).strip()
                   for key in ("date", "home", "away"))):
        raise ValueError("Incomplete EuroLeague core context/provenance")
    predicted = meta.get("generated_at")
    if type(predicted) is not int or not 0 < predicted <= int(time.time()):
        raise ValueError("Original EuroLeague prediction timestamp is missing or future-dated")
    snapshot = meta.get("input_snapshot")
    frozen = validate_prediction_inputs(snapshot, league="EUROLEAGUE", prediction_utc=predicted,
        expected_home=meta.get("expected_home"), expected_away=meta.get("expected_away"))
    if snapshot["payload"]["context"] != {key: getattr(ctx, key) for key in ("date", "home", "away")}:
        raise ValueError("EuroLeague original input context differs from core")
    for side in ("home", "away"):
        key = getattr(ctx, side)
        rows = frozen.get_series("EUROLEAGUE", key, 1000)
        count = meta.get(f"{side}_baseline_games")
        if (meta.get(f"{side}_sources") != ["TEAM_BASELINE_STORE"]
                or meta.get(f"{side}_baseline_key") != key
                or type(count) is not int or count < 6 or count != len(rows)):
            raise ValueError("EuroLeague baseline source/key/sample mismatch")
        reconcile_team_average(getattr(core, f"{side}_avg", None), rows,
            prediction_utc=predicted, league="EUROLEAGUE", team=key)
    total = meta.get("expected_total")
    if (type(total) not in (int, float) or not math.isfinite(total)
            or abs(total-meta["expected_home"]-meta["expected_away"]) > 0.02):
        raise ValueError("EuroLeague total differs from explicit team projections")

    # Deliberately bypass the short baseline cache: saving a prediction requires
    # a fresh schedule read and one matching individual fixture response.
    catalog = await adapter.fetch_catalog("EUROLEAGUE", year)
    if catalog["invalid_records"] or catalog["conflicting_fixture_ids"]:
        raise ValueError("EuroLeague fixture catalog is incomplete or ambiguous")
    matches = [game for game in catalog["games"] if game["status"] == "UNPLAYED" and game["phase"] == "RS"
        and game["home_team_id"] == ctx.home and game["away_team_id"] == ctx.away
        and datetime.fromtimestamp(game["start_ts_utc"], ZoneInfo("Europe/Istanbul")).date().isoformat() == ctx.date]
    if len(matches) != 1:
        raise ValueError("Unique matching EuroLeague fixture not found")
    fixture = matches[0]
    if int(time.time()) >= fixture["start_ts_utc"]:
        raise ValueError("EuroLeague fixture already started")
    url = f"{BASE}/E/seasons/{fixture['season_code']}/games/{fixture['game_code']}"
    raw = await adapter._get_json(url)
    evidence = capture_fixture_evidence(raw, year=year, observed_at_utc=int(time.time()))
    if evidence["payload"]["fixture"] != fixture:
        raise ValueError("EuroLeague catalog and detail fixture disagree")
    inserted = record_verified_prematch_projection(ledger, league="EUROLEAGUE",
        fixture_id=fixture["provider_fixture_id"], provider="EUROLEAGUE_LIVE",
        provider_fixture_id=fixture["provider_fixture_id"], tipoff_utc=fixture["start_ts_utc"],
        prediction_utc=predicted, expected_home=meta["expected_home"], expected_away=meta["expected_away"],
        input_snapshot=snapshot, fixture_evidence=evidence)
    original = ledger.load_fixture_observation("EUROLEAGUE", fixture["provider_fixture_id"])
    return dict(fixture=fixture, inserted=inserted, fixture_observation_sha256=original["sha256"])
