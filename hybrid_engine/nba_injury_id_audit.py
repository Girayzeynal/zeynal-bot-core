"""Fail-closed fixture and player identity audit for NBA injury PDF rows.

No fuzzy matching, no invented player IDs and no automatic verification.
"""
from collections import Counter

def audit_injury_id_mapping(rows, *, fixture_matchup, team_ids, player_ids):
    if not isinstance(fixture_matchup,str) or not fixture_matchup.strip():
        raise ValueError('FIXTURE_MATCHUP_REQUIRED')
    if not isinstance(team_ids,dict) or not isinstance(player_ids,dict):
        raise ValueError('EXPLICIT_ID_MAPPINGS_REQUIRED')
    if not isinstance(rows,list):
        raise ValueError('ROWS_REQUIRED')
    expected={team_ids.get('home'),team_ids.get('away')}
    if len(expected)!=2 or any(not isinstance(x,str) or not x.strip() for x in expected):
        raise ValueError('FIXTURE_TEAM_IDS_REQUIRED')
    accepted=[]
    missing_team=[]
    missing_player=[]
    outside=0
    for row in rows:
        if not isinstance(row,dict) or row.get('matchup')!=fixture_matchup:
            outside+=1
            continue
        team_name=row.get('team')
        player_name=row.get('player_name')
        team_id=team_ids.get(team_name)
        if team_id not in expected:
            missing_team.append({'team':team_name,'player':player_name})
            continue
        player_id=player_ids.get((team_name,player_name))
        if not isinstance(player_id,str) or not player_id.strip():
            missing_player.append({'team':team_name,'player':player_name})
            continue
        accepted.append({'team_id':team_id,'player_id':player_id,'status':row.get('status')})
    duplicates=sum(count-1 for count in Counter(
        (row['team_id'],row['player_id']) for row in accepted).values() if count>1)
    return {'fixture_matchup':fixture_matchup,'fixture_rows':len(accepted)+len(missing_team)+len(missing_player),
            'mapped_rows':len(accepted),'missing_team_mapping':missing_team,
            'missing_player_mapping':missing_player,'other_fixture_rows':outside,
            'duplicate_player_rows':duplicates,
            'identity_mapping_complete':not missing_team and not missing_player and duplicates==0 and bool(accepted),
            'roster_verified':False,'telegram_delivery_verified':False}
