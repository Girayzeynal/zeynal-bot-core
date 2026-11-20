"""Synthetic catalog tests: never contact MoviOdds or reveal any credential."""
from datetime import datetime, timedelta, timezone

from hybrid_engine.movi_catalog_pilot import inspect_catalog

NOW = datetime(2026, 11, 21, 1, 0, tzinfo=timezone.utc)


def make_fixture(league, fixture_id, hours=72, **kwargs):
    match = dict(id=fixture_id, sport="basketball", league=league,
                 kickoff_utc=(NOW + timedelta(hours=hours)).isoformat(),
                 in_play=False)
    match.update(kwargs)
    return match


def test_three_competitions_next_week_in_one_catalog():
    board = {"fixtures": [
        make_fixture("NBA", "nba", hours=3),
        make_fixture("EuroLeague", "el", hours=100),
        make_fixture("BKT EuroCup", "ec", hours=144),
    ]}
    report = inspect_catalog(board, NOW)
    assert report["status"] == "OK"
    assert all(report["leagues"][n]["next_7_days"] == 1
               for n in ("NBA", "EUROLEAGUE", "EUROCUP"))
    # UTC +3 and local date/day are not guessed from the server date.
    assert report["leagues"]["NBA"]["next_tsi"] == ["2026-11-21 07:00 +0300"]


def test_36_hour_odds_gap_is_not_a_seven_day_catalog_gap():
    board = {"fixtures": [make_fixture("EuroLeague", "future", hours=96)]}
    result = inspect_catalog(board, NOW)
    assert result["leagues"]["EUROLEAGUE"]["next_7_days"] == 1


def test_fiba_europe_cup_not_mislabelled():
    report = inspect_catalog({"fixtures": [
        make_fixture("FIBA Europe Cup", "fiba"),
        make_fixture("EuroCup Women", "w"),
    ]}, NOW)
    assert report["leagues"]["EUROCUP"]["next_7_days"] == 0
    assert "FIBA Europe Cup" in report["unclassified_europe"]


def test_future_horizon_and_deduplication():
    board = {"fixtures": [
        make_fixture("NBA", 7, hours=200),
        make_fixture("NBA", 7, hours=200),
        make_fixture("NBA", 8, hours=-1),
        make_fixture("NBA", 9, hours=20, in_play=True),
    ]}
    result = inspect_catalog(board, NOW)["leagues"]["NBA"]
    assert result["listed_total"] == 3
    assert result["next_7_days"] == 0
    assert result["after_7_days"] == 1


def test_unverified_time_is_never_converted_to_fake_match():
    match = make_fixture("BKT EuroCup", "a", kickoff_utc="2026-11-25")
    result = inspect_catalog({"fixtures": [match]}, NOW)["leagues"]["EUROCUP"]
    assert result["unverified_kickoff"] == 1
    assert result["next_7_days"] == 0


def test_bad_schema_no_network():
    assert inspect_catalog({"matches": []}, NOW)["status"] == "BAD_SCHEMA"
    assert inspect_catalog({"fixtures": [], "warming": True}, NOW)["status"] == "WARMING"


def test_adaptive_plan_limits_total_daily_api_usage_to_six():
    board = {"fixtures": [
        make_fixture("NBA", "a", hours=16),
        make_fixture("NBA", "b", hours=18),
        make_fixture("EuroLeague", "c", hours=21),
        make_fixture("EuroLeague", "d", hours=24),
        make_fixture("BKT EuroCup", "e", hours=27),
        make_fixture("BKT EuroCup", "f", hours=30),
    ]}
    result = inspect_catalog(board, NOW)
    assert result["schedule_status"] == "PROPOSAL_ONLY_NOT_INSTALLED"
    assert result["dry_run_schedule"]
    assert all(day["max_total_calls_including_reserve"] <= 6
               for day in result["dry_run_schedule"])
    assert all(day["catalog_calls_per_day"] == 1
               for day in result["dry_run_schedule"])


def test_quiet_week_schedules_zero_odds_pulls():
    report = inspect_catalog({"fixtures": []}, NOW)
    assert report["dry_run_schedule"] == []


def test_early_morning_tsi_uses_previous_local_day_when_needed():
    # 2026-11-22 00:10 TSİ => refresh at 2026-11-21 23:50 TSİ
    kickoff = datetime(2026, 11, 21, 21, 10, tzinfo=timezone.utc)
    board = {"fixtures": [make_fixture("NBA", "early",
        kickoff_utc=kickoff.isoformat())]}
    report = inspect_catalog(board, NOW)
    plans = report["dry_run_schedule"]
    assert plans[0]["tsi_day"] == "2026-11-21"
    assert "2026-11-21 23:50" in plans[0]["regular_odds_slots_tsi"]


def test_does_not_schedule_after_match_would_start():
    board = {"fixtures": [make_fixture("NBA", "soon",
        kickoff_utc=(NOW + timedelta(minutes=9)).isoformat())]}
    assert inspect_catalog(board, NOW)["dry_run_schedule"] == []
