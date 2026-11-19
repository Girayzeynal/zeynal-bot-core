"""Bounded official NBA PDF capture, for isolated research only.

Capture is intentionally separate from PDF table extraction and roster mapping.
Never claim that downloaded bytes establish player statuses.
"""
import hashlib
import time
from urllib.request import Request, urlopen
from hybrid_engine.nba_injury_source import official_nba_injury_report_reference

MAX_PDF_BYTES=8*1024*1024

def capture_official_injury_pdf(url, *, retrieved_at_utc, prediction_utc,
                                opener=urlopen):
    """Fetch an official report with bounded memory and return a provenance receipt.

    Caller must provide an actual capture timestamp, not a future timestamp.
    The report is not parsed and the bytes are never persisted by this function.
    """
    began=int(time.time())
    if type(retrieved_at_utc) is not int or not 0<=began-retrieved_at_utc<=30 or type(prediction_utc) is not int or began>prediction_utc:
        raise ValueError('ACTUAL_REPORT_RETRIEVAL_CLOCK_REQUIRED')
    reference=official_nba_injury_report_reference(
        url,retrieved_at_utc=retrieved_at_utc,prediction_utc=prediction_utc)
    req=Request(url,headers={'User-Agent':'ZeynalResearchInjuryEvidence/1.0',
                             'Accept':'application/pdf'})
    with opener(req,timeout=15) as response:
        final_url=response.geturl()
        if final_url!=url:
            raise ValueError('REPORT_REDIRECT_NOT_ALLOWED')
        declared=response.headers.get('Content-Length')
        if declared is not None and (not declared.isdecimal() or int(declared)>MAX_PDF_BYTES):
            raise ValueError('REPORT_SIZE_NOT_ALLOWED')
        body=response.read(MAX_PDF_BYTES+1)
    if len(body)>MAX_PDF_BYTES or len(body)<8 or not body.startswith(b'%PDF-'):
        raise ValueError('INVALID_OR_OVERSIZED_REPORT_PDF')
    completed=int(time.time())
    if not retrieved_at_utc<=began<=completed<=prediction_utc:
        raise ValueError('REPORT_DOWNLOAD_COMPLETED_AFTER_PREDICTION')
    return dict(reference,download_started_at_utc=began,download_completed_at_utc=completed,sha256=hashlib.sha256(body).hexdigest(),
                byte_count=len(body),download_verified=True,
                extraction_verified=False,player_status_records=[])
