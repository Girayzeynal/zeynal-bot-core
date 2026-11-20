"""The four new official links are discoverable, NOT four injury feeds."""
import copy
import json

import pytest
from hybrid_engine import official_club_discovered_candidates as dc


def test_four_official_discovered_news_links_are_not_verified_connected_feeds():
    rows=dc.discovered_registry()
    assert len(rows)==4
    assert {r["league"] for r in rows}=={"NBA","EUROLEAGUE","EUROCUP"}
    assert {r["club_key"] for r in rows}==dc.CANDIDATE_KEYS
    assert all(r["status"]=="PUBLIC_LINK_DISCOVERED_NOT_PROBED" for r in rows)
    assert all(r["host"] and r["path"] for r in rows)
    for r in rows:
        state=dc.observe_candidate(r["club_key"],live=False,
                                  requester=lambda *a,**k:1/0)
        assert state["status"]=="DISCOVERED_URL_NOT_LIVE_CHECKED"
        assert state["model_input"] is False
        assert state["requests"]==0


def test_robots_denial_blocks_new_candidate_before_fetching_news_page():
    calls=[]
    def fetch(url,*,limit,expected_mime):
        calls.append(url)
        return dict(status="SOURCE_ACCESS_REFUSED",http_status=403)
    r=dc.observe_candidate("euroleague_anadolu_efes_istanbul",
                           live=True,requester=fetch)
    assert r["status"]=="ABSTAIN_CANDIDATE_SOURCE_NOT_ACCESS_VERIFIED"
    assert r["robots_http_status"]==403
    assert r["verified_player_ids"]==0
    assert r["model_input"] is False
    assert len(calls)==1
    assert calls[0].endswith("/robots.txt")


def test_permitted_news_index_yields_only_source_candidates_not_injuries():
    requests=[]
    def fetch(url,*,limit,expected_mime):
        requests.append(url)
        if url.endswith("/robots.txt"):
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"User-agent: *\nAllow: /\n")
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    body=b"<html><title>News</title><h1>Club news</h1></html>",
                    observed_at_utc=1795000000)
    r=dc.observe_candidate("euroleague_panathinaikos_athens",
                           live=True,requester=fetch)
    assert r["status"]=="PUBLIC_NEWS_INDEX_OBSERVED_NOT_PLAYER_VERIFIED"
    assert r["verified_player_ids"]==0
    assert r["observed_claims"]==0
    assert r["article_url_candidate_count"]==0
    assert r["model_input"] is False
    assert len(requests)==2


def test_discovered_news_url_must_not_promote_to_six_verified_sources(tmp_path):
    rows=json.loads(dc.MANIFEST.read_text())
    x=next(r for r in rows["candidates"] if
           r["club_key"]=="euroleague_panathinaikos_athens")
    x["status"]="PLAYER_STATUS_VERIFIED"
    path=tmp_path/"discovered.json"
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError,match="DISCOVERED_CLUB_IDENTITY"):
        dc.discovered_registry(path)


def test_discovered_url_cli_is_only_metadata_no_network(capsys):
    assert dc.run([])==0
    r=json.loads(capsys.readouterr().out.strip())
    assert r["total_candidates"]==4
    assert r["connected_player_feeds"]==0
    assert r["requests"]==0
    assert r["model_input"] is False
    assert r["production_changed"] is False
