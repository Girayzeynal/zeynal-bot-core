"""Fail-closed extraction of official NBA injury PDF table rows.

This is a parser, not a verification of player identity or eligibility.
The caller must retain the captured PDF digest and validate source provenance.
Requires optional pdfplumber; absence fails explicitly.
"""
from io import BytesIO

HEADERS=('Game Date','Game Time','Matchup','Team','Player Name','Current Status','Reason')
OFFICIAL_HEADERS=('Date','Time (ET)','Matchup','Team','Player','Status','Injury / Illness / Notes')
COMPACT_HEADERS=('GameDate','GameTime','Matchup','Team','PlayerName','CurrentStatus','Reason')
SUPPORTED_HEADERS=frozenset((HEADERS,OFFICIAL_HEADERS,COMPACT_HEADERS))
STATUSES=frozenset({'Out','Doubtful','Questionable','Probable','Available'})


def _coordinate_rows(pdf):
    """Extract NBA text columns when pdfplumber detects headers but not body cells.

    Coordinate bands are anchored to the seven headers on each page, never to
    unvalidated text order. Sparse game/team cells inherit only within a game.
    """
    import re
    output=[]
    rejected=0
    context=None
    for page in pdf.pages:
        if not hasattr(page,'extract_words'):
            continue
        words=sorted(page.extract_words() or [],key=lambda w:(float(w['top']),float(w['x0'])))
        lines=[]
        for w in words:
            top=float(w['top'])
            if lines and abs(top-lines[-1][0])<=2.5:
                lines[-1][1].append(w)
            else:
                lines.append((top,[w]))
        header_index=None
        bounds=None
        for i,(_,line) in enumerate(lines):
            ordered=sorted(line,key=lambda w:float(w['x0']))
            joined=''.join(str(w['text']) for w in ordered).replace(' ','').lower()
            if all(token in joined for token in ('gamedate','gametime','matchup','playername','currentstatus','reason')):
                anchors=[]
                for token in ('GameDate','GameTime','Matchup','Team','PlayerName','CurrentStatus','Reason'):
                    match=next((w for w in ordered if str(w['text']).replace(' ','').lower()==token.lower()),None)
                    if match is None:
                        break
                    anchors.append(float(match['x0']))
                if len(anchors)==7 and all(a<b for a,b in zip(anchors,anchors[1:])):
                    bounds=[(a+b)/2 for a,b in zip(anchors,anchors[1:])]
                    header_index=i
                    break
        if bounds is None:
            continue
        for _,line in lines[header_index+1:]:
            cells=[[] for _ in range(7)]
            for w in sorted(line,key=lambda w:float(w['x0'])):
                x=float(w['x0'])
                column=sum(x>=b for b in bounds)
                cells[column].append(str(w['text']))
            values=[' '.join(c).strip() for c in cells]
            date,time,matchup,team,player,status,reason=values
            if not any(values):
                continue
            if date and not re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}',date):
                continue
            if matchup and not re.fullmatch(r'[A-Z]{2,4}@[A-Z]{2,4}',matchup):
                continue
            if team and not re.search(r'[A-Za-z]',team):
                continue
            if context:
                old_date,old_time,old_matchup,old_team=context
                if (date and date!=old_date) or (time and time!=old_time):
                    if not matchup:
                        context=None
                        rejected+=1
                        continue
                date=date or old_date
                time=time or old_time
                matchup=matchup or old_matchup
                if not team and matchup==old_matchup:
                    team=old_team
            if date and time and matchup and team:
                context=(date,time,matchup,team)
            if not player and reason.replace(' ','').upper()=='NOTYETSUBMITTED':
                rejected+=1
                continue
            if player and status in STATUSES and reason and date and time and matchup and team:
                output.append(dict(game_date=date,game_time=time,matchup=matchup,
                                   team=team,player_name=player,status=status,reason=reason))
            elif player or status:
                rejected+=1
    return output,rejected

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
    from core.team_identity import digest
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
        if not rows:
            coordinate_rows,coordinate_rejected=_coordinate_rows(pdf)
            rows.extend(coordinate_rows)
            rejected+=coordinate_rejected
    if recognized_tables==0 and not rows:
        raise ValueError('OFFICIAL_REPORT_TABLE_SCHEMA_UNRECOGNIZED')
    if not rows:
        return dict(status='NO_VERIFIED_TABLE_ROWS',rows=[],rejected_count=rejected,
                    source_pdf_sha256=expected_sha256,rows_sha256=digest([]),
                    extraction_verified=False)
    return dict(status='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION',rows=rows,
                source_pdf_sha256=expected_sha256,rows_sha256=digest(rows),
                rejected_count=rejected,extraction_verified=False)
