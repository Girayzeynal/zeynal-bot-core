"""Legacy lookup facade backed by the explicit season registry.

No embedded two-team fallback. Existing ledger IDs are never rewritten and
provider crosswalks require evidence rather than a similar name.
"""
from types import MappingProxyType
from core.team_identity import TeamIdentityRegistry

NBA_TEAMS=MappingProxyType({})  # compatibility import, not a participant list


def get_nba_team(canonical_team_id, *, registry=None, season=None, asof_utc=None):
    if registry is None or season is None or asof_utc is None: return None
    found=[t for t in registry.participants('NBA',season,asof_utc=asof_utc) if t.internal_id==canonical_team_id]
    if len(found)!=1:return None
    team=found[0]
    abbreviation=next((name for name,kind,language,start,end in team.aliases if kind=='SOURCE_abbreviation'),None)
    return dict(internal_id=team.internal_id,name=team.official_name,abbr=abbreviation,
        providers={p.lower():dict(team_id=pid,abbr=abbreviation.lower() if abbreviation else None) for p,pid in team.provider_ids})
