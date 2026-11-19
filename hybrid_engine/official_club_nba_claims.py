"""Strict, scoped NBA official team injury-report *text candidate* detector.

Only Denver pilot: extract explicit statements under INJURY REPORT -> Denver.
Never treat G League assignments as physical injuries; never infer native
player IDs, match identity, a verified first-publication clock, or model input.
Returns at most six report lines; unknown wording is intentionally ignored.
"""
import re
import unicodedata

_MAX_TEXT=8192
_MAX_SECTION=1800
_MAX_CANDIDATES=6
_NAME=r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'’.-]{1,32}(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'’.-]{1,32}|II|III|IV|Jr\.|Sr\.)){1,4}"
_STATUS=re.compile(
    rf"(?<![A-Za-z])(?P<name>{_NAME})\s*[—–]\s*"
    r"(?P<status>OUT|DOUBTFUL|QUESTIONABLE|PROBABLE|AVAILABLE)"
    r"\s*\((?P<reason>[^()]{3,120})\)",re.I|re.UNICODE)
_SECTION=re.compile(r"\bINJURY\s+REPORT\b",re.I)
_TEAM=re.compile(r"\bDenver\s*:\s*",re.I)
_STOP=re.compile(
    r"\b(?:New\s+Orleans|Boston|Phoenix|Memphis|Dallas|Houston|Minnesota|"
    r"Golden\s+State|Sacramento|Portland|Los\s+Angeles|Chicago|Utah|"
    r"San\s+Antonio|Oklahoma\s+City|TUNE[\s-]*IN|MATCHUP|"
    r"NEXT\s+UP|GAME\s+DETAILS)\s*:",re.I)

def nba_injury_report_candidates(visible_text,*,club_key):
    if club_key!="nba_denver_nuggets":
        return []
    if not isinstance(visible_text,str) or len(visible_text)>_MAX_TEXT:
        raise ValueError("OFFICIAL_NBA_REPORT_TEXT_BUDGET")
    text=unicodedata.normalize("NFC"," ".join(visible_text.split()))
    heading=_SECTION.search(text)
    if heading is None:
        return []
    # Insist on the named source team, not an opponent's injury report.
    heading_tail=text[heading.end():heading.end()+_MAX_SECTION]
    team=_TEAM.search(heading_tail[:250])
    if team is None:
        return []
    section=heading_tail[team.end():]
    stop=_STOP.search(section)
    if stop is not None:
        section=section[:stop.start()]
    out=[];seen=set()
    for m in _STATUS.finditer(section):
        name=" ".join(m.group("name").split())
        key=name.casefold()
        if key in seen:
            continue
        seen.add(key)
        reason=" ".join(m.group("reason").split())[:120]
        r=reason.casefold()
        category=("NON_INJURY_G_LEAGUE" if "g league" in r or "g-league" in r else
                  "INJURY_REASON_REPORTED" if any(x in r for x in
                  ("sprain","strain","injury","knee","ankle","hamstring",
                   "concussion","back","illness","foot","wrist","shoulder",
                   "hip","contusion","tendin")) else
                  "REASON_OTHER_OR_UNKNOWN")
        out.append(dict(
            player_name_text=name,
            reported_status=m.group("status").upper(),
            reported_reason_text=reason,
            reason_category=category,
            team_scope_text="Denver Nuggets",
            league="NBA",
            native_player_id=None,fixture_id=None,
            native_player_identity_verified=False,
            native_fixture_identity_verified=False,
            source_publication_time_verified=False,
            historical_prematch_eligibility=False,
            model_input=False,evidence_level="OFFICIAL_TEAM_REPORT_TEXT_CANDIDATE_ONLY"))
        if len(out)>=_MAX_CANDIDATES:break
    return out
