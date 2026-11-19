"""Exact API-Basketball season catalog selection; never fall back to old years."""
import re
from datetime import datetime,timezone


def select_season(league,snapshot):
    wanted=snapshot.get('season','');m=re.fullmatch(r'(20[0-9]{2})/(20[0-9]{2})',wanted)
    if m is None or int(m[2])!=int(m[1])+1:raise ValueError('EXPLICIT_CONSECUTIVE_SEASON_REQUIRED')
    day=datetime.fromtimestamp(snapshot['fixture_start_utc'],timezone.utc).date()
    if not int(m[1])<=day.year<=int(m[2]):raise ValueError('FIXTURE_SEASON_YEAR_CONFLICT')
    source=league.get('seasons')
    result=dict(status='SEASON_CATALOG_MISSING',requested_season=wanted,available_seasons=[],season_value=None,
                policy='EXACT_DECLARED_VALUE_NO_OLD_SEASON_FALLBACK')
    if not isinstance(source,list):return result
    if len(source)>128:return dict(result,status='SEASON_CATALOG_BUDGET')
    available=set();candidates=set()
    for row in source:
        if not isinstance(row,dict):continue
        value=row.get('season')
        if isinstance(value,bool) or type(value) not in (str,int):continue
        token=str(value)
        if re.fullmatch(r'20[0-9]{2}(?:[-/]20[0-9]{2})?',token) is None:continue
        available.add(token);bounds=None
        if row.get('start') is not None or row.get('end') is not None:
            try:
                start=datetime.strptime(row['start'],'%Y-%m-%d').date()
                end=datetime.strptime(row['end'],'%Y-%m-%d').date()
            except (KeyError,ValueError,TypeError):continue
            if not start<=day<=end or start.year!=int(m[1]) or end.year!=int(m[2]):continue
            bounds=(row['start'],row['end'])
        exact=token.replace('-','/')==wanted
        # Numeric season labels have no universal year convention; explicit
        # source dates must bind them to the requested two-year season.
        if exact or (token in (m[1],m[2]) and bounds is not None):candidates.add((token,bounds))
    result['available_seasons']=sorted(available)[-16:]
    if len(candidates)==1:
        token,bounds=next(iter(candidates))
        return dict(result,status='VERIFIED_PROVIDER_SEASON',season_value=token,season_dates=bounds)
    return dict(result,status='AMBIGUOUS_PROVIDER_SEASON' if candidates else 'REQUESTED_SEASON_NOT_LISTED')
