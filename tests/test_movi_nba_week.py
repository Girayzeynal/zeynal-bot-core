"""NBA-only catalog tests; synthetic input, no provider calls."""
from datetime import datetime, timedelta, timezone

from hybrid_engine.movi_nba_week import nba_week_catalog

NOW = datetime(2026, 11, 20, 22, 15, tzinfo=timezone.utc)  # Nov 21 01:15 TSİ


def game(identity, hours=6, league="NBA", **kwargs):
    value = dict(
        id=identity, sport="basketball", league=league,
        home="Boston Celtics", away="New York Knicks",
        kickoff_utc=(NOW + timedelta(hours=hours)).isoformat(),
        in_play=False,
    )
    value.update(kwargs)
    return value


def test_current_seven_local_dates_and_matchups():
    results = nba_week_catalog({"fixtures": [game("a")]}, NOW)
    assert results["start_day_tsi"] == "2026-11-21"
    assert results["end_day_tsi"] == "2026-11-27"
    assert results["upcoming_this_week"] == 1
    one = results["days"]["2026-11-21"][0]
    assert one["away"] == "New York Knicks"
    assert one["home"] == "Boston Celtics"
    assert one["tsi"] == "21.11.2026 07:15"
    assert results["network_calls"] == 0


def test_end_inclusive_and_next_day_exclusive():
    end_utc = datetime(2026, 11, 27, 20, 30, tzinfo=timezone.utc)
    next_day = datetime(2026, 11, 27, 21, 10, tzinfo=timezone.utc)
    report = nba_week_catalog({"fixtures": [
        game("in", kickoff_utc=end_utc.isoformat()),
        game("out", kickoff_utc=next_day.isoformat()),
    ]}, NOW)
    assert report["upcoming_this_week"] == 1
    assert report["days"]["2026-11-27"][0]["fixture_id"] == "in"


def test_duplicate_and_pre_started_filtered():
    result = nba_week_catalog({"fixtures": [
        game("a"), game("a"),
        game("b", hours=-1), game("c", in_play=True),
        game("d", kickoff_utc="2026-11-21"),
        game("e", league="FIBA Europe Cup"),
    ]}, NOW)
    assert result["total_nba_catalog_entries"] == 4
    assert result["upcoming_this_week"] == 1


def test_no_games_no_unsupported_league_claim():
    report = nba_week_catalog({"fixtures": []}, NOW)
    assert report["status"] == "OK"
    assert report["upcoming_this_week"] == 0
    assert "not yet published" in report["note"]


def test_invalid_schema_and_unknown_nba_label():
    assert nba_week_catalog({"matches": []}, NOW)["status"] == "BAD_SCHEMA"
    report = nba_week_catalog({"fixtures": [game("a", league="NBA League New")]}, NOW)
    assert report["upcoming_this_week"] == 0
    assert report["unclassified_nba_names"] == ["NBA League New"]
