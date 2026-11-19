"""Conservative adapter for externally parsed NBA official injury report rows.

No PDF parsing, player-ID guessing or inferred team identity occurs here.
Rows require explicit verified ID mapping supplied by a separate data pipeline.
"""
from hybrid_engine.roster_evidence import assess_roster_evidence

STATUS={'Out':'OUT','Doubtful':'DOUBTFUL','Questionable':'QUESTIONABLE',
        'Probable':'PROBABLE','Available':'AVAILABLE'}


def classify_official_absence(row):
    """Label report reason without treating every OUT as a medical injury.

    This classification is descriptive only; it does not verify identity,
    eligibility, lineup or playing-time impact.
    """
    reason=' '.join(str(row.get('reason') or '').split()).lower()
    status=row.get('status')
    if status not in STATUS:
        return 'UNRECOGNIZED_STATUS'
    if 'g league' in reason or 'gleague' in reason or 'two-way' in reason or 'onassignment' in reason or 'on assignment' in reason:
        return 'G_LEAGUE_OR_ASSIGNMENT'
    if 'injury' in reason or 'illness' in reason:
        return 'INJURY_OR_ILLNESS'
    if 'personal' in reason:
        return 'PERSONAL'
    if 'rest' in reason:
        return 'REST'
    return 'OTHER_OR_UNCLASSIFIED'

def map_official_injury_rows(rows, *, fixture_matchup, team_ids, player_ids,
                             report_reference, prediction_utc, fixture_start_utc):
    """Build fixture-scoped status evidence only after source extraction verification."""
    if (not isinstance(report_reference,dict) or
            report_reference.get('extraction_verified') is not True or
            report_reference.get('status')!='OFFICIAL_REPORT_CONTENT_VERIFIED'):
        return assess_roster_evidence([],prediction_utc=prediction_utc,
            fixture_start_utc=fixture_start_utc,
            home_team_id=team_ids['home'],away_team_id=team_ids['away'])
    mapped=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('matchup')!=fixture_matchup:
            continue
        team=team_ids.get(row.get('team'))
        player=player_ids.get((row.get('team'),row.get('player_name')))
        status=STATUS.get(row.get('status'))
        if team not in (team_ids['home'],team_ids['away']) or not player or not status:
            continue
        mapped.append(dict(team_id=team,player_id=player,status=status,
            published_at_utc=report_reference['report_timestamp_utc'],
            source_url=report_reference['source_url']))
    return assess_roster_evidence(mapped,prediction_utc=prediction_utc,
        fixture_start_utc=fixture_start_utc,
        home_team_id=team_ids['home'],away_team_id=team_ids['away'])
