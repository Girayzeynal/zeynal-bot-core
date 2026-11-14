"""Explicit verification boundary between parsed PDF rows and roster evidence.

An operator-provided extraction receipt is required. Never automatically
promote PDF table text to a verified NBA player status.
"""
from hybrid_engine.nba_injury_rows import map_official_injury_rows

def verified_pdf_roster_evidence(extraction, *, capture_receipt, verification,
                                 fixture_matchup, team_ids, player_ids,
                                 prediction_utc, fixture_start_utc):
    """Promote only digest-matched, independently verified extracted rows."""
    if not isinstance(capture_receipt,dict) or not capture_receipt.get('download_verified'):
        raise ValueError('CAPTURE_RECEIPT_REQUIRED')
    digest=capture_receipt.get('sha256')
    if not isinstance(digest,str) or len(digest)!=64:
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
    report=dict(capture_receipt,status='OFFICIAL_REPORT_CONTENT_VERIFIED',
                extraction_verified=True)
    return map_official_injury_rows(
        extraction['rows'],fixture_matchup=fixture_matchup,
        team_ids=team_ids,player_ids=player_ids,
        report_reference=report,prediction_utc=prediction_utc,
        fixture_start_utc=fixture_start_utc)
