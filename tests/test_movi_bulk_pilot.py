"""Synthetic-only tests: never call MoviOdds API or Telegram."""
from datetime import datetime, timedelta, timezone

from hybrid_engine.movi_bulk_pilot import inspect_board, league_id, utc_time

NOW = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)


def fixture(league, identity="11", quotes=None, **overrides):
    result = dict(
        id=identity, league=league, home="Team A", away="Team B",
        kickoff_utc=(NOW + timedelta(hours=3)).isoformat(),
        in_play=False,
        group_status={"1453": {"polled_at": NOW.isoformat()}},
        quotes=[dict(market_id="55", sel_id="xx", odds_dec=1.95,
                     group_id="1453", group_name="Game", ts=NOW.isoformat())]
        if quotes is None else quotes,
    )
    result.update(overrides)
    return result


def test_exact_league_classification():
    assert league_id("NBA") == "NBA"
    assert league_id("Turkish Airlines EuroLeague") == "EUROLEAGUE"
    assert league_id("BKT EuroCup") == "EUROCUP"
    assert league_id("FIBA Europe Cup") is None


def test_invalid_schema_and_naive_timestamp():
    assert inspect_board({"fixtures": []}, NOW)["status"] == "BAD_SCHEMA"
    assert utc_time("2026-11-21") is None


def test_three_leagues_in_one_board():
    report = inspect_board({"matches": [
        fixture("NBA"), fixture("EuroLeague"), fixture("BKT EuroCup")
    ]}, NOW)
    assert set(report["covered"]) == {"NBA", "EUROLEAGUE", "EUROCUP"}
    assert all(report["leagues"][lg]["fresh_quotes"] == 1 for lg in report["covered"])


def test_stale_missing_clock_live_and_duplicates():
    live = fixture("NBA", "3", in_play=True)
    stale = fixture("NBA", "4", group_status={"99": {"polled_at": (NOW - timedelta(hours=2)).isoformat()}}, quotes=[
        dict(market_id="99", sel_id="9", odds_dec=1.95,
             ts=(NOW - timedelta(hours=2)).isoformat())])
    no_timestamp = fixture("NBA", "5", quotes=[
        dict(market_id="88", sel_id="8", odds_dec=1.95)])
    duplicate = fixture("NBA", "6", group_status={"88": {"polled_at": NOW.isoformat()}}, quotes=[
        dict(market_id="88", sel_id="8", odds_dec=1.95, ts=NOW.isoformat())] * 2)
    summary = inspect_board({"matches": [
        live, stale, no_timestamp, duplicate, duplicate
    ]}, NOW)["leagues"]["NBA"]
    assert summary["fixtures"] == 3
    assert summary["fresh_quotes"] == 1
    assert summary["stale_quotes"] == 1
    assert summary["unknown_time_quotes"] == 1


def test_next_day_kickoff_and_already_started():
    tomorrow = fixture("EuroCup", kickoff_utc=(NOW + timedelta(hours=20)).isoformat())
    assert inspect_board({"matches": [tomorrow]}, NOW)["leagues"]["EUROCUP"]["fixtures"] == 1
    tomorrow["kickoff_utc"] = (NOW - timedelta(minutes=1)).isoformat()
    assert inspect_board({"matches": [tomorrow]}, NOW)["leagues"]["EUROCUP"]["fixtures"] == 0


def test_official_basketball_sample_without_market_id():
    quote = dict(group_id="1453", group_name="Game", sel_id="1888364452",
                 line="Line", side="BOS Celtics", label="+1.5",
                 odds_dec=1.90909, ts=NOW.isoformat())
    report = inspect_board({"matches": [fixture("NBA", quotes=[quote])]}, NOW)
    assert report["leagues"]["NBA"]["fresh_quotes"] == 1


def test_old_price_change_time_does_not_imply_stale_market():
    match = fixture("NBA", quotes=[dict(group_id="1453", sel_id="xx",
        odds_dec=1.95, ts=(NOW - timedelta(days=4)).isoformat())])
    report = inspect_board({"matches": [match], "server_time": NOW.isoformat()}, NOW)
    assert report["leagues"]["NBA"]["fresh_quotes"] == 1
    assert report["leagues"]["NBA"]["stale_quotes"] == 0


def test_fixture_only_polled_time_not_per_market_evidence():
    match = fixture("NBA", group_status={}, polled_at=NOW.isoformat())
    report = inspect_board({"matches": [match]}, NOW)
    assert report["leagues"]["NBA"]["fresh_quotes"] == 0
    assert report["leagues"]["NBA"]["fixture_only_quotes"] == 1


def test_stale_explicit_group_flag_rejects_recent_clock():
    match = fixture("EUROLEAGUE", group_status={"1453": {"polled_at": NOW.isoformat(), "stale": True}})
    report = inspect_board({"matches": [match]}, NOW)
    assert report["leagues"]["EUROLEAGUE"]["stale_quotes"] == 1
    assert report["leagues"]["EUROLEAGUE"]["fresh_quotes"] == 0


def test_league_catalog_does_not_claim_market_coverage():
    long_horizon = fixture("EuroLeague", kickoff_utc=(NOW + timedelta(days=6)).isoformat())
    report = inspect_board({"matches": [long_horizon]}, NOW)
    assert report["leagues"]["EUROLEAGUE"]["listed_all_dates"] == 1
    assert report["leagues"]["EUROLEAGUE"]["fixtures"] == 0
    assert "EUROLEAGUE" not in report["covered"]


def test_http_400_error_diagnostic_does_not_echo_secret():
    import io
    from urllib.error import HTTPError
    from hybrid_engine.movi_bulk_pilot import classify_http_error
    secret = "secret-credential-that-must-not-appear"
    error = HTTPError("https://moviodds.com/odds?sport=basketball", 400,
                      "Bad Request", {}, io.BytesIO(
                          ('{"error":"unknown sport key: '+secret+'"}').encode()))
    assert classify_http_error(error) == "UNKNOWN_SPORT_FILTER"


def test_http_400_unrecognized_error_does_not_show_body():
    import io
    from urllib.error import HTTPError
    from hybrid_engine.movi_bulk_pilot import classify_http_error
    error = HTTPError("https://moviodds.com/odds?sport=basketball", 400,
                      "Bad Request", {}, io.BytesIO(
                          b'{"error":"secret provider details"}'))
    assert classify_http_error(error) == "BAD_REQUEST_UNCLASSIFIED"


def test_http_401_and_429_categories():
    from urllib.error import HTTPError
    from hybrid_engine.movi_bulk_pilot import classify_http_error
    assert classify_http_error(HTTPError("", 401, "", {}, None)) == "KEY_MISSING_OR_INVALID"
    assert classify_http_error(HTTPError("", 429, "", {}, None)) == "RATE_LIMIT"



def test_missing_per_market_status_is_counted_without_claiming_fresh():
    match = fixture("NBA", group_status={}, polled_at=None)
    report = inspect_board({"matches": [match]}, NOW)["leagues"]["NBA"]
    assert report["matches_with_market_status"] == 0
    assert report["matches_with_fixture_poll"] == 0
    assert report["quotes_missing_group_status"] == 1
    assert report["fresh_quotes"] == 0


def test_group_status_coverage_counters():
    match = fixture("NBA")
    report = inspect_board({"matches": [match]}, NOW)["leagues"]["NBA"]
    assert report["matches_with_market_status"] == 1
    assert report["market_status_groups"] == 1
    assert report["quotes_missing_group_status"] == 0
