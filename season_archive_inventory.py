"""Offline, pinned 2026/27 regular-season source census, never model training.

Native source documents are replayed. A catalog is a retrospective research
observation, not proof that features existed before any historical tipoff.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import time

from providers.espn_completed_event import parse_completed_nba_event


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _count(value):
    _require(type(value) is int and 0 <= value <= 500, 'invalid_score')
    return value


def _utc(value):
    _require(type(value) is str, 'explicit_utc_required')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _require(date.tzinfo is not None and date.utcoffset().total_seconds() == 0, 'explicit_utc_required')
    return int(date.timestamp())


def _periods(home, away, scores):
    if home is None and away is None:
        return None
    _require(type(home) is list and type(away) is list and 4 <= len(home) == len(away) <= 12,
             'invalid_periods')
    for values, score in zip((home, away), scores):
        _require(sum(_count(v) for v in values) == score, 'period_score_conflict')
    for n in range(4, len(home)):
        _require(sum(home[:n]) == sum(away[:n]), 'overtime_without_preceding_tie')
    return {'home': home, 'away': away}


def _nba(event, year, observed):
    _require(event['season']['year'] == year+1 and type(event['season']['year']) is int and
             type(event['season']['type']) is int and event['season']['type'] == 2, 'nba_regular_season_identity_required')
    pid = event['id']
    _require(type(pid) is str and re.fullmatch(r'[0-9]+', pid), 'provider_id_required')
    _require(len(event['competitions']) == 1, 'single_competition_required')
    comp = event['competitions'][0]
    _require(comp.get('id', pid) == pid, 'provider_id_conflict')
    start = _utc(event['date'])
    if 'date' in comp:
        _require(_utc(comp['date']) == start, 'fixture_start_conflict')
    sides = {t['homeAway']: t for t in comp['competitors']}
    _require(len(comp['competitors']) == 2 and set(sides) == {'home', 'away'}, 'two_teams_required')
    ids = [sides[s]['team']['id'] for s in ('home', 'away')]
    _require(all(type(v) is str and re.fullmatch(r'[0-9]+', v) for v in ids) and ids[0] != ids[1], 'team_identity_required')
    status = comp['status']['type']
    if 'status' in event:
        _require(all(event['status']['type'].get(k) == status.get(k) for k in ('state', 'completed')), 'contradictory_final_status')
    final = status['completed'] is True
    if final:
        _require(status.get('name') in ('STATUS_FINAL', 'STATUS_FINAL_OT'), 'explicit_nba_final_required')
        result = parse_completed_nba_event(event, datetime.fromtimestamp(observed, timezone.utc))
        _require(result is not None, 'unverified_nba_final')
        scores = [result['actual_home'], result['actual_away']]
        for score in scores:
            _count(score)
        raw_parts = [sides[s].get('linescores') for s in ('home', 'away')]
        values = None if all(v is None for v in raw_parts) else [
            [int(v['value']) if type(v['value']) in (int, float) and v['value'] == int(v['value']) else v['value'] for v in rows]
            for rows in raw_parts]
        if values is not None:
            for source, parsed in zip(raw_parts, values):
                for item, value in zip(source, parsed):
                    _require('displayValue' not in item or str(item['displayValue']) == str(value), 'contradictory_period_score')
        parts = _periods(None, None, scores) if values is None else _periods(*values, scores)
    else:
        _require(status['completed'] is False and status['state'] in ('pre', 'in'), 'unverified_game_status')
        scores = None
        parts = None
    return pid, start, ids, final, scores, parts


def _euro(game, year, observed, competition='E'):
    season = game['season']
    _require(season['code'] == f'{competition}{year}' and season['competitionCode'] == competition and
             type(season['year']) is int and season['year'] == year and
             season['alias'] == f'{year}-{str(year+1)[-2:]}', 'euroleague_season_identity_required')
    _require(game['phaseType']['code'] == 'RS', 'regular_season_required')
    number = game['gameCode']
    _require(type(number) is int and number > 0 and game['identifier'] == f'{competition}{year}_{number}', 'provider_id_conflict')
    _require(game['confirmedDate'] is True and game['confirmedHour'] is True and game['gameStatus'] == 'Confirmed', 'confirmed_fixture_required')
    start = _utc(game['utcDate'])
    ids = [game[s]['club']['code'] for s in ('local', 'road')]
    _require(all(type(v) is str and re.fullmatch(r'[A-Z0-9]{1,8}', v) for v in ids) and ids[0] != ids[1], 'team_identity_required')
    _require(all(game[s]['club']['isVirtual'] is False for s in ('local', 'road')), 'virtual_team_refused')
    _require(type(game['played']) is bool, 'explicit_played_status_required')
    final = game['played']
    scores = parts = None
    if final:
        _require(start < observed, 'future_final_refused')
        scores = [_count(game[s]['score']) for s in ('local', 'road')]
        _require(scores[0] != scores[1], 'tied_final_refused')
        values = []
        for side in ('local', 'road'):
            p = game[side].get('partials')
            if p is None:
                values.append(None)
                continue
            extra = p['extraPeriods']
            _require(type(extra) is dict and set(extra) == {str(i+1) for i in range(len(extra))}, 'invalid_overtime_periods')
            values.append([p[f'partials{i}'] for i in range(1, 5)] + [extra[str(i+1)] for i in range(len(extra))])
        parts = _periods(*values, scores)
    return game['identifier'], start, ids, final, scores, parts


def archive_catalog(raw, *, provider, observed_at_utc, ingested_at_utc, season_start_year=2026, competition_code=None, regular_season_filter=False):
    """Validate one native document; never claim full-season or source permission."""
    try:
        _require(provider in ('ESPN', 'EUROLEAGUE_LIVE'), 'unsupported_archive_provider')
        _require(competition_code in (None,'E','U') and (provider!='ESPN' or competition_code is None), 'unsupported_archive_competition')
        _require(type(regular_season_filter) is bool, 'invalid_regular_season_filter')
        _require(type(season_start_year) is int and 2000 <= season_start_year <= 2100, 'invalid_season')
        _require(type(observed_at_utc) is int and type(ingested_at_utc) is int and
                 0 < observed_at_utc <= ingested_at_utc <= int(time.time()), 'invalid_source_clocks')
        raw = deepcopy(raw)
        rows = raw['events'] if provider == 'ESPN' else raw['data']
        _require(type(rows) is list and len(rows) <= 5000, 'bounded_catalog_required')
        if provider == 'EUROLEAGUE_LIVE':
            _require(type(raw['total']) is int and raw['total'] == len(rows), 'incomplete_catalog_page')
        league = 'NBA' if provider == 'ESPN' else 'EuroCup' if competition_code=='U' else 'EuroLeague'
        fixtures, aliases, slots = {}, {}, {}; excluded=[]
        for row in rows:
            if regular_season_filter and provider=='ESPN':
                _require(type(row['season']['year']) is int and row['season']['year']==season_start_year+1 and
                    type(row['season']['type']) is int and row['season']['type'] in (1,2,3), 'nba_season_phase_identity_required')
                if row['season']['type']!=2:
                    _require(type(row['id']) is str and re.fullmatch(r'[0-9]+',row['id']), 'provider_id_required')
                    excluded.append(row['id']);continue
            elif regular_season_filter:
                season=row['season'];code=competition_code or 'E';phase=row['phaseType']['code']
                _require(season['code']==f'{code}{season_start_year}' and season['competitionCode']==code and
                    type(season['year']) is int and season['year']==season_start_year, 'euroleague_season_identity_required')
                phases = ('RS','8F','4F','2F','Final') if code=='U' else ('RS','PI','PO','FF')
                _require(phase in phases, 'unknown_euroleague_season_phase')
                if phase!='RS':
                    _require(type(row['gameCode']) is int and row['gameCode']>0 and
                        row['identifier']==f"{code}{season_start_year}_{row['gameCode']}", 'provider_id_conflict')
                    excluded.append(row['identifier']);continue
            pid, start, ids, final, scores, parts = _nba(row,season_start_year,observed_at_utc) if provider=='ESPN' else _euro(row,season_start_year,observed_at_utc,competition_code or 'E')
            _require(int(datetime(season_start_year, 7, 1, tzinfo=timezone.utc).timestamp()) <= start <
                     int(datetime(season_start_year+1, 7, 1, tzinfo=timezone.utc).timestamp()), 'fixture_outside_season_years')
            identity = dict(provider=provider, league=league, season_start_year=season_start_year,
                            start_ts_utc=start, home_team_id=ids[0], away_team_id=ids[1])
            cid = _hash(identity)
            game = dict(identity, canonical_id=cid, completed=final, final_scores=scores, periods=parts)
            _require(pid not in aliases or aliases[pid] == cid, 'provider_id_conflict')
            aliases[pid] = cid
            for team in ids:
                key = (team, start)
                _require(key not in slots or slots[key] == cid, 'same_team_start_conflict')
                slots[key] = cid
            if cid in fixtures:
                _require({k: v for k, v in fixtures[cid].items() if k != 'provider_fixture_ids'} == game, 'conflicting_fixture_results')
                fixtures[cid]['provider_fixture_ids'] = sorted(set(fixtures[cid]['provider_fixture_ids'] + [pid]))
            else:
                fixtures[cid] = dict(game, provider_fixture_ids=[pid])
        games = [fixtures[k] for k in sorted(fixtures)]
        payload = dict(format='RESEARCH_SEASON_CATALOG_V1', provider=provider, league=league,
            season_start_year=season_start_year, observed_at_utc=observed_at_utc, ingested_at_utc=ingested_at_utc,
            usage='RETROSPECTIVE_RESEARCH', raw=raw, raw_sha256=_hash(raw), fixtures=games,
            raw_records=len(rows), independent_fixtures=len(games),
            completed_fixtures=sum(g['completed'] for g in games),
            completed_with_periods=sum(g['completed'] and g['periods'] is not None for g in games),
            season_archive_complete=False, completeness_reason='independent_expected_season_universe_not_verified',
            source_permission='NOT_ESTABLISHED', source_attestation='PINNED_LOCAL_BYTES_NOT_INDEPENDENT_ATTESTATION',
            player_statistics='NOT_COLLECTED', point_in_time_training_eligible=False,
            prospective_predictions_created=0)
        if competition_code is not None: payload['competition_code']=competition_code
        if regular_season_filter:
            payload.update(regular_season_filter=True,excluded_non_regular_ids=sorted(set(excluded)))
        return {'payload': payload, 'sha256': _hash(payload)}
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError('malformed_archive_source') from exc


def validate_catalog(bundle, *, trusted_sha256):
    try:
        _require(type(bundle) is dict and set(bundle) == {'payload', 'sha256'} and
                 bundle['sha256'] == trusted_sha256 == _hash(bundle['payload']), 'trusted_archive_pin_mismatch')
        p = bundle['payload']
        rebuilt = archive_catalog(p['raw'],competition_code=p.get('competition_code'),regular_season_filter=p.get('regular_season_filter',False), **{k: p[k] for k in ('provider', 'observed_at_utc', 'ingested_at_utc', 'season_start_year')})
        _require(rebuilt == bundle, 'archive_cannot_replay')
        return rebuilt['payload']
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('malformed_archive_catalog') from exc
