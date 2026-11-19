"""Conservative Turkish official-club injury absence sentence candidate detector.

This is an *untrusted text extraction stage*, not lineup evidence. It makes
no assumptions that player identity, fixture binding, timezone of publication,
or historical pre-tipoff availability has been verified. Explicit narrow
wording and a single source club pilot are required.
"""
import re
import unicodedata

MAX_VISIBLE_TEXT=8192
MAX_SENTENCE=300
MAX_CANDIDATES=4

# One known official TOFAŞ writing construction; do not infer future-time
# statements or translate vague "injured" into "will not play".
_ABSENCE=re.compile(
    r"sakatlıkları\s+bulunan\s+([A-Za-zÇĞİÖŞÜçğıöşü'’\-\s,]{8,130}?)\s+"
    r"bu\s+karşılaşmada\s+forma\s+giyemeyecek\b",
    re.IGNORECASE|re.UNICODE)
_PERSON=re.compile(
    r"[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü'’\-]{1,31}"
    r"(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü'’\-]{1,31}){1,3}$",
    re.UNICODE)


def injury_absence_candidates(visible_text, *, club_key):
    """Only return named textual candidates; no forecast or roster effect."""
    if club_key!="eurocup_tofas":return []
    if not isinstance(visible_text,str) or len(visible_text)>MAX_VISIBLE_TEXT:
        raise ValueError("OFFICIAL_ARTICLE_TEXT_BUDGET")
    clean=unicodedata.normalize("NFC"," ".join(visible_text.split()))
    found=[];seen=set()
    # Limit extraction to clear language within the *same* sentence, not
    # disconnected site menu/navigation or a retrospective score report.
    for sentence in re.split(r"(?<=[.!?])\s+",clean):
        if len(sentence)>MAX_SENTENCE:continue
        for m in _ABSENCE.finditer(sentence):
            names=re.split(r"\s+(?:ile|ve)\s+|\s*,\s*",m.group(1),flags=re.IGNORECASE)
            if len(names)<1 or len(names)>MAX_CANDIDATES:continue
            if not all(_PERSON.fullmatch(x.strip()) for x in names):
                continue
            for text in names:
                name=" ".join(text.split())
                if name.casefold() in seen:continue
                seen.add(name.casefold())
                found.append(dict(
                    player_name_text=name,
                    reported_status="CLUB_STATES_UNAVAILABLE_FOR_THIS_MATCH",
                    reported_reason="INJURY_IN_SOURCE_SENTENCE",
                    native_player_id=None,fixture_id=None,
                    native_player_identity_verified=False,
                    native_fixture_identity_verified=False,
                    source_publication_time_verified=False,
                    historical_prematch_eligibility=False,
                    model_input=False,
                    evidence_level="EXPLICIT_TEXT_CANDIDATE_ONLY"))
                if len(found)==MAX_CANDIDATES:return found
    return found
