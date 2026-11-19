"""One fixture, two real club news entry sources; no fabricated medical status."""
import pytest
from hybrid_engine.official_club_fixture_news import (
    read_fixture_club_news,render_fixture_news)

BASE=dict(league="EUROLEAGUE",fixture_start_utc=1800000000,
    home=dict(official_name="Armani Olimpia Milan"),
    away=dict(official_name="Fenerbahce Tarfin Istanbul"))
NOW=1795000000

def _ok(url,*,limit,expected_mime):
    if url.endswith("/robots.txt"):
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    body=b"User-agent: *\nAllow: /\n")
    return dict(status="DOCUMENT_RECEIVED",http_status=200,
        observed_at_utc=NOW-20,
        body=("<html><title>Official news</title>"
              '<a href="/en/coach-pre-match/">Coach preview ahead of the game</a>'
              "</html>").encode())

def test_milan_fenerbahce_both_clubs_fetched_with_pinned_sites():
    calls=[]
    def fetch(url,*,limit,expected_mime):
        calls.append(url)
        return _ok(url,limit=limit,expected_mime=expected_mime)
    r=read_fixture_club_news(BASE,requester=fetch,clock=lambda:NOW)
    assert r["status"]=="FIXTURE_OFFICIAL_CLUB_NEWS_INDEX_REVIEW_V1"
    assert len(r["rows"])==2
    assert [x["club_key"] for x in r["rows"]]==[
        "euroleague_ea7_emporio_armani_milan",
        "euroleague_fenerbahce_istanbul"]
    assert all(x["status"]=="OFFICIAL_NEWS_INDEX_OBSERVED_ONLY"
               for x in r["rows"])
    assert r["requests"]==4
    assert all(url.startswith("https://") for url in calls)
    assert r["verified_player_count"]==0
    assert r["model_input"] is False
    assert r["injury_verified"] is False
    assert r["archives_modified"] is False
    txt=render_fixture_news(r)
    assert "Armani Olimpia Milan" in txt
    assert "Fenerbahce Tarfin Istanbul" in txt
    assert "OUT" in txt
    assert "Resmî haber" in txt

def test_zalgiris_panathinaikos_fetch_two_correct_official_hosts():
    ctx=dict(BASE,home=dict(official_name="Zalgiris Kaunas"),
             away=dict(official_name="Panathinaikos AKTOR Athens"))
    seen=[]
    def fetch(url,*,limit,expected_mime):
        seen.append(url)
        return _ok(url,limit=limit,expected_mime=expected_mime)
    r=read_fixture_club_news(ctx,requester=fetch,clock=lambda:NOW)
    assert {x["club_key"] for x in r["rows"]}=={
        "euroleague_zalgiris","euroleague_panathinaikos_athens"}
    assert set(url.split("/")[2] for url in seen)=={"zalgiris.lt","www.paobc.gr"}
    assert r["requests"]==4

def test_denied_robots_never_fetches_official_news():
    seen=[]
    def deny(url,*,limit,expected_mime):
        seen.append(url)
        return dict(status="SOURCE_ACCESS_REFUSED",http_status=403)
    r=read_fixture_club_news(BASE,requester=deny,clock=lambda:NOW)
    assert r["requests"]==2
    assert len(seen)==2
    assert all(x.endswith("/robots.txt") for x in seen)
    assert all(x["status"]=="ROBOTS_NOT_AVAILABLE_NEWS_NOT_FETCHED"
               for x in r["rows"])
    assert r["injury_verified"] is False

def test_after_tipoff_does_not_try_website_and_retroactively_backfill():
    ctx=dict(BASE,fixture_start_utc=NOW-1)
    r=read_fixture_club_news(ctx,requester=lambda *a,**k:1/0,
                             clock=lambda:NOW)
    assert r["status"]=="POST_TIPOFF_NO_NEW_SOURCE_POLL"
    assert r["requests"]==0

def test_ambiguous_or_unknown_name_does_not_guess_club():
    ctx=dict(BASE,home=dict(official_name="Fenerbahce"),away=dict(
        official_name="Olimpia"))
    r=read_fixture_club_news(ctx,requester=lambda *a,**k:1/0,
                             clock=lambda:NOW)
    assert r["requests"]==0
    assert all(x["status"]=="CLUB_OFFICIAL_IDENTITY_NOT_EXACTLY_RESOLVED"
               for x in r["rows"])

def test_unsupported_league_refuses_implicit_team_identity():
    with pytest.raises(ValueError):
        read_fixture_club_news(dict(BASE,league="UNKNOWN"),clock=lambda:NOW)
