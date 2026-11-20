"""Synthetic NBA fixture comparison tests; no live ESPN or MoviOdds requests."""
from hybrid_engine.movi_nba_espn_week import compare_cached, code_of, parse_espn_board
from datetime import date


def event(identity, utc, away="CHA", home="ATL"):
    return {"id": identity, "date": utc, "competitions": [{"competitors": [
        {"homeAway": "away", "team": {"abbreviation": away}},
        {"homeAway": "home", "team": {"abbreviation": home}}
    ]}]}


def cached_week():
    return {
        "league": "NBA", "start_day_tsi": "2026-11-21",
        "end_day_tsi": "2026-11-27",
        "days": {"2026-11-21": [
            {"tsi": "21.11.2026 03:10", "utc": "2026-11-21T00:10:00+00:00",
             "away": "CHA Hornets", "home": "ATL Hawks", "fixture_id": "m1"}
        ]}
    }


def test_safe_team_identity_aliases():
    assert code_of("CHA Hornets") == "CHA"
    assert code_of("ATL Hawks") == "ATL"
    assert code_of("NO Pelicans") == "NOP"
    assert code_of("LA Lakers") == "LAL"
    assert code_of("UT Jazz") == "UTA"
    assert code_of("not a team") is None


def test_detects_ten_minute_time_discrepancy():
    doc = {"events": [event("e1", "2026-11-21T00:00:00Z")]}
    result = compare_cached(cached_week(), [doc])
    assert result["status"] == "OK"
    assert result["official_fixtures"] == 1
    assert result["matched"] == 1
    assert result["time_differences"][0]["difference_minutes"] == 10
    assert result["day_summary"]["2026-11-21"]["moviodds_matched"] == 1


def test_future_official_fixture_missing_in_provider_does_not_mean_cancelled():
    doc = {"events": [
        event("e1", "2026-11-21T00:00:00Z"),
        event("e2", "2026-11-21T18:00:00Z", "MIL", "PHI"),
    ]}
    result = compare_cached(cached_week(), [doc])
    assert result["official_fixtures"] == 2
    assert result["day_summary"]["2026-11-21"]["not_in_moviodds_catalog"] == 1
    assert result["missing_from_provider_examples"]["2026-11-21"][0]["home"] == "Philadelphia 76ers"


def test_espn_tsi_day_filter_and_invalid():
    board = {"events": [
        event("prior", "2026-11-20T14:00:00Z"),
        event("inside", "2026-11-21T00:00:00Z"),
        event("after", "2026-11-28T00:00:00Z")
    ]}
    observed = parse_espn_board(board, date(2026, 11, 21), date(2026, 11, 27))
    assert sorted(observed) == ["inside"]


def test_invalid_provider_week_rejected():
    assert compare_cached({"league": "NBA", "days": {}}, [])["status"] == "INVALID_MOVIODDS_CACHE"
    cache = cached_week()
    cache["end_day_tsi"] = "2026-11-28"
    assert compare_cached(cache, [])["status"] == "INVALID_WEEK_RANGE"


def test_identity_mismatch_is_not_marked_as_matching_odds():
    doc = {"events": [event("e1", "2026-11-21T00:00:00Z", "IND", "ATL")]}
    result = compare_cached(cached_week(), [doc])
    assert result["official_fixtures"] == 1
    assert result["matched"] == 0
