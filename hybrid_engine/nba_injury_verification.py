"""Explicit verification boundary between parsed PDF rows and roster evidence.

An operator-provided extraction receipt is required. Never automatically
promote PDF table text to a verified NBA player status.
"""
import time
from core.team_identity import digest as content_digest
from hybrid_engine.nba_injury_source import official_nba_injury_report_reference
from hybrid_engine.nba_injury_rows import map_official_injury_rows
from hybrid_engine.nba_injury_id_audit import audit_injury_id_mapping

def verified_pdf_roster_evidence(extraction, *, capture_receipt, verification,
                                 fixture_matchup, team_ids, player_ids,
                                 prediction_utc, fixture_start_utc):
    """Promote only digest-matched, independently verified extracted rows."""
    if not isinstance(capture_receipt,dict) or capture_receipt.get('download_verified') is not True:
        raise ValueError('CAPTURE_RECEIPT_REQUIRED')
    digest=capture_receipt.get('sha256')
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('CAPTURE_DIGEST_REQUIRED')
    if (not isinstance(extraction,dict) or
            extraction.get('status')!='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION' or
            not isinstance(extraction.get('rows'),list)):
        raise ValueError('PARSED_ROWS_REQUIRED')
    if (not isinstance(verification,dict) or
            verification.get('verified') is not True or
            verification.get('sha256')!=digest or
            verification.get('fixture_matchup')!=fixture_matchup or
            verification.get('player_id_mapping_verified') is not True or
            verification.get('team_id_mapping_verified') is not True):
        raise ValueError('INDEPENDENT_EXTRACTION_VERIFICATION_REQUIRED')
    reference=official_nba_injury_report_reference(capture_receipt['source_url'],
        retrieved_at_utc=capture_receipt.get('retrieved_at_utc'),prediction_utc=prediction_utc)
    completed=capture_receipt.get('download_completed_at_utc');verified=verification.get('verified_at_utc')
    if (type(completed) is not int or type(verified) is not int or
        not reference['retrieved_at_utc']<=completed<=verified<=min(prediction_utc,int(time.time())) or
        prediction_utc-reference['report_timestamp_utc']>6*3600):
        raise ValueError('INJURY_EVIDENCE_UNAVAILABLE_OR_STALE_AT_PREDICTION')
    rows_pin=content_digest(extraction['rows'])
    if (extraction.get('source_pdf_sha256')!=digest or extraction.get('rows_sha256')!=rows_pin or
        verification.get('rows_sha256')!=rows_pin or
        capture_receipt.get('report_timestamp_utc')!=reference['report_timestamp_utc']):
        raise ValueError('INJURY_PARSED_ROWS_OR_PUBLICATION_PIN_CONFLICT')
    audit=audit_injury_id_mapping(extraction['rows'],fixture_matchup=fixture_matchup,
        team_ids=team_ids,player_ids=player_ids)
    if not audit['identity_mapping_complete']:
        raise ValueError('INCOMPLETE_OR_DUPLICATE_PLAYER_ID_MAPPING')
    report=dict(capture_receipt,status='OFFICIAL_REPORT_CONTENT_VERIFIED',
                extraction_verified=True)
    return map_official_injury_rows(
        extraction['rows'],fixture_matchup=fixture_matchup,
        team_ids=team_ids,player_ids=player_ids,
        report_reference=report,prediction_utc=prediction_utc,
        fixture_start_utc=fixture_start_utc)
