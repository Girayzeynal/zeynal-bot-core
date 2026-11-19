"""Offline first-captured article evidence proof and fail-closed frozen forecast audit."""
from pathlib import Path

import pytest
from hybrid_engine import official_club_capture as cap
from hybrid_engine.official_club_prematch_gate import assess_against_frozen_forecast
from hybrid_engine.official_club_sources import registry

OBS=1795061771
SHA="a"*64
ART_URL="https://www.nba.com/nuggets/news/nuggets-conclude-road-trip-pelicans"

def club(key="nba_denver_nuggets"):
    return next(v for v in registry() if v["club_key"]==key)


def article():
    return dict(
        status="OFFICIAL_ARTICLE_OBSERVED_NOT_ROSTER_VERIFIED",
        source_http_status=200,
        source_url=ART_URL,
        body_sha256=SHA,
        club_key="nba_denver_nuggets",league="NBA",
        observed_at_utc=OBS,
        published_utc=OBS-3600,
        publication_time_status="PRECISE_PAGE_PUBLICATION_TIME",
        injury_absence_claim_candidates=[
            dict(player_name_text="Julian Strawther",
                 evidence_level="OFFICIAL_TEAM_REPORT_TEXT_CANDIDATE_ONLY",
                 model_input=False)],
        model_input=False)


def frozen():
    return dict(
        league="NBA",season="2026/2027",fixture_id="0022600300",
        home=dict(provider_id="1610612743"),
        away=dict(provider_id="1610612740"),
        prediction_generated_at_utc=OBS+120,
        created_at_utc=OBS+150,
        fixture_start_utc=OBS+3000,
        snapshot_sha256="b"*64)


def binding():
    return dict(
        league="NBA",fixture_id="0022600300",
        provider_team_id="1610612743",
        provider_player_id="1639999",
        player_name_text="Julian Strawther",
        identity_evidence_sha256="c"*64)


@pytest.fixture()
def allowed_capture_dir(tmp_path,monkeypatch):
    root=tmp_path/"zeynal-test-isolated"/"data"/"club-pilot-evidence"
    monkeypatch.setattr(cap,"_ALLOWED_ROOT",root.absolute())
    return root


def test_first_observation_receipt_is_immutable_by_article_content(allowed_capture_dir):
    a=article()
    receipt,path,new=cap.record_first_article_capture(
        a,club(),root=allowed_capture_dir,now_utc=OBS+10)
    assert new is True
    assert path.is_file()
    assert receipt["observed_at_utc"]==OBS
    assert receipt["captured_at_utc"]==OBS+10
    assert cap.verify_article_capture(receipt)==receipt
    later,laterpath,new2=cap.record_first_article_capture(
        a,club(),root=allowed_capture_dir,now_utc=OBS+500)
    assert new2 is False
    assert path==laterpath
    assert later==receipt
    changed=dict(a,body_sha256="d"*64)
    changedrec,newpath,is_new=cap.record_first_article_capture(
        changed,club(),root=allowed_capture_dir,now_utc=OBS+20)
    assert is_new is True
    assert newpath!=path
    assert changedrec["observed_at_utc"]==OBS


def test_receipt_tamper_is_rejected(allowed_capture_dir):
    rec,path,_=cap.record_first_article_capture(
        article(),club(),root=allowed_capture_dir,now_utc=OBS+10)
    bad=dict(rec,observed_at_utc=OBS-10000)
    with pytest.raises(ValueError,match="PIN_CONFLICT"):
        cap.verify_article_capture(bad)
    # Tainted on-disk receipt cannot be silently replaced.
    import json
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match="PIN_CONFLICT"):
        cap.record_first_article_capture(
            article(),club(),root=allowed_capture_dir,now_utc=OBS+25)


def test_cannot_write_outside_isolated_root(tmp_path,allowed_capture_dir):
    with pytest.raises(ValueError,match="ISOLATED_CLUB_CAPTURE_DIRECTORY_REQUIRED"):
        cap.record_first_article_capture(
            article(),club(),root=tmp_path/"other",now_utc=OBS+10)


def test_untrusted_article_hostname_or_clock_fail_closed(allowed_capture_dir):
    with pytest.raises(ValueError,match="HOST_CONFLICT"):
        cap.record_first_article_capture(
            dict(article(),source_url="https://not-nba.example/nuggets/news/fake"),
            club(),root=allowed_capture_dir,now_utc=OBS+10)
    with pytest.raises(ValueError,match="CLOCK"):
        cap.record_first_article_capture(
            article(),club(),root=allowed_capture_dir,now_utc=OBS-1)


def audit(article_override=None,frozen_override=None,binding_override=None,
          captured_override=None):
    a=article() if article_override is None else article_override
    f=frozen() if frozen_override is None else frozen_override
    b=binding() if binding_override is None else binding_override
    captured=dict(format=cap.RECEIPT_FORMAT,club_key=a["club_key"],
                  source_url=a["source_url"],body_sha256=a["body_sha256"],
                  observed_at_utc=a["observed_at_utc"],
                  captured_at_utc=a["observed_at_utc"]+10)
    import hashlib
    captured["receipt_sha256"]=hashlib.sha256(
        cap._packed(captured)).hexdigest()
    if captured_override is not None:
        captured=captured_override
    return assess_against_frozen_forecast(
        a,club=club(),frozen=f,captured=captured,binding=b)


def test_only_full_preforecast_pinned_identity_proof_is_human_shadow_review():
    result=audit()
    assert result["status"]=="SHADOW_REVIEW_ONLY"
    assert result["reasons"]==[]
    assert result["human_shadow_review_eligible"] is True
    assert result["model_input"] is False
    assert result["historical_forecast_modified"] is False


def test_later_observed_article_never_enters_earlier_frozen_forecast():
    f=frozen()
    f["prediction_generated_at_utc"]=OBS-100
    f["created_at_utc"]=OBS-20
    result=audit(frozen_override=f)
    assert result["status"]=="ABSTAIN"
    assert "ARTICLE_EVIDENCE_CAPTURED_AFTER_FROZEN_FORECAST" in result["reasons"]
    assert result["preforecast_captured"] is False
    assert result["model_input"] is False


def test_publication_display_date_alone_cannot_pass():
    a=article()
    a["published_utc"]=None
    a["publication_time_status"]="NO_VERIFIED_PUBLICATION_TIME"
    result=audit(article_override=a)
    assert result["status"]=="ABSTAIN"
    assert "PRECISE_ARTICLE_PUBLICATION_CLOCK_UNVERIFIED" in result["reasons"]


def test_missing_player_id_or_wrong_fixture_abstains():
    b=binding()
    b["provider_player_id"]=None
    b["fixture_id"]="MISMATCH"
    result=audit(binding_override=b)
    assert "INDEPENDENT_PLAYER_ROSTER_BINDING_REQUIRED" in result["reasons"]
    assert "INDEPENDENT_FIXTURE_BINDING_REQUIRED" in result["reasons"]


def test_article_seen_after_tipoff_refused_even_with_older_published_date():
    f=frozen()
    f["fixture_start_utc"]=OBS-10
    result=audit(frozen_override=f)
    assert result["status"]=="ABSTAIN"
    assert "ARTICLE_EVIDENCE_NOT_PRE_TIPOFF" in result["reasons"]


def test_tampered_receipt_blocked_and_never_preforecast_captured():
    a=article()
    r=dict(format=cap.RECEIPT_FORMAT,club_key=a["club_key"],
           source_url=a["source_url"],body_sha256=a["body_sha256"],
           observed_at_utc=OBS,captured_at_utc=OBS+10,
           receipt_sha256="9"*64)
    result=audit(captured_override=r)
    assert "FIRST_CAPTURE_RECEIPT_HASH_OR_CLOCK_INVALID" in result["reasons"]
    assert result["preforecast_captured"] is False
    assert result["human_shadow_review_eligible"] is False


def test_no_frozen_snapshot_is_abstain_not_green():
    result=assess_against_frozen_forecast(article(),club=club())
    assert result["status"]=="ABSTAIN"
    assert result["model_input"] is False
    assert "FROZEN_PRETIPOFF_FORECAST_IDENTITY_OR_PIN_REQUIRED" in result["reasons"]


def test_wrong_team_or_stale_article_is_rejected():
    f=frozen()
    f["home"]["provider_id"]="9999"
    f["away"]["provider_id"]="8888"
    result=audit(frozen_override=f)
    assert "SOURCE_TEAM_NOT_BOUND_TO_FIXTURE_SIDE" in result["reasons"]
    a=article()
    a["published_utc"]=OBS-10*86400
    result=audit(article_override=a)
    assert "ARTICLE_OLDER_THAN_72H_FOR_FIXTURE" in result["reasons"]
