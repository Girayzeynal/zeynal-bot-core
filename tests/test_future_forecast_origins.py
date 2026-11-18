"""Synthetic checks for future forecast provenance without on-disk fixture mutation."""
from scripts.audit_future_forecast_origins import auto_evidence


def case(code="NBA"):
    return dict(league=code,sha="a"*64,fixture_id="fixed-event",
                provider_fixture_ids=["123"],archived=110)


def test_nba_scheduler_needs_same_sha_id_and_original_creation_window():
    entry=dict(evaluated_at_utc=100,completed_at_utc=120,
               predictions=[dict(snapshot_sha256="a"*64,
                                 provider_fixture_id="123",status="ARCHIVED")])
    assert auto_evidence(case(),[entry])=="AUTO_SCHEDULER_JOURNAL_SHA_AND_CLOCK_MATCHED"
    entry["predictions"][0]["status"]="REUSED"
    assert auto_evidence(case(),[entry])=="AUTO_EVIDENCE_NOT_FOUND_CREATOR_UNDETERMINED"
    entry["predictions"][0]["status"]="ARCHIVED"
    entry["predictions"][0]["snapshot_sha256"]="b"*64
    assert auto_evidence(case(),[entry])=="AUTO_EVIDENCE_NOT_FOUND_CREATOR_UNDETERMINED"
    entry["predictions"][0]["snapshot_sha256"]="a"*64
    entry["completed_at_utc"]=105
    assert auto_evidence(case(),[entry])=="AUTO_EVIDENCE_NOT_FOUND_CREATOR_UNDETERMINED"


def test_europe_scheduler_requires_new_record_and_same_fixture():
    r=dict(forecast_sha256="a"*64,fixture_id="fixed-event",status="ANALYSIS_OK",new_record=True)
    entry=dict(evaluated_at_utc=100,completed_at_utc=120,
               leagues={"EUROLEAGUE":{"results":[r]}})
    assert auto_evidence(case("EUROLEAGUE"),[entry])=="AUTO_SCHEDULER_JOURNAL_SHA_AND_CLOCK_MATCHED"
    r["new_record"]=False
    assert auto_evidence(case("EUROLEAGUE"),[entry])=="AUTO_EVIDENCE_NOT_FOUND_CREATOR_UNDETERMINED"


def test_absent_journal_is_not_manual_creation_evidence():
    assert auto_evidence(case(),None)=="JOURNAL_NOT_PRESENT"
    assert auto_evidence(case(),[])=="AUTO_EVIDENCE_NOT_FOUND_CREATOR_UNDETERMINED"
