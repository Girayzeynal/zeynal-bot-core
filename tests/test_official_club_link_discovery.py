"""No-network fixtures: bounded same-club official news link discovery."""
from hybrid_engine.official_club_link_discovery import discover_article_links
from hybrid_engine.official_club_sources import registry, probe


def club(key):
    return next(x for x in registry() if x["club_key"]==key)


def test_tofas_article_discovery_ignores_other_origins_scripts_and_duplicate():
    c=club("eurocup_tofas")
    body=b"""
    <a href="/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda">Official preview</a>
    <a href="https://www.tofasspor.com/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda">Repeat</a>
    <a href="javascript:alert('x')">Bad</a>
    <a href="https://evil.test/haber-111-misleading_news">Other club</a>
    <a href="/en/shop/">Shop</a>
    """
    links=discover_article_links(body,c)
    # www / non-www variants are distinct URL paths but both same official club.
    assert len(links)==2
    assert all("tofasspor.com" in x["url"] for x in links)
    assert all(x["player_status_verified"] is False for x in links)
    assert all(x["published_utc"] is None for x in links)


def test_cedevita_uses_real_root_article_path_and_filters_utility_pages():
    c=club("eurocup_cedevita_olimpija")
    body=b"""<a href="/en/dragons-face-rostock-on-tuesday/">Match preview</a>
    <a href="/en/club/">Club</a><a href="/en/news/">News index</a>
    <a href="https://evil.test/en/misleading-injury-release/">Mimic</a>"""
    links=discover_article_links(body,c)
    assert len(links)==1
    assert links[0]["url"]=="https://cedevita.olimpija.com/en/dragons-face-rostock-on-tuesday/"


def test_olympiacos_and_zalgiris_patterns_match_verified_official_examples():
    greek=discover_article_links(
        b'<a href="/en/news/announcements/19860-announcement-74.html">Announcement</a>',
        club("euroleague_olympiacos"))
    lithuania=discover_article_links(
        b'<a href="/naujienos/beprotiskos-pergales-pries-bayern-uzkulisiai-ir-rubines-emocijos">Club news</a>',
        club("euroleague_zalgiris"))
    assert len(greek)==1
    assert len(lithuania)==1


def test_pilot_probe_reads_only_robots_and_index_but_reports_candidate_links():
    item=club("eurocup_tofas")
    calls=[]
    def getter(url,*,limit,expected_mime):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"User-agent: *\nDisallow: /private\n")
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    body=b'<a href="/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda">Preview</a>',
                    observed_at_utc=1795089600)
    value=probe(item,requester=getter)
    assert len(calls)==2
    assert len(value["article_links"])==1
    assert value["article_links_status"]=="CANDIDATES_ONLY_NO_ARTICLE_FETCH"
    assert value["model_input"] is False
    assert value["fixture_id"] is None


def test_oversized_body_is_not_indexed():
    import pytest
    with pytest.raises(ValueError):
        discover_article_links(b"x"*(512*1024+1),club("eurocup_tofas"))


def test_celtics_insiders_hub_is_not_a_news_article():
    html=b'''<a href="/celtics/news/insiders">Celtics Insiders Central</a>
    <a href="/celtics/news/official-press-release-2026">Official release</a>'''
    links=discover_article_links(html,club("nba_boston_celtics"))
    assert len(links)==1
    assert links[0]["url"]=="https://www.nba.com/celtics/news/official-press-release-2026"
