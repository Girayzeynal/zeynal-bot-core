"""Synthetic official article fetching, host and robots policy tests. No network."""
import pytest
from hybrid_engine.official_club_article_probe import probe_article
from hybrid_engine.official_club_sources import registry

TOFAS_URL="https://tofasspor.com/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda"

def club():
    return next(x for x in registry() if x["club_key"]=="eurocup_tofas")

def fake_request_factory(*,robots=b"User-agent: *\nDisallow: /private",include_link=True,publication_time=False):
    called=[]
    def fake(url,*,limit,expected_mime):
        called.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",http_status=200,body=robots)
        if url.endswith("/haberler"):
            markup=(f'<a href="{TOFAS_URL}">Chemnitz match preview</a>' if include_link else "<p>Other news</p>")
            return dict(status="DOCUMENT_RECEIVED",http_status=200,body=markup.encode(),
                        observed_at_utc=1795089600)
        date=(b'<meta property="article:published_time" content="2026-11-18T20:00:00+03:00">' if publication_time else b"")
        body=b"<h1>TOFAS Preview</h1><p>Club news, not verified injury roster.</p>"+date
        return dict(status="DOCUMENT_RECEIVED",http_status=200,body=body,observed_at_utc=1795089600)
    return fake,called

def test_article_verified_index_robot_and_metadata_only():
    fetch,calls=fake_request_factory(publication_time=True)
    result=probe_article(club(),TOFAS_URL,requester=fetch)
    assert calls==["https://tofasspor.com/robots.txt","https://tofasspor.com/haberler",TOFAS_URL]
    assert result["status"]=="OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED"
    assert result["article_title"]=="TOFAS Preview"
    assert result["published_utc"] is not None
    assert result["player_status_verified"] is False
    assert result["injury_verified"] is False
    assert result["fixture_id"] is None
    assert result["model_input"] is False
    assert result["body_sha256"]
    assert "Club news" not in repr(result)

def test_date_only_never_pretends_published_timestamp():
    fetch,_=fake_request_factory()
    result=probe_article(club(),TOFAS_URL,requester=fetch)
    assert result["published_utc"] is None
    assert result["publication_time_status"]=="NO_VERIFIED_PUBLICATION_TIME"

def test_link_not_found_does_not_fetch_story():
    fetch,calls=fake_request_factory(include_link=False)
    result=probe_article(club(),TOFAS_URL,requester=fetch)
    assert result["status"]=="ARTICLE_NOT_VERIFIED_IN_CURRENT_INDEX"
    assert calls==["https://tofasspor.com/robots.txt","https://tofasspor.com/haberler"]

def test_robots_prevents_article_request():
    fetch,calls=fake_request_factory(robots=b"User-agent: *\nDisallow: /haber-")
    result=probe_article(club(),TOFAS_URL,requester=fetch)
    assert result["status"]=="ROBOTS_DISALLOW"
    assert calls==["https://tofasspor.com/robots.txt"]

@pytest.mark.parametrize("url",[
    "https://evil.test/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda",
    "https://tofasspor.com:8123/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda",
    "http://tofasspor.com/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda",
    "https://tofasspor.com/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda?x=1",
])
def test_untrusted_article_url_never_fetches(url):
    fetch,calls=fake_request_factory()
    with pytest.raises(ValueError):
        probe_article(club(),url,requester=fetch)
    assert calls==[]
