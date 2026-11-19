"""No-network official NBA Next.js and JSON-LD source diagnostics."""
import json

import pytest

from hybrid_engine.official_club_embedded_diagnostics import diagnose_embedded
from hybrid_engine.official_club_sources import registry, probe


def club(key="nba_denver_nuggets"):
    return next(x for x in registry() if x["club_key"]==key)


def page(payload, kind="NEXT_DATA"):
    meta=(b'<script id="__NEXT_DATA__" type="application/json">' if kind=="NEXT_DATA"
          else b'<script type="application/ld+json">')
    return b"<html>"+meta+json.dumps(payload).encode("utf-8")+b"</script></html>"


def test_explicit_official_nba_next_data_news_urls_found_without_links():
    source=page({
        "props":{"pageProps":{
            "stories":[
                {"title":"Official team preview","url":"/nuggets/news/pre-game-preview-vs-celtics"},
                {"title":"Fake rival","url":"/celtics/news/fake-other-team"},
                {"title":"Bad origin","url":"https://evil.test/nuggets/news/fake-story"},
                {"title":"Query link","url":"/nuggets/news/not-valid?token=foo"}
            ]}},
        "page":"/nuggets/news"})
    report=diagnose_embedded(source,club())
    assert report["next_data_script_count"]==1
    assert report["has_page_props"] is True
    assert report["parse_error_count"]==0
    assert report["article_url_candidate_count"]==1
    assert report["article_urls_sample"]==[
        "https://www.nba.com/nuggets/news/pre-game-preview-vs-celtics"]
    assert report["model_input"] is False


def test_public_json_ld_article_url_can_be_reported_but_not_trusted_as_roster():
    source=page({"@context":"https://schema.org","@type":"ItemList",
                 "itemListElement":[{"@type":"NewsArticle","url":
                                     "https://www.nba.com/celtics/news/official-injury-update"}]},
                 kind="JSON_LD")
    report=diagnose_embedded(source,club("nba_boston_celtics"))
    assert report["json_ld_script_count"]==1
    assert report["article_url_candidate_count"]==1
    assert report["model_input"] is False


def test_next_data_non_article_keys_do_not_construct_article_url():
    source=page({"pageProps":{"news":[{"slug":"injury-update"}]},
                 "other":"https://www.nba.com/nuggets/news/a-story"})
    report=diagnose_embedded(source,club())
    assert report["article_url_candidate_count"]==0


def test_bad_json_and_oversized_document_fail_closed():
    malformed=b'<script id="__NEXT_DATA__">{unparseable]</script>'
    report=diagnose_embedded(malformed,club())
    assert report["parse_error_count"]==1
    assert report["article_url_candidate_count"]==0
    with pytest.raises(ValueError):
        diagnose_embedded(b"x"*(512*1024+1),club())


def test_same_robots_and_index_requests_with_embedded_diagnostics():
    calls=[]
    html=page({"props":{"pageProps":{"cards":[
        {"url":"/nuggets/news/official-lineup-update"}]}}})
    def requester(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"User-agent: *\nDisallow: /private")
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    observed_at_utc=1795089600,body=html)
    report=probe(club(),requester=requester,link_diagnostics=True)
    assert len(calls)==2
    assert report["article_links"]==[]
    assert report["embedded_diagnostics"]["article_url_candidate_count"]==1
    assert report["status"]=="PUBLIC_NEWS_PAGE_OBSERVED_NOT_PLAYER_VERIFIED"
    assert report["model_input"] is False


def test_other_league_diagnostic_refused():
    with pytest.raises(ValueError):
        diagnose_embedded(b"hello",next(c for c in registry()
                                       if c["club_key"]=="eurocup_tofas"))


def test_boston_insiders_landing_excluded_despite_article_like_route():
    source=page({"props":{"pageProps":{"cards":[
        {"url":"/celtics/news/insiders","slug":"insiders","title":"Insiders hub"},
        {"url":"/celtics/news/official-player-injury-update","slug":"official-player-injury-update",
         "headline":"Official injury update"}
    ]}}})
    report=diagnose_embedded(source,club("nba_boston_celtics"))
    assert report["article_url_candidate_count"]==1
    assert report["article_urls_sample"]==[
        "https://www.nba.com/celtics/news/official-player-injury-update"]
    assert report["slug_field_count"]==2
    assert len(report["slug_context_samples"])==2
    assert all(row["title_present"] for row in report["slug_context_samples"])
    assert report["model_input"] is False


def test_slug_metadata_alone_does_not_become_a_synthetic_article_url():
    source=page({"props":{"pageProps":{"items":[
        {"slug":"nuggets-vs-celtics-injury-preview","headline":"News headline"},
        {"slug":"nested-team-nav","title":"Navigation category"}
    ]}}})
    report=diagnose_embedded(source,club())
    assert report["slug_field_count"]==2
    assert report["article_url_candidate_count"]==0
    assert report["source"]=="EMBEDDED_OFFICIAL_HTML_NOT_PUBLISHED_ARTICLE"
