"""Fail-closed extraction of official NBA injury PDF table rows.

This is a parser, not a verification of player identity or eligibility.
The caller must retain the captured PDF digest and validate source provenance.
Requires optional pdfplumber; absence fails explicitly.
"""
from io import BytesIO

HEADERS=('Game Date','Game Time','Matchup','Team','Player Name','Current Status','Reason')
STATUSES=frozenset({'Out','Doubtful','Questionable','Probable','Available'})

def extract_nba_injury_rows(pdf_bytes, *, expected_sha256):
    import hashlib
    if not isinstance(pdf_bytes,bytes) or not pdf_bytes.startswith(b'%PDF-'):
        raise ValueError('INVALID_PDF_BYTES')
    if len(pdf_bytes)>8*1024*1024:
        raise ValueError('OVERSIZED_PDF_BYTES')
    if hashlib.sha256(pdf_bytes).hexdigest()!=expected_sha256:
        raise ValueError('PDF_DIGEST_MISMATCH')
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError('PDFPLUMBER_REQUIRED_FOR_EXTRACTION') from exc
    rows=[]
    rejected=0
    recognized_tables=0
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        if not 1<=len(pdf.pages)<=40:
            raise ValueError('INVALID_REPORT_PAGE_COUNT')
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table:
                    continue
                header=[str(x or '').strip().replace('\n',' ') for x in table[0]]
                if tuple(header)!=HEADERS:
                    continue
                recognized_tables+=1
                for cells in table[1:]:
                    if len(cells)!=7:
                        rejected+=1
                        continue
                    values=[str(x or '').strip().replace('\n',' ') for x in cells]
                    date,time,matchup,team,player,status,reason=values
                    if (not matchup or not team or not player or
                            status not in STATUSES or not reason or
                            not date or not time or player in ('—','-')):
                        rejected+=1
                        continue
                    rows.append(dict(game_date=date,game_time=time,matchup=matchup,
                                     team=team,player_name=player,status=status,reason=reason))
    if recognized_tables==0:
        raise ValueError('OFFICIAL_REPORT_TABLE_SCHEMA_UNRECOGNIZED')
    if not rows:
        return dict(status='NO_VERIFIED_TABLE_ROWS',rows=[],rejected_count=rejected,
                    extraction_verified=False)
    return dict(status='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION',rows=rows,
                rejected_count=rejected,extraction_verified=False)
