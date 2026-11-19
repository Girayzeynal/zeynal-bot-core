"""Conservative, read-only NBA availability evidence gate.

No player status is inferred from missing data. This module never changes the
frozen prediction or its prepared model/source pin.
"""
from datetime import datetime, timezone

ALLOWED = frozenset({'OUT', 'DOUBTFUL', 'QUESTIONABLE', 'PROBABLE', 'AVAILABLE'})
CONFIRMED = frozenset({'OUT', 'AVAILABLE'})


def assess_roster_evidence(records, *, prediction_utc, fixture_start_utc, home_team_id=None, away_team_id=None):
    """Accept only pre-prediction, pre-tipoff, source-attributed status records.

    A status is not a confirmed starter or a minutes projection.
    Conflicting statuses for the same player are withheld.
    """
    if type(prediction_utc) is not int or type(fixture_start_utc) is not int or not 0 < prediction_utc < fixture_start_utc:
        raise ValueError('INVALID_PREMATCH_CUTOFF')
    if (home_team_id is None) != (away_team_id is None):
        raise ValueError('BOTH_FIXTURE_TEAMS_REQUIRED')
    if home_team_id is not None and (not isinstance(home_team_id, str) or not isinstance(away_team_id, str) or not home_team_id.strip() or not away_team_id.strip() or home_team_id == away_team_id):
        raise ValueError('INVALID_FIXTURE_TEAM_IDENTITIES')
    accepted = {}
    conflicts = set()
    rejected = 0
    for record in records:
        if not isinstance(record, dict):
            rejected += 1
            continue
        player = record.get('player_id')
        team = record.get('team_id')
        status = record.get('status')
        published = record.get('published_at_utc')
        source = record.get('source_url')
        if (home_team_id is not None and team not in (home_team_id, away_team_id)):
            rejected += 1
            continue
        if (not isinstance(player, str) or not player.strip() or
                not isinstance(team, str) or not team.strip() or
                status not in ALLOWED or type(published) is not int or
                not 0 < published <= prediction_utc or published >= fixture_start_utc or
                not isinstance(source, str) or not source.startswith('https://')):
            rejected += 1
            continue
        key = (team, player)
        if key in conflicts:
            continue
        prior = accepted.get(key)
        if prior and prior['status'] != status:
            conflicts.add(key)
            accepted.pop(key, None)
            continue
        if prior is None or published > prior['published_at_utc']:
            accepted[key] = dict(team_id=team, player_id=player, status=status,
                                 published_at_utc=published, source_url=source)
    return dict(status='PARTIAL_EVIDENCE_NOT_LINEUP_VERIFIED',
                records=sorted(accepted.values(), key=lambda x:(x['team_id'], x['player_id'])),
                rejected_count=rejected, conflict_count=len(conflicts),
                confirmed_starters=[], rotation_verified=False,
                minutes_adjustment_allowed=False)
