"""Exhaustive 82-club source batch: one command, strict provenance and robots."""
import copy
import json
from urllib.parse import urlsplit

import pytest

from hybrid_engine import official_all_82_club_batch as bulk


def test_82_club_urls_every_league_exhaustive_no_nulls():
    rows=bulk.load_all_82()
    assert len(rows)==82
    assert len({r["club_key"] for r in rows})==82
    assert {league:sum(r["league"]==league for r in rows)
            for league in bulk.EXPECTED}==bulk.EXPECTED
    assert all(r["official_site_url"].startswith("https://")
               and r["official_news_entry_url"].startswith("https://")
               for r in rows)
    assert all(r["player_identity_verified"] is False
               and r["injury_or_lineup_verified"] is False
               and r["model_input"] is False for r in rows)
    assert {r["club_key"] for r in rows}=={
        r["club_key"] for r in bulk.load_coverage()["teams"]}
    assert len([r for r in rows if r["news_entry_kind"]=="DIRECT_NEWS"])==39


def test_batch_default_lists_all_82_without_any_network():
    def no_network(*args,**kwargs):
        raise AssertionError("Default called network")
    report=bulk.batch_probe(live=False,requester=no_network)
    assert report["status"]=="ALL_82_URLS_REGISTERED_ZERO_NETWORK"
    assert report["registry_size"]==82
    assert report["source_http_requests"]==0
    assert len(report["results"])==82
    assert report["source_observed_count"]==0
    assert report["player_injury_feed_connected_count"]==0
    assert report["model_input"] is False
    assert report["archives_modified"] is False
    assert report["production_changed"] is False


def _all_allowed(url,*,limit,expected_mime):
    if url.endswith("/robots.txt"):
        return dict(status="DOCUMENT_RECEIVED",http_status=200,
                    body=b"User-agent: *\nAllow: /\n")
    return dict(status="DOCUMENT_RECEIVED",http_status=200,
                body=b"<html><h1>Official team news</h1></html>",
                observed_at_utc=1795000000)


def test_all_82_batch_one_run_cached_robots_and_82_html_probes():
    requests=[]
    def fetch(url,*,limit,expected_mime):
        requests.append(url)
        return _all_allowed(url,limit=limit,expected_mime=expected_mime)
    report=bulk.batch_probe(live=True,requester=fetch)
    assert report["registry_size"]==82
    assert report["scan_complete"] is True
    assert report["scan_capped"] is False
    assert report["unattempted_count"]==0
    assert report["source_observed_count"]==82
    assert report["source_blocked_or_unavailable_count"]==0
    assert report["source_http_requests"]==len(requests)
    assert len([x for x in requests if not x.endswith("/robots.txt")])==82
    hosts={urlsplit(r["official_news_entry_url"]).hostname
           for r in bulk.load_all_82()}
    assert len([x for x in requests if x.endswith("/robots.txt")])==len(hosts)
    assert requests.count("https://www.nba.com/robots.txt")==1
    assert report["player_injury_feed_connected_count"]==0
    assert report["verified_player_count"]==0
    assert report["model_input"] is False
    assert report["production_changed"] is False
    assert report["archives_modified"] is False
    assert all(r["status"]=="NEWS_ENTRY_HTTP_OBSERVED_NOT_INJURY_VERIFIED"
               for r in report["results"])


def test_robots_403_one_host_is_skipped_for_all_30_nba_clubs():
    calls=[]
    def fetch(url,*,limit,expected_mime):
        calls.append(url)
        if url=="https://www.nba.com/robots.txt":
            return dict(status="SOURCE_ACCESS_REFUSED",http_status=403)
        return _all_allowed(url,limit=limit,expected_mime=expected_mime)
    result=bulk.batch_probe(live=True,requester=fetch)
    nba=[x for x in result["results"] if x["league"]=="NBA"]
    assert len(nba)==30
    assert all(x["status"]=="ROBOTS_UNAVAILABLE_OR_REFUSED_NO_NEWS_FETCH"
               for x in nba)
    assert all(x["robots_http_status"]==403 for x in nba)
    assert "https://www.nba.com/robots.txt" in calls
    assert not any(url.startswith("https://www.nba.com/") and
                   not url.endswith("/robots.txt") for url in calls)
    assert result["source_observed_count"]==52
    assert result["source_blocked_or_unavailable_count"]==30
    assert result["unattempted_count"]==0
    assert result["model_input"] is False


def test_robots_disallow_and_cloudflare_do_not_promote_index():
    def fetch(url,*,limit,expected_mime):
        if url.endswith("/robots.txt") and "olympiacosbc.gr" in url:
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"User-agent: *\nDisallow: /\n")
        if "zalgiris.lt/naujienos" in url:
            return dict(status="DOCUMENT_RECEIVED",http_status=200,
                        body=b"<html><title>Just a moment...</title>"
                             b"Verify you are human</html>",
                        observed_at_utc=1795000000)
        return _all_allowed(url,limit=limit,expected_mime=expected_mime)
    result=bulk.batch_probe(live=True,requester=fetch)
    by_key={r["club_key"]:r for r in result["results"]}
    assert by_key["euroleague_olympiacos"]["status"]=="ROBOTS_DISALLOW_NO_NEWS_FETCH"
    assert by_key["euroleague_zalgiris"]["status"]=="ANTI_BOT_CHALLENGE_NOT_NEWS_SOURCE"
    assert result["source_observed_count"]==80
    assert result["player_injury_feed_connected_count"]==0


def test_invalid_source_does_not_break_remaining_clubs():
    def fetch(url,*,limit,expected_mime):
        if url=="https://www.nba.com/celtics/news":
            return dict(status="SOURCE_ACCESS_REFUSED",http_status=403)
        return _all_allowed(url,limit=limit,expected_mime=expected_mime)
    report=bulk.batch_probe(live=True,requester=fetch)
    assert report["source_observed_count"]==81
    assert report["source_blocked_or_unavailable_count"]==1
    assert report["scan_complete"] is True
    assert report["source_http_requests"]<=bulk.MAX_REQUESTS


def test_global_budget_is_honest_not_false_full_verification():
    ticks=[0]
    def clock():
        ticks[0]+=1
        return ticks[0]
    report=bulk.batch_probe(live=True,requester=_all_allowed,
                            monotonic=clock,deadline_seconds=2)
    assert report["scan_complete"] is False
    assert report["scan_capped"] is True
    assert report["source_observed_count"]==0
    assert report["unattempted_count"]>=80
    assert report["status"]=="ALL_82_BATCH_PARTIAL_BUDGET_WITH_PER_SOURCE_STATUS"


def test_paris_media_impostor_and_two_roma_club_collision_refused(tmp_path):
    payload=json.loads(bulk.MANIFEST.read_text())
    paris=next(x for x in payload["records"]
               if x["club_key"]=="euroleague_paris_basketball")
    paris["official_site_url"]="https://parisbasketball.paris"
    paris["official_news_entry_url"]="https://parisbasketball.paris/news"
    path=tmp_path/"wrong-paris.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match="ALL_82_PARIS_MEDIA_IMPERSONATION"):
        bulk.load_all_82(path)
    payload=json.loads(bulk.MANIFEST.read_text())
    one=next(x for x in payload["records"] if
             x["club_key"]=="eurocup_roma_basketball")
    other=next(x for x in payload["records"] if
               x["club_key"]=="eurocup_maxima_roma")
    one["official_site_url"]=other["official_site_url"]
    one["official_news_entry_url"]=other["official_news_entry_url"]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match="ALL_82_ROMA_TEAMS_MUST_BE_DISTINCT"):
        bulk.load_all_82(path)


def test_cannot_enable_model_injury_feeds_or_swap_original_pilot_url(tmp_path):
    doc=json.loads(bulk.MANIFEST.read_text())
    doc["records"][0]["model_input"]=True
    path=tmp_path/"tamper.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match="UNVERIFIED_SOURCE_MUST_NOT_PROMOTE"):
        bulk.load_all_82(path)
    doc=json.loads(bulk.MANIFEST.read_text())
    p=next(x for x in doc["records"] if x["club_key"]=="nba_denver_nuggets")
    p["official_news_entry_url"]="https://www.nba.com/denver/misc"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match="ALL_82_(ORIGINAL_PILOT_SITE_CHALLENGED|NBA_NEWS_TEAM_PATH_MISMATCH)"):
        bulk.load_all_82(path)


def test_cli_single_entry_point_all_82_summary_no_http(capsys):
    assert bulk.run(["--summary"])==0
    report=json.loads(capsys.readouterr().out.strip())
    assert report["registry_size"]==82
    assert len(report["results"])==82
    assert report["source_http_requests"]==0
    assert report["source_observed_count"]==0



def test_single_user_csv_matches_every_json_registry_link():
    import csv
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/"docs"/"official_all_82_club_urls_2026_27.csv"
    with path.open(encoding="utf-8-sig",newline="") as stream:
        rows=list(csv.DictReader(stream))
    expected=bulk.load_all_82()
    assert len(rows)==len(expected)==82
    joined={r["official_team_name"]:r for r in rows}
    for entry in expected:
        row=joined[entry["official_team_name"]]
        assert row["league"]==entry["league"]
        assert row["official_site_url"]==entry["official_site_url"]
        assert row["official_news_entry_url"]==entry["official_news_entry_url"]
        assert row["news_entry_kind"]==entry["news_entry_kind"]
        assert row["live_http_status"]=="NOT_CHECKED_IN_UNIFIED_82_BATCH"


def test_nba_news_must_stay_under_that_teams_nba_directory():
    doc=json.loads(bulk.MANIFEST.read_text())
    row=next(x for x in doc["records"] if
             x["club_key"]=="nba_boston_celtics")
    row["official_news_entry_url"]="https://www.nba.com/lakers/news"
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/"bad_team_news.json"
        path.write_text(json.dumps(doc))
        with pytest.raises(ValueError,match="ALL_82_NBA_NEWS_TEAM_PATH_MISMATCH"):
            bulk.load_all_82(path)
