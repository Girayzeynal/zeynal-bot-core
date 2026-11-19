"""Fixture-scoped verified roster evidence is display-only in isolated test bot.

No automatic report download, no mutation of frozen model or predictions.
"""
from hybrid_engine.roster_evidence import assess_roster_evidence

def read_fixture_roster_evidence(store, *, fixture_id, prediction_utc,
                                 fixture_start_utc, home_team_id, away_team_id):
    """Load only explicitly fixture-bound records from a trusted in-memory store."""
    empty=lambda:assess_roster_evidence([],prediction_utc=prediction_utc,
        fixture_start_utc=fixture_start_utc,home_team_id=home_team_id,
        away_team_id=away_team_id)
    if not isinstance(store,dict):
        return empty()
    packet=store.get(str(fixture_id))
    if not isinstance(packet,dict) or packet.get('verified') is not True:
        return empty()
    if (packet.get('fixture_id')!=str(fixture_id) or
            packet.get('prediction_utc')!=prediction_utc or
            packet.get('fixture_start_utc')!=fixture_start_utc or
            packet.get('home_team_id')!=home_team_id or
            packet.get('away_team_id')!=away_team_id):
        return empty()
    records=packet.get('records')
    if not isinstance(records,list):
        return empty()
    return assess_roster_evidence(records,prediction_utc=prediction_utc,
        fixture_start_utc=fixture_start_utc,home_team_id=home_team_id,
        away_team_id=away_team_id)
