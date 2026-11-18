"""No-network contract tests for the official six-club pilot."""
from datetime import datetime, timezone

import pytest

from hybrid_engine.official_club_sources import (
    FORMAT, allowed_by_robots, registry, probe, parse_metadata, _bounded_https
)


def test_six_verified_pilot_sources_no_fabricated_europe_team_ids():
    clubs=registry()
    assert len(clubs)==6
    assert [r["league"] for r in clubs].count("NBA")==2
    assert [r["league"] for r in clubs].count("EUROLEAGUE")==2
    assert [r["league"] for r in clubs].count("EUROCUP")==2
    assert all(r["native_team_id"] is None for r in clubs if r["league"]!="NBA")


@pytest.mark.parametrize("bad",[
    "http://tofasspor.com/haberler",
    "https://evil.test/anything",
    "https://tofasspor.com:8080/haberler",
    "https://tofasspor.com/haberler?q=secret",
    "https://tofasspor.com/../private",
    "https://tofasspor.com@evil.test/haberler",
])
def test_url_refuses_untrusted_locations(bad):
    with pytest.raises(ValueError):
        _bounded_https(bad, "tofasspor.com")


def test_robots_explicit_disallow_and_allow():
    url="https://tofasspor.com/haberler"
    assert allowed_by_robots("User-agent: *\nDisallow: /haberler",url) is False
    assert allowed_by_robots("User-agent: *\nDisallow: /private\n",url) is True


def test_publication_time_requires_explicit_timezone():
    observed=int(datetime(2026,11,19,10,0,tzinfo=timezone.utc).timestamp())
    body=b'<html><head><meta property="article:published_time" content="2026-11-18T12:00:00+03:00"><title>Team official announcement</title></head></html>'
    result=parse_metadata(body,observed_at_utc=observed)
    assert result["page_title"]=="Team official announcement"
    assert result["publication_time_status"]=="PRECISE_PAGE_PUBLICATION_TIME"
    assert result["published_utc"]==int(datetime(2026,11,18,9,tzinfo=timezone.utc).timestamp())
    missing=parse_metadata(b'<time datetime="2026-11-18">Date only</time>',observed_at_utc=observed)
    assert missing["published_utc"] is None
    assert missing["publication_time_status"]=="NO_VERIFIED_PUBLICATION_TIME"


def test_conflicting_published_times_refused():
    body=b'''<meta property="article:published_time" content="2026-11-18T11:00:00Z">
    <meta name="pubdate" content="2026-11-18T12:00:00Z">'''
    r=parse_metadata(body,observed_at_utc=1795089600)
    assert r["published_utc"] is None
    assert r["publication_time_status"]=="CONFLICTING_PAGE_PUBLICATION_CLOCKS"


def test_probe_respects_robots_and_never_inferrs_squad_availability():
    club=next(c for c in registry() if c["club_key"]=="eurocup_tofas")
    calls=[]
    def fake_get(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",body=b"User-agent: *\nDisallow: /private",
                        http_status=200)
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    observed_at_utc=1795089600,
                    body=b'<h1>Official club news</h1><p>Rumor is not confirmed lineup.</p>')
    result=probe(club,requester=fake_get)
    assert calls==["https://tofasspor.com/robots.txt",club["source_url"]]
    assert result["format"]==FORMAT
    assert result["status"]=="PUBLIC_NEWS_PAGE_OBSERVED_NOT_PLAYER_VERIFIED"
    assert result["injury_verified"] is False
    assert result["lineup_verified"] is False
    assert result["model_input"] is False
    assert result["fixture_id"] is None
    assert result["body_sha256"]
    assert "Rumor" not in repr(result)


def test_robots_block_never_fetches_content():
    club=next(c for c in registry() if c["club_key"]=="eurocup_tofas")
    calls=[]
    def fake_get(url,*,limit,expected_mime):
        calls.append(url)
        return dict(status="DOCUMENT_RECEIVED",
                    body=b"User-agent: *\nDisallow: /",http_status=200)
    result=probe(club,requester=fake_get)
    assert result["status"]=="ROBOTS_DISALLOW"
    assert len(calls)==1


def test_429_robots_denial_stops_without_bypass():
    club=next(c for c in registry() if c["club_key"]=="eurocup_tofas")
    calls=[]
    def fake_get(url,*,limit,expected_mime):
        calls.append(url)
        return dict(status="SOURCE_RATE_LIMITED",http_status=429)
    result=probe(club,requester=fake_get)
    assert result["status"]=="ROBOTS_UNAVAILABLE_OR_REFUSED"
    assert len(calls)==1


def test_alias_redirect_host_is_not_followed():
    club=next(c for c in registry() if c["club_key"]=="nba_denver_nuggets")
    calls=[]
    def fake_get(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="SOURCE_HTTP_ERROR",http_status=404)
        return dict(status="SOURCE_REDIRECT_REFUSED",http_status=302)
    result=probe(club,requester=fake_get)
    assert result["status"]=="SOURCE_REDIRECT_REFUSED"
    assert len(calls)==2
