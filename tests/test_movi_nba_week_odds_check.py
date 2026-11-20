"""Synthetic week odds probe tests; zero network calls."""
from hybrid_engine.movi_nba_week_odds_check import compare_week


def snap():
    return {"status":"OK","kind":"SAVED_SNAPSHOT_NOT_LIVE_DATA",
            "period_tsi":["2026-11-21","2026-11-27"],
            "games":[
              {"utc":"2026-11-21T00:00:00+00:00","date_tsi":"2026-11-21",
               "start_tsi":"21.11.2026 03:00","away":"Charlotte Hornets",
               "home":"Atlanta Hawks","away_code":"CHA","home_code":"ATL"},
              {"utc":"2026-11-24T00:00:00+00:00","date_tsi":"2026-11-24",
               "start_tsi":"24.11.2026 03:00","away":"Portland Trail Blazers",
               "home":"Philadelphia 76ers","away_code":"POR","home_code":"PHI"},
              {"utc":"2026-11-25T00:00:00+00:00","date_tsi":"2026-11-25",
               "start_tsi":"25.11.2026 03:00","away":"Detroit Pistons",
               "home":"Orlando Magic","away_code":"DET","home_code":"ORL"}]}


def test_matches_with_ten_minute_provider_clock_shift():
    board={"matches":[{"league":"NBA","away":"CHA Hornets","home":"ATL Hawks",
                      "kickoff_utc":"2026-11-21T00:10:00Z",
                      "quotes":[{"odds_dec":1.9,"suspended":False}]}]}
    x=compare_week(snap(),board)
    assert x["status"]=="OK"
    assert x["total"]==3
    assert x["counts"]["BOARD_WITH_PRICES_UNVERIFIED_FRESHNESS"]==1
    assert x["counts"]["NOT_IN_CURRENT_PROVIDER_BOARD"]==2
    assert x["matches"][0]["active_price_rows"]==1


def test_no_active_prices_not_marked_as_live():
    board={"matches":[{"league":"NBA","away":"Portland Trail Blazers",
                       "home":"Philadelphia 76ers","kickoff_utc":"2026-11-24T00:00:00Z",
                       "quotes":[{"odds_dec":1.7,"suspended":True}]}]}
    x=compare_week(snap(),board)
    assert x["counts"]["BOARD_NO_ACTIVE_PRICES"]==1


def test_bad_snapshot_rejected():
    assert compare_week({"games":[]},{"matches":[]})["status"]=="BAD_SCHEMA"


def test_unrelated_opponent_not_falsely_matched():
    board={"matches":[{"league":"NBA","away":"Charlotte Hornets",
                       "home":"Boston Celtics","kickoff_utc":"2026-11-21T00:00:00Z",
                       "quotes":[{"odds_dec":1.9}]}]}
    x=compare_week(snap(),board)
    assert x["counts"]["NOT_IN_CURRENT_PROVIDER_BOARD"]==3
