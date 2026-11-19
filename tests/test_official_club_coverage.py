"""The 2026/27 82-team club inventory is NOT 82 connected news sites."""
import copy
import json
from pathlib import Path

import pytest

from hybrid_engine import official_club_coverage as cov


def test_all_82_current_clubs_are_named_but_only_six_pilot_sources_observed():
    report=cov.summary()
    assert report["members_total"]==82
    assert report["league_totals"]=={"NBA":30,"EUROLEAGUE":20,"EUROCUP":32}
    assert report["league_observed"]=={"NBA":2,"EUROLEAGUE":2,"EUROCUP":2}
    assert report["league_source_pending"]=={"NBA":28,"EUROLEAGUE":18,"EUROCUP":30}
    assert report["source_pages_not_yet_verified"]==76
    assert report["all_clubs_official_news_connected"] is False
    assert report["roster_identity_verified"] is False
    assert report["injury_status_comprehensively_verified"] is False
    assert report["requests"]==0
    assert report["model_input"] is False
    assert report["production_changed"] is False


def test_2026_27_revision_and_distinct_rome_clubs_are_preserved():
    data=cov.load_coverage()
    names={(x["league"],x["team_name"]) for x in data["teams"]}
    assert ("EUROLEAGUE","Besiktas Istanbul") in names
    assert ("EUROCUP","Bosna BH Telecom Sarajevo") in names
    assert ("EUROCUP","Maxima Roma") in names
    assert ("EUROCUP","Roma Basketball") in names
    assert ("EUROCUP","AS Monaco") not in names
    assert ("EUROLEAGUE","AS Monaco") not in names
    assert len({x["club_key"] for x in data["teams"]})==82


def _tamper(tmp_path,change):
    d=copy.deepcopy(cov.load_coverage())
    change(d)
    f=tmp_path/"coverage.json"
    f.write_text(json.dumps(d),encoding="utf-8")
    return f


def test_unverified_teams_cannot_acquire_guessed_news_url(tmp_path):
    path=_tamper(tmp_path,lambda d:next(
        x for x in d["teams"] if x["club_key"]=="nba_atlanta_hawks"
    ).update(official_news_url="https://www.nba.com/hawks/news"))
    with pytest.raises(ValueError,match="UNVERIFIED_CLUB_MUST_NOT_BE_CONNECTED"):
        cov.load_coverage(path)


def test_pilot_site_must_match_original_allowlist_not_something_else(tmp_path):
    path=_tamper(tmp_path,lambda d:next(
        x for x in d["teams"] if x["club_key"]=="nba_denver_nuggets"
    ).update(official_news_url="https://example.org/team/news"))
    with pytest.raises(ValueError,match="PILOT_SITE_IDENTITY_MISMATCH"):
        cov.load_coverage(path)


def test_cannot_fake_complete_by_missing_club_or_moving_besiktas_back(tmp_path):
    path=_tamper(tmp_path,lambda d:d["teams"].pop())
    with pytest.raises(ValueError,match="INVENTORY_INVALID"):
        cov.load_coverage(path)
    def change(d):
        x=next(x for x in d["teams"] if x["team_name"]=="Besiktas Istanbul")
        x["team_name"]="Old Season Club"
    with pytest.raises(ValueError,match="MEMBERSHIP_REVISION_MISSING"):
        cov.load_coverage(_tamper(tmp_path,change))


def test_summary_cli_is_zero_network(capsys):
    assert cov.run(["--summary"])==0
    item=json.loads(capsys.readouterr().out.strip())
    assert item["members_total"]==82
    assert item["pilot_source_pages_observed"]==6
    assert item["requests"]==0



def test_official_nba_injury_hub_does_not_mean_30_team_status_feed_connected():
    r=cov.summary()
    assert r["nba_official_injury_report_hub_url"]==(
        "https://official.nba.com/nba-injury-report-2026-27-season/")
    assert r["nba_injury_hub_data_ingested"] is False
    assert r["nba_injury_hub_parsed_player_count"]==0
    assert r["all_clubs_official_news_connected"] is False
    assert r["injury_status_comprehensively_verified"] is False


def test_cannot_promote_unread_nba_pdf_injury_hub_to_model_feed(tmp_path):
    def tamper(d):
        d["additional_league_sources"]["NBA"][0]["model_input"]=True
    with pytest.raises(ValueError,match="LEAGUE_INJURY_HUB_NOT_VERIFIED"):
        cov.load_coverage(_tamper(tmp_path,tamper))
