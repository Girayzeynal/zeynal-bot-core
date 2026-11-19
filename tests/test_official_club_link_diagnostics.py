"""No-network tests for diagnosing NBA official news parser misses."""
import pytest
from hybrid_engine.official_club_link_diagnostics import diagnose_links
from hybrid_engine.official_club_sources import registry, probe


def club(key="nba_denver_nuggets"):
    return next(x for x in registry() if x["club_key"]==key)


def test_news_200_but_no_matched_links_is_not_source_failure():
    html=b'''<a href="/nuggets/news">News</a>
    <a href="/nuggets/articles/injury-update-new-post">Club story (new URL pattern)</a>
    <a href="//evil.test/nuggets/news/forged-story">Untrusted host</a>
    <script src="/_next/static/test.js"></script>'''
    result=diagnose_links(html,club())
    assert result["audited_anchor_count"]==3
    assert result["same_club_host_href_count"]==2
    assert result["other_host_href_count"]==1
    assert result["allowed_article_path_href_count"]==0
    assert result["js_runtime_markers"]["next_static"] is True
    assert result["model_input"] is False
    assert "/nuggets/news" in result["article_like_unmatched_paths_sample"]
    assert not any("evil" in x for x in result["article_like_unmatched_paths_sample"])


def test_article_pattern_exists_but_missing_visible_text_is_visible_diagnostic():
    html=b'''<a href="/nuggets/news/official-roster-and-injury-report"><img alt="Team"></a>
    <a href="/nuggets/news/another-official-game-preview">Visible</a>'''
    result=diagnose_links(html,club())
    assert result["allowed_article_path_href_count"]==2
    assert result["allowed_article_path_unlabelled_count"]==1
    assert result["empty_label_count"]==1


def test_same_index_probe_diagnostics_costs_no_additional_network_requests():
    calls=[]
    def request(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",body=b"User-agent: *\nDisallow: /private",
                        http_status=200)
        return dict(status="DOCUMENT_RECEIVED",observed_at_utc=1795089600,
                    http_status=200,
                    body=b'<a href="/nuggets/articles/new-roster-entry">Club article</a>')
    result=probe(club(),requester=request,link_diagnostics=True)
    assert len(calls)==2
    assert result["source_http_status"]==200
    assert result["article_links"]==[]
    assert result["link_diagnostics"]["same_club_news_like_href_count"]==1
    assert result["link_diagnostics"]["diagnostic_only"] is True
    assert result["model_input"] is False


@pytest.mark.parametrize("data", [b"x"*(512*1024+1),"html","x",None])
def test_unbounded_or_nonbytes_refused(data):
    with pytest.raises(ValueError):
        diagnose_links(data,club())
