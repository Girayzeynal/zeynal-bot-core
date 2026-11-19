"""No-network NBA team-scoped injury-report line extraction tests."""
import pytest
from hybrid_engine.official_club_nba_claims import nba_injury_report_candidates

DENVER_ARTICLE_TEXT="""Nuggets conclude road trip against Pelicans.
INJURY REPORT Denver:
DaRon Holmes II — OUT (G League Assignment)
Ryan Nembhard — OUT (G League Two-Way Assignment)
Julian Strawther — OUT (Left Knee Sprain)
Cam Whitmore — OUT (G League Two-Way Assignment)
New Orleans:
Yves Missi — PROBABLE (Left Knee Contusion)
TUNE-IN: Saturday, November 14.
"""


def test_official_denver_report_extracts_four_only_not_opponent():
    claims=nba_injury_report_candidates(
        DENVER_ARTICLE_TEXT,club_key="nba_denver_nuggets")
    assert [x["player_name_text"] for x in claims]==[
        "DaRon Holmes II","Ryan Nembhard","Julian Strawther","Cam Whitmore"]
    assert all(x["reported_status"]=="OUT" for x in claims)
    assert [x["reason_category"] for x in claims]==[
        "NON_INJURY_G_LEAGUE","NON_INJURY_G_LEAGUE",
        "INJURY_REASON_REPORTED","NON_INJURY_G_LEAGUE"]
    assert all(x["native_player_id"] is None and x["fixture_id"] is None for x in claims)
    assert all(x["model_input"] is False for x in claims)
    assert all(x["historical_prematch_eligibility"] is False for x in claims)


def test_questionable_is_not_treated_as_a_definite_out():
    txt="INJURY REPORT Denver: Cameron Johnson — DOUBTFUL (Right Ankle Sprain) Julian Strawther — OUT (Left Knee Sprain) TUNE-IN:"
    claims=nba_injury_report_candidates(txt,club_key="nba_denver_nuggets")
    assert [x["reported_status"] for x in claims]==["DOUBTFUL","OUT"]
    assert len(claims)==2


def test_opponent_only_section_and_unrelated_prose_never_extract():
    assert nba_injury_report_candidates(
        "INJURY REPORT New Orleans: Yves Missi — OUT (Left Knee Contusion)",
        club_key="nba_denver_nuggets")==[]
    assert nba_injury_report_candidates(
        "Julian Strawther — OUT (Left Knee Sprain)",
        club_key="nba_denver_nuggets")==[]


def test_team_scope_is_denver_only_until_other_parsers_verified():
    assert nba_injury_report_candidates(
        DENVER_ARTICLE_TEXT,club_key="nba_boston_celtics")==[]
    assert nba_injury_report_candidates(
        DENVER_ARTICLE_TEXT,club_key="eurocup_tofas")==[]


def test_unknown_phrase_not_promoted_to_definite_out():
    assert nba_injury_report_candidates(
        "INJURY REPORT Denver: Julian Strawther might miss next week.",
        club_key="nba_denver_nuggets")==[]


@pytest.mark.parametrize("bad", ["x"*8193,None,10])
def test_text_limit(bad):
    with pytest.raises(ValueError):
        nba_injury_report_candidates(bad,club_key="nba_denver_nuggets")
