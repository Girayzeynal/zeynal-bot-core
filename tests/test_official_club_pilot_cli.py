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
    assert result["article_claim_candidate_names_text_only"]==["Yiğitcan Saybir"]
    assert result["model_input"] is False
    assert result["publication_time_status"]=="NO_VERIFIED_PUBLICATION_TIME"
    assert len(called)==1
