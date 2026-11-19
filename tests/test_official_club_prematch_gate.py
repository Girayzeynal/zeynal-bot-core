"""Offline first-captured article evidence proof and fail-closed frozen forecast audit."""
from pathlib import Path

import pytest
from hybrid_engine import official_club_capture as cap
from hybrid_engine.official_club_prematch_gate import assess_against_frozen_forecast
from hybrid_engine.official_club_sources import registry
from hybrid_engine.official_club_team_crosswalk import audit_nba_team_crosswalk
from core.team_identity import digest, internal_team_id
from core.league_identity import resolve_league

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
        injury_absence_claim_candidates=[],
        nba_injury_report_claim_candidates=[
            dict(player_name_text="Julian Strawther",
                 reported_status="OUT",
                 reported_reason_text="Left Knee Sprain",
                 reason_category="INJURY_REASON_REPORTED",
                 evidence_level="OFFICIAL_TEAM_REPORT_TEXT_CANDIDATE_ONLY",
                 model_input=False)],
        model_input=False)


def frozen():
    return dict(
        league="NBA",season="2026/2027",fixture_id="0022600300",
        home=dict(provider_id="7"),  # Synthetic ESPN provider namespace.
        away=dict(provider_id="3"),
        prediction_generated_at_utc=OBS+120,
        created_at_utc=OBS+150,
        fixture_start_utc=OBS+3000,
        snapshot_sha256="b"*64)


def binding():
    return dict(
        league="NBA",fixture_id="0022600300",
        provider_team_id="7",
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


def synthetic_participants(*, observed=OBS-2400, ingested=OBS-2200,
                           team_name="Denver Nuggets", team_id="7"):
    # Synthetic but schema-consistent season-scoped ESPN team snapshot.
    spec=resolve_league("NBA")
    participant=dict(
        internal_id=internal_team_id(spec.identity_namespace,team_id),
        provider="ESPN",provider_id=team_id,official_name=team_name,
        aliases=[dict(name=team_name,kind="SOURCE_displayName",language="und",
                      valid_from_utc=observed,valid_until_utc=None)])
    p=dict(format="SEASON_PARTICIPANTS_V1",
           league_id="NBA",year=2026,season_id="2026/2027",
           observed_at_utc=observed,ingested_at_utc=ingested,
           participant_count=1,participants=[participant],
           source_pins={"membership":dict(
               url="https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2027/teams?limit=100",
               document_sha256="e"*64,observed_at_utc=observed,
               ingested_at_utc=ingested)},
           membership_basis="SEASON_PARTICIPANT_ENDPOINT_NOT_GAME_SAMPLES",
           source_attestation="LOCAL_HASH_NOT_INDEPENDENT_ATTESTATION")
    return dict(payload=p,sha256=digest(p))


def audit(article_override=None,frozen_override=None,binding_override=None,
          captured_override=None,participants_override=None):
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
    snap=synthetic_participants() if participants_override is None else participants_override
    return assess_against_frozen_forecast(
        a,club=club(),frozen=f,captured=captured,binding=b,
        participants_snapshot=snap,trusted_participant_sha256=snap["sha256"])


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


def test_nba_g_league_assignment_out_is_not_an_injury_out_claim():
    a=article()
    a["nba_injury_report_claim_candidates"][0]["reason_category"]="NON_INJURY_G_LEAGUE"
    a["nba_injury_report_claim_candidates"][0]["reported_reason_text"]="G League Assignment"
    result=audit(article_override=a)
    assert result["status"]=="ABSTAIN"
    assert "NO_EXPLICIT_PHYSICAL_INJURY_OUT_CLAIM_FOR_SHADOW" in result["reasons"]
    assert result["model_input"] is False


def test_nba_questionable_even_with_injury_is_not_out():
    a=article()
    a["nba_injury_report_claim_candidates"][0]["reported_status"]="QUESTIONABLE"
    result=audit(article_override=a)
    assert "NO_EXPLICIT_PHYSICAL_INJURY_OUT_CLAIM_FOR_SHADOW" in result["reasons"]
    assert result["human_shadow_review_eligible"] is False


def test_nba_text_claim_with_no_native_identity_never_passes():
    b=binding()
    b["provider_player_id"]=None
    result=audit(binding_override=b)
    assert "INDEPENDENT_PLAYER_ROSTER_BINDING_REQUIRED" in result["reasons"]


def test_tofas_native_team_id_unbound_cannot_reach_shadow_gate():
    a=article()
    a["club_key"]="eurocup_tofas"
    a["league"]="EUROCUP"
    a["source_url"]="https://tofasspor.com/haber-3715-tofas_eurocupta_chemnitz_deplasmaninda"
    a["injury_absence_claim_candidates"]=[
        dict(player_name_text="Efe Postel",
             reported_status="CLUB_STATES_UNAVAILABLE_FOR_THIS_MATCH",
             reported_reason="INJURY_IN_SOURCE_SENTENCE",model_input=False)]
    a["nba_injury_report_claim_candidates"]=[]
    f=frozen()
    f["league"]="EUROCUP"
    b=binding()
    b["league"]="EUROCUP"
    b["player_name_text"]="Efe Postel"
    # Create a signed capture matching this article, but no native EuroCup
    # team identity is yet present in the manifest. Must remain abstain.
    captured=dict(format=cap.RECEIPT_FORMAT,club_key=a["club_key"],
                  source_url=a["source_url"],body_sha256=a["body_sha256"],
                  observed_at_utc=OBS,captured_at_utc=OBS+10)
    import hashlib
    captured["receipt_sha256"]=hashlib.sha256(cap._packed(captured)).hexdigest()
    result=assess_against_frozen_forecast(
        a,club=club("eurocup_tofas"),frozen=f,captured=captured,binding=b)
    assert result["status"]=="ABSTAIN"
    assert "SOURCE_TEAM_NOT_BOUND_TO_FIXTURE_SIDE" in result["reasons"]
    assert result["model_input"] is False


def test_same_pinned_article_version_reobserved_later_uses_original_capture():
    a=article()
    receipt=dict(format=cap.RECEIPT_FORMAT,club_key=a["club_key"],
                 source_url=a["source_url"],body_sha256=a["body_sha256"],
                 observed_at_utc=OBS,captured_at_utc=OBS+10)
    import hashlib
    receipt["receipt_sha256"]=hashlib.sha256(cap._packed(receipt)).hexdigest()
    later=dict(a,observed_at_utc=OBS+3*86400)
    # Re-fetch is three days later, but the exact version was captured
    # before the immutable forecast. No retroactive look-ahead.
    report=assess_against_frozen_forecast(
        later,club=club(),frozen=frozen(),captured=receipt,binding=binding(),
        participants_snapshot=synthetic_participants(),
        trusted_participant_sha256=synthetic_participants()["sha256"])
    assert report["status"]=="SHADOW_REVIEW_ONLY"
    assert report["model_input"] is False


def test_later_reobserved_modified_article_must_not_use_earlier_version_receipt():
    a=article()
    receipt=dict(format=cap.RECEIPT_FORMAT,club_key=a["club_key"],
                 source_url=a["source_url"],body_sha256=a["body_sha256"],
                 observed_at_utc=OBS,captured_at_utc=OBS+10)
    import hashlib
    receipt["receipt_sha256"]=hashlib.sha256(cap._packed(receipt)).hexdigest()
    changed=dict(a,body_sha256="d"*64,observed_at_utc=OBS+3*86400)
    report=assess_against_frozen_forecast(
        changed,club=club(),frozen=frozen(),captured=receipt,binding=binding(),
        participants_snapshot=synthetic_participants(),
        trusted_participant_sha256=synthetic_participants()["sha256"])
    assert report["status"]=="ABSTAIN"
    assert "PINNED_FIRST_CAPTURE_RECEIPT_REQUIRED" in report["reasons"]


def test_first_capture_from_after_frozen_game_is_always_blocked_even_if_post_old():
    a=article()
    f=frozen()
    f["prediction_generated_at_utc"]=OBS-60
    f["created_at_utc"]=OBS-30
    f["fixture_start_utc"]=OBS+300
    report=audit(article_override=a,frozen_override=f)
    assert "ARTICLE_EVIDENCE_CAPTURED_AFTER_FROZEN_FORECAST" in report["reasons"]
    assert report["status"]=="ABSTAIN"
    assert report["historical_forecast_modified"] is False


def test_native_nba_team_id_and_espn_team_id_are_not_interchangeable():
    snap=synthetic_participants()
    bridge=audit_nba_team_crosswalk(
        club(),snap,trusted_snapshot_sha256=snap["sha256"],
        asof_utc=frozen()["prediction_generated_at_utc"])
    assert bridge["nba_com_team_id"]=="1610612743"
    assert bridge["espn_team_id"]=="7"
    assert bridge["nba_com_team_id"]!=bridge["espn_team_id"]
    assert bridge["model_input"] is False
    assert bridge["verified_fixture_id"] is None
    assert bridge["source_participant_ingested_at_utc"]<frozen()["prediction_generated_at_utc"]


def test_wrong_namespace_in_forecast_abstains_even_with_valid_snapshot():
    f=frozen()
    f["home"]["provider_id"]="1610612743"  # NBA.com ID inside ESPN forecast.
    result=audit(frozen_override=f)
    assert result["status"]=="ABSTAIN"
    assert "SOURCE_TEAM_NOT_BOUND_TO_FIXTURE_SIDE" in result["reasons"]


def test_missing_nba_team_crosswalk_source_blocks_shadow_review():
    a=article()
    captured=dict(format=cap.RECEIPT_FORMAT,club_key=a["club_key"],
                  source_url=a["source_url"],body_sha256=a["body_sha256"],
                  observed_at_utc=OBS,captured_at_utc=OBS+10)
    import hashlib
    captured["receipt_sha256"]=hashlib.sha256(cap._packed(captured)).hexdigest()
    result=assess_against_frozen_forecast(
        a,club=club(),frozen=frozen(),captured=captured,binding=binding())
    assert result["status"]=="ABSTAIN"
    assert "NBA_OFFICIAL_TO_ESPN_TEAM_CROSSWALK_UNVERIFIED" in result["reasons"]
    assert result["model_input"] is False


def test_season_membership_collected_after_prediction_cannot_be_backfilled():
    snapshot=synthetic_participants(observed=OBS+60,ingested=OBS+90)
    f=frozen()
    f["prediction_generated_at_utc"]=OBS+50
    f["created_at_utc"]=OBS+80
    result=audit(frozen_override=f,participants_override=snapshot)
    assert "NBA_OFFICIAL_TO_ESPN_TEAM_CROSSWALK_UNVERIFIED" in result["reasons"]
    assert result["status"]=="ABSTAIN"


def test_team_name_or_trusted_pin_mismatch_abstains():
    snapshot=synthetic_participants(team_name="Fake Nuggets")
    result=audit(participants_override=snapshot)
    assert "NBA_OFFICIAL_TO_ESPN_TEAM_CROSSWALK_UNVERIFIED" in result["reasons"]
    assert result["model_input"] is False
    good=synthetic_participants()
    with pytest.raises(ValueError):
        audit_nba_team_crosswalk(
            club(),good,trusted_snapshot_sha256="f"*64,
            asof_utc=frozen()["prediction_generated_at_utc"])


def test_ambiguous_crosswalk_name_refused():
    snap=synthetic_participants()
    p=snap["payload"]
    first=p["participants"][0]
    import copy
    same=copy.deepcopy(first)
    same["provider_id"]="2"
    same["internal_id"]=internal_team_id(resolve_league("NBA").identity_namespace,"2")
    p["participants"].append(same)
    p["participant_count"]=2
    snap["sha256"]=digest(p)
    result=audit(participants_override=snap)
    assert "NBA_OFFICIAL_TO_ESPN_TEAM_CROSSWALK_UNVERIFIED" in result["reasons"]
