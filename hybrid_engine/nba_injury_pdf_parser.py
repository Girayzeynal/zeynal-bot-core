"""Fail-closed extraction of official NBA injury PDF table rows.

This is a parser, not a verification of player identity or eligibility.
The caller must retain the captured PDF digest and validate source provenance.
Requires optional pdfplumber; absence fails explicitly.
"""
from io import BytesIO

HEADERS=('Game Date','Game Time','Matchup','Team','Player Name','Current Status','Reason')
OFFICIAL_HEADERS=('Date','Time (ET)','Matchup','Team','Player','Status','Injury / Illness / Notes')
SUPPORTED_HEADERS=frozenset((HEADERS,OFFICIAL_HEADERS))
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
    active_table=False
    previous_context=None
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        if not 1<=len(pdf.pages)<=40:
            raise ValueError('INVALID_REPORT_PAGE_COUNT')
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table:
                    continue
                header=[str(x or '').strip().replace('\n',' ') for x in table[0]]
                if tuple(header) in SUPPORTED_HEADERS:
                    recognized_tables+=1
                    active_table=True
                    data_rows=table[1:]
                elif active_table and len(header)==len(HEADERS):
                    # A page break can omit the repeated header; treat first row as data
                    # only after a recognized header in an earlier table.
                    data_rows=table
                else:
                    active_table=False
                    previous_context=None
                    continue
                for cells in data_rows:
                    if len(cells)!=7:
                        rejected+=1
                        continue
                    values=[str(x or '').strip().replace('\n',' ') for x in cells]
                    date,time,matchup,team,player,status,reason=values
                    # Official NBA reports leave repeated date/time/matchup/team
                    # cells blank. Never carry a team into a newly named matchup.
                    if previous_context:
                        old_date,old_time,old_matchup,old_team=previous_context
                        # Never inherit an old team's matchup into a newly
                        # supplied game date/time without an explicit matchup.
                        if (date and date!=old_date) or (time and time!=old_time):
                            if not matchup:
                                rejected+=1
                                previous_context=None
                                continue
                        if not date:
                            date=old_date
                        if not time:
                            time=old_time
                        if not matchup:
                            matchup=old_matchup
                        if not team and matchup==old_matchup:
                            team=old_team
                    if date and time and matchup and team:
                        previous_context=(date,time,matchup,team)
                    elif matchup and previous_context and matchup!=previous_context[2]:
                        previous_context=None
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
