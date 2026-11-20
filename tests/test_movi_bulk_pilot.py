"""Synthetic-only tests: never call MoviOdds API or Telegram."""
from datetime import datetime, timedelta, timezone

from hybrid_engine.movi_bulk_pilot import inspect_board, league_id, utc_time

NOW = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)


def fixture(league, identity="11", quotes=None, **overrides):
    result = dict(
        id=identity, league=league, home="Team A", away="Team B",
        kickoff_utc=(NOW + timedelta(hours=3)).isoformat(),
        in_play=False,
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
    stale = fixture("NBA", "4", quotes=[
        dict(market_id="99", sel_id="9", odds_dec=1.95,
             ts=(NOW - timedelta(hours=2)).isoformat())])
    no_timestamp = fixture("NBA", "5", quotes=[
        dict(market_id="88", sel_id="8", odds_dec=1.95)])
    duplicate = fixture("NBA", "6", quotes=[
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
