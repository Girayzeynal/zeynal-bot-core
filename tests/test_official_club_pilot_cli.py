"""No-network compact audit and no-archive mutation CLI checks."""
import json

from hybrid_engine import official_club_pilot


def test_compact_six_club_probe_does_not_downgrade_missing_sources(monkeypatch,capsys):
    visited=[]
    def fake(item):
        visited.append(item["club_key"])
        return dict(club_key=item["club_key"],league=item["league"],
                    status="ROBOTS_UNAVAILABLE_OR_REFUSED" if len(visited)%2 else "PUBLIC_NEWS_PAGE_OBSERVED_NOT_PLAYER_VERIFIED",
                    source_http_status=200 if len(visited)%2==0 else None,
                    article_links=[{"url":"https://example.com/only-a-synthetic-test"}] if len(visited)%2==0 else [],
                    model_input=False)
    monkeypatch.setattr(official_club_pilot,"probe",fake)
    assert official_club_pilot.run(["--live","--summary"])==0
    out=capsys.readouterr().out.splitlines()
    reports=[json.loads(line) for line in out if line.startswith("{")]
    assert len(reports)==6
    assert len(visited)==6
    assert sum(x["article_candidate_count"] for x in reports)==3
    assert all(x["model_input"] is False for x in reports)
    assert all(x["production_changed"] is False for x in reports)
    assert all(x["status"] in ("ROBOTS_UNAVAILABLE_OR_REFUSED","PUBLIC_NEWS_PAGE_OBSERVED_NOT_PLAYER_VERIFIED") for x in reports)


def test_dry_run_produces_no_live_probe_calls(monkeypatch,capsys):
    monkeypatch.setattr(official_club_pilot,"probe",lambda _:1/0)
    assert official_club_pilot.run(["--summary"])==0
    out=capsys.readouterr().out
    assert out.count("READY_NOT_FETCHED")==6


def test_article_summary_remains_text_only(monkeypatch,capsys):
    from hybrid_engine import official_club_article_probe
    called=[]
    def fake(item,url):
        called.append((item["club_key"],url))
        return dict(club_key=item["club_key"],league=item["league"],
                    status="OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED",
                    injury_absence_claim_candidates=[{"player_name_text":"Yiğitcan Saybir"}],
                    publication_time_status="NO_VERIFIED_PUBLICATION_TIME",
                    model_input=False)
    monkeypatch.setattr(official_club_article_probe,"probe_article",fake)
    assert official_club_pilot.run(["--live","--summary","--club","eurocup_tofas",
                                    "--article-url","https://tofasspor.com/haber-3715-test_story"])==0
    out=capsys.readouterr().out
    result=next(json.loads(line) for line in out.splitlines() if line.startswith("{"))
    assert result["observation_kind"]=="SINGLE_ARTICLE"
    assert "article_candidate_count" not in result
    assert result["article_access_verified"] is False
    assert result["player_status_verified"] is False
    assert result["fixture_verified"] is False
    assert result["article_claim_candidate_names_text_only"]==["Yiğitcan Saybir"]
    assert result["model_input"] is False
    assert result["publication_time_status"]=="NO_VERIFIED_PUBLICATION_TIME"
    assert len(called)==1


def test_compact_nba_article_receipt_reports_provenance_not_false_zero_count(monkeypatch,capsys):
    from hybrid_engine import official_club_article_probe
    native_url="https://www.nba.com/nuggets/news/nuggets-conclude-road-trip-pelicans"
    def fake(item,url):
        assert item["club_key"]=="nba_denver_nuggets"
        assert url==native_url
        return dict(club_key=item["club_key"],league=item["league"],
                    status="OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED",
                    source_http_status=200,source_url=url,
                    article_headline_from_index="Denver official pregame preview",
                    document_bytes=18485,visible_text_chars=2100,
                    index_candidate_origin="OFFICIAL_NBA_EMBEDDED_PUBLISHED_POST",
                    index_raw_date="2026-11-14T06:30:00Z",
                    index_raw_timestamp=1794637800000,
                    index_clock_status="LISTING_DATE_TIMESTAMP_AGREE_UNVERIFIED",
                    index_native_post_id="101",
                    publication_time_status="NO_VERIFIED_PUBLICATION_TIME",
                    injury_claim_evidence_status="NO_EXPLICIT_SOURCE_TEXT_CANDIDATES",
                    body_sha256="a"*64,model_input=False,production_changed=False)
    monkeypatch.setattr(official_club_article_probe,"probe_article",fake)
    assert official_club_pilot.run(["--live","--summary","--club",
        "nba_denver_nuggets","--article-url",native_url])==0
    result=next(json.loads(line) for line in
                capsys.readouterr().out.splitlines() if line.startswith("{"))
    assert result["observation_kind"]=="SINGLE_ARTICLE"
    assert result["article_access_verified"] is True
    assert result["index_candidate_origin"]=="OFFICIAL_NBA_EMBEDDED_PUBLISHED_POST"
    assert result["index_clock_status"]=="LISTING_DATE_TIMESTAMP_AGREE_UNVERIFIED"
    assert result["publication_time_status"]=="NO_VERIFIED_PUBLICATION_TIME"
    assert result["document_bytes"]==18485
    assert result["player_status_verified"] is False
    assert result["model_input"] is False
    assert "article_candidate_count" not in result


def test_failed_news_index_is_unknown_not_zero(monkeypatch,capsys):
    monkeypatch.setattr(official_club_pilot,"probe",
        lambda item: dict(status="ROBOTS_UNAVAILABLE_OR_REFUSED",
                          league=item["league"],club_key=item["club_key"],
                          model_input=False))
    assert official_club_pilot.run(["--live","--summary","--club",
                                    "nba_denver_nuggets"])==0
    report=next(json.loads(x) for x in
                capsys.readouterr().out.splitlines() if x.startswith("{"))
    assert report["observation_kind"]=="NEWS_INDEX"
    assert "article_candidate_count" not in report
    assert report["status"]=="ROBOTS_UNAVAILABLE_OR_REFUSED"


def test_failed_article_status_is_not_success_and_no_news_count(monkeypatch,capsys):
    from hybrid_engine import official_club_article_probe
    monkeypatch.setattr(official_club_article_probe,"probe_article",
        lambda item,url: dict(status="ARTICLE_NOT_VERIFIED_IN_CURRENT_INDEX",
                              index_article_count=15,article_url=url,
                              model_input=False))
    assert official_club_pilot.run(["--live","--summary","--club",
        "nba_denver_nuggets","--article-url",
        "https://www.nba.com/nuggets/news/unknown-article"])==0
    report=next(json.loads(x) for x in
                capsys.readouterr().out.splitlines() if x.startswith("{"))
    assert report["index_article_count"]==15
    assert report["article_access_verified"] is False
    assert "article_candidate_count" not in report
    assert report["model_input"] is False
