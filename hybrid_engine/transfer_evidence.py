"""Time-bounded transfer and team-membership evidence; research-only.

A news report alone never confirms a transfer. Explicit effective dates and
source attribution are required before assigning a player to a team.
"""
from datetime import date

def roster_membership(events, *, player_id, as_of_date, known_at_utc):
    """Resolve one player at a historical game date using only evidence known at cutoff.

    Conflicting overlapping teams result in an abstention, not a guessed roster.
    """
    if not isinstance(player_id,str) or not player_id.strip():
        raise ValueError('PLAYER_ID_REQUIRED')
    if not isinstance(as_of_date,str):
        raise ValueError('GAME_DATE_REQUIRED')
    day=date.fromisoformat(as_of_date)
    if type(known_at_utc) is not int or known_at_utc<=0:
        raise ValueError('KNOWLEDGE_CUTOFF_REQUIRED')
    matches=[]
    rejected=0
    for e in events:
        if not isinstance(e,dict) or e.get('player_id')!=player_id:
            continue
        try:
            team=e['team_id']
            start=date.fromisoformat(e['effective_from'])
            end=date.fromisoformat(e['effective_until']) if e.get('effective_until') else None
            published=e['published_at_utc']
            url=e['source_url']
            if (not isinstance(team,str) or not team.strip() or
                type(published) is not int or not 0<published<=known_at_utc or
                not isinstance(url,str) or not url.startswith('https://') or
                (end is not None and end<=start)):
                raise ValueError('INVALID_MEMBERSHIP_EVIDENCE')
            if start<=day and (end is None or day<end):
                matches.append((team,url,published))
        except (KeyError,ValueError,TypeError):
            rejected+=1
    teams={team for team,_,_ in matches}
    if len(teams)>1:
        return dict(status='CONFLICTING_TEAM_MEMBERSHIP',team_id=None,
                    evidence_count=len(matches),rejected_count=rejected)
    if not teams:
        return dict(status='MEMBERSHIP_UNVERIFIED',team_id=None,
                    evidence_count=0,rejected_count=rejected)
    return dict(status='TIME_BOUNDED_MEMBERSHIP_EVIDENCE',team_id=next(iter(teams)),
                evidence_count=len(matches),rejected_count=rejected,
                roster_confirmed=False,eligible_to_play_verified=False,
                model_minutes_adjustment_allowed=False)
