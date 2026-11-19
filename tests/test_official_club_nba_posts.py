"""Offline NBA native permalink -> index -> explicit article probe contracts."""
from datetime import datetime, timezone
import json
import pytest

from hybrid_engine.official_club_nba_posts import discover_nba_official_posts
from hybrid_engine.official_club_sources import (
    collect_article_candidates, probe, registry
)
from hybrid_engine.official_club_article_probe import probe_article


def club():
    return next(x for x in registry() if x["club_key"]=="nba_denver_nuggets")


def stamp(iso):
    return int(datetime.fromisoformat(iso.replace("Z","+00:00")).timestamp()*1000)


NEW="https://www.nba.com/nuggets/news/nuggets-prepare-for-a-game-in-november"
OLD="https://www.nba.com/nuggets/news/old-match-from-spring"


def index(posts):
    payload={"props":{"pageProps":{"posts":posts}}}
    return (b'<html><script id="__NEXT_DATA__" type="application/json">'+
            json.dumps(payload,ensure_ascii=False).encode("utf-8")+
            b'</script></html>')


def valid_posts():
    return [
        dict(id=12,slug="old-match-from-spring",name="Old playoff recap",
             status="publish",permalink=OLD,
             date="2026-04-27T01:52:45Z",
             timestamp=stamp("2026-04-27T01:52:45Z")),
        dict(id=16,slug="nuggets-prepare-for-a-game-in-november",
             name="Denver November official pregame news",
             status="publish",permalink=NEW,date="2026-11-18T22:10:00Z",
             timestamp=stamp("2026-11-18T22:10:00Z")),
        dict(id=18,slug="unpublished-pending-preview",name="Draft",
             status="draft",
             permalink="https://www.nba.com/nuggets/news/unpublished-pending-preview"),
        dict(id=20,slug="other-team-story",name="Rival",
             status="publish",
             permalink="https://www.nba.com/celtics/news/other-team-story"),
        dict(id=22,slug="wrong-host-story",name="Forged host",
             status="publish",permalink="https://evil.test/nuggets/news/wrong-host-story"),
        dict(id=23,slug="query-string-story",name="Query",
             status="publish",
             permalink="https://www.nba.com/nuggets/news/query-string-story?tracking=1")
    ]


def test_realistic_published_permalink_objects_discovered_without_guesswork():
    html=index(valid_posts())
    matches=discover_nba_official_posts(
        html,club(),observed_at_utc=stamp("2026-11-19T05:00:00Z")//1000)
    assert [r["url"] for r in matches]==[NEW,OLD]
    assert [r["source_post_id"] for r in matches]==["16","12"]
    assert matches[0]["source_clock_status"]=="LISTING_DATE_TIMESTAMP_AGREE_UNVERIFIED"
    assert matches[0]["source_raw_date"]=="2026-11-18T22:10:00Z"
    assert matches[0]["published_utc"] is None
    assert matches[0]["player_status_verified"] is False
    assert matches[0]["fixture_id"] is None
    assert matches[0]["model_input"] is False


def test_mixed_html_and_embedded_sources_are_deduplicated():
    links=b'<a href="/nuggets/news/nuggets-prepare-for-a-game-in-november">Preview</a>'
    body=links+index(valid_posts())
    results=collect_article_candidates(body,club())
    assert len(results)==2
    assert results[0]["url"]==NEW
    assert results[0]["source_post_id"]=="16"


def test_robots_news_index_plus_embedded_posts_only_two_requests():
    calls=[]
    def requester(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"User-agent: *\nDisallow: /private")
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    observed_at_utc=stamp("2026-11-19T05:00:00Z")//1000,
                    body=index(valid_posts()))
    result=probe(club(),requester=requester)
    assert len(calls)==2
    assert result["article_links"][0]["url"]==NEW
    assert result["official_embedded_candidate_count"]==2
    assert len(result["article_links"])==2
    assert result["model_input"] is False
    assert result["forecast_changed"] is False
    assert result["production_changed"] is False


def test_opt_in_article_from_native_post_is_fetched_after_robots_and_index():
    calls=[]
    def requester(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"User-agent: *\nDisallow: /private")
        if url.endswith("/news"):
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        observed_at_utc=stamp("2026-11-19T05:00:00Z")//1000,
                        body=index(valid_posts()))
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    observed_at_utc=stamp("2026-11-19T05:00:00Z")//1000,
                    body=b'<h1>Denver official pregame news</h1><p>Lineup has not been verified</p>')
    result=probe_article(club(),NEW,requester=requester)
    assert calls==[
        "https://www.nba.com/robots.txt",
        "https://www.nba.com/nuggets/news",NEW]
    assert result["status"]=="OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED"
    assert result["index_candidate_origin"]=="OFFICIAL_NBA_EMBEDDED_PUBLISHED_POST"
    assert result["index_raw_date"]=="2026-11-18T22:10:00Z"
    assert result["index_clock_status"]=="LISTING_DATE_TIMESTAMP_AGREE_UNVERIFIED"
    assert result["index_native_post_id"]=="16"
    assert result["published_utc"] is None
    assert result["fixture_id"] is None
    assert result["player_status_verified"] is False
    assert result["model_input"] is False
    assert result["forecast_changed"] is False


def test_tampered_link_not_present_in_current_index_is_rejected_without_download():
    calls=[]
    def requester(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"User-agent: *\nDisallow: /private")
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    observed_at_utc=stamp("2026-11-19T05:00:00Z")//1000,
                    body=index(valid_posts()))
    result=probe_article(
        club(),"https://www.nba.com/nuggets/news/not-in-live-index",
        requester=requester)
    assert result["status"]=="ARTICLE_NOT_VERIFIED_IN_CURRENT_INDEX"
    assert len(calls)==2


def test_mismatched_listing_post_clocks_do_not_masquer_as_published_at():
    posts=[dict(id=55,slug="new-clock-conflict",status="publish",
                permalink="https://www.nba.com/nuggets/news/new-clock-conflict",
                date="2026-11-18T22:10:00Z",
                timestamp=stamp("2026-10-18T22:10:00Z"))]
    results=discover_nba_official_posts(index(posts),club())
    assert len(results)==1
    assert results[0]["source_clock_status"]=="LISTING_DATE_TIMESTAMP_CONFLICT"
    assert results[0]["published_utc"] is None
    assert results[0]["model_input"] is False


def test_html_budget_and_non_nba_team_scope():
    with pytest.raises(ValueError):
        discover_nba_official_posts(b"x"*(512*1024+1),club())
    other=next(x for x in registry() if x["club_key"]=="eurocup_tofas")
    with pytest.raises(ValueError):
        discover_nba_official_posts(index(valid_posts()),other)


def test_landing_category_not_accepted_as_article():
    boston=next(x for x in registry() if x["club_key"]=="nba_boston_celtics")
    posts=[dict(id=77,slug="insiders",status="publish",
                permalink="https://www.nba.com/celtics/news/insiders")]
    assert discover_nba_official_posts(index(posts),boston)==[]
