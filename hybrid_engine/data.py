"""Pinned, season-scoped historical features; target labels stay outside predictors."""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, pstdev

from core.team_identity import digest
from historical_research import historical_rows, reference_predict
from season_archive_collect import validate_collection
from hybrid_engine.availability import effective_time, effective_box_time

STRICT = "PIT_PROVEN_BACKTEST"
ASSUMED = "AVAILABILITY_ASSUMED_RESEARCH"
PERMISSION = "RESEARCH_AND_MODEL_TRAINING_VERIFIED"


class Abstain(ValueError):
    """An unavailable experiment is distinct from a failed invariant."""


def local_path(value):
    p = Path(value).absolute()
    if p == Path('/data') or Path('/data') in p.parents or p.resolve() != p:
        raise ValueError('ISOLATED_LOCAL_RESEARCH_PATH_REQUIRED')
    return p


def load_manifest(path):
    """No implicit downloads, production DBs, clock rewrites or unpinned inputs."""
    manifest = json.loads(local_path(path).read_text())
    if manifest.get('format') != 'HYBRID_DATASET_MANIFEST_V1':
        raise ValueError('DATASET_MANIFEST_REQUIRED')
    catalogs, boxes, pins, archive_items = [], {}, [], []
    for item in manifest['files']:
        p = local_path(item['path'])
        if p.stat().st_size > 128 * 1024 * 1024:
            raise ValueError('DATASET_FILE_TOO_LARGE')
        raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('DATASET_TRUSTED_PIN_MISMATCH')
        document = json.loads(raw)
        if item['kind'] == 'COLLECTION':
            if document.get('payload', {}).get('format') == 'HISTORICAL_SEASON_DISCOVERY_V1':
                p = document['payload']
                if (digest(p) != document['sha256'] or p.get('record_type') != 'HISTORICAL_DATA' or
                        p.get('prospective_predictions_created') != 0 or p.get('production_database_accessed') is not False):
                    raise ValueError('HISTORY_ARCHIVE_KIND_OR_PIN_INVALID')
                # historical_rows below replays and verifies every native catalog.
                if any(k != b['sha256'] for k, b in p['catalogs'].items()):
                    raise ValueError('HISTORY_CATALOG_INDEX_PIN_CONFLICT')
            else:
                validate_collection(document, trusted_sha256=document['sha256'])
            catalogs.extend(document['payload']['catalogs'].values())
        elif item['kind'] == 'CATALOG':
            catalogs.append(document)
        elif item['kind'] == 'BOX_STATISTICS':
            if document.get('format') != 'HYBRID_BOX_ARCHIVE_V1':
                raise ValueError('BOX_ARCHIVE_FORMAT_REQUIRED')
            for box in document['games']:
                key = (box['league'], box['fixture_id'])
                if key in boxes and boxes[key] != box:
                    raise ValueError('CONFLICTING_BOX_ARCHIVE')
                boxes[key] = box
        elif item['kind'] == 'PUBLIC_ARCHIVE_INPUTS':
            if document.get('format') != 'PUBLIC_ARCHIVE_INPUTS_V1': raise ValueError('PUBLIC_ARCHIVE_INPUT_FORMAT')
            archive_items.extend(document['sources'])
        else:
            raise ValueError('UNKNOWN_DATASET_FILE_KIND')
        pins.append(dict(kind=item['kind'], sha256=item['sha256']))
    cohort = historical_rows([(b, b['sha256']) for b in catalogs])
    for versions in cohort:
        for row in versions:
            box = boxes.get((row['league'], row['fixture_id']))
            if box:
                if (box['source_digest'] != digest(box['source']) or
                        box['season'] != row['season'] or
                        any(type(box['source'][k]) is not int for k in ('observed_at_utc', 'ingested_at_utc')) or
                        not row['fixture_start_utc'] < box['source']['observed_at_utc'] <= box['source']['ingested_at_utc'] or
                        [box['teams'][s]['points'] for s in ('home', 'away')] != row['final_scores'] or
                        box['home_team_id'] != row['home_team_id'] or box['away_team_id'] != row['away_team_id'] or
                        box['fixture_start_utc'] != row['fixture_start_utc']):
                    raise ValueError('BOX_IDENTITY_OR_SOURCE_CONFLICT')
                row['box'] = deepcopy(box)
                row['box_versions'] = [deepcopy(box)]
    knowledge = []
    for catalog in catalogs:
        payload = catalog['payload']
        for fixture in payload['fixtures']:
            knowledge.append(dict(league=fixture['league'], fixture_id=fixture['canonical_id'],
                season=f"{fixture['season_start_year']}/{fixture['season_start_year']+1}",
                fixture_start_utc=fixture['start_ts_utc'], home_team_id=fixture['home_team_id'],
                away_team_id=fixture['away_team_id'], provider=fixture['provider'],
                observed_at_utc=payload['observed_at_utc'], ingested_at_utc=payload['ingested_at_utc'],
                source_catalog_sha256=catalog['sha256']))
    provenance = dict(manifest_sha256=digest(manifest), source_pins=pins, fixture_knowledge=knowledge,
                        data_class=manifest.get('data_class', 'UNVERIFIED'),
                        source_permission=manifest.get('source_permission', 'NOT_ESTABLISHED'))
    if archive_items:
        from hybrid_engine.archive_sources import bind_archives
        names = {}
        for catalog in catalogs:
            p = catalog['payload']
            if p['provider'] != 'EUROLEAGUE_LIVE': continue
            for game in p['raw']['data']:
                for side in ('local','road'):
                    club = game[side]['club']; key = (p['league'], f"{p['season_start_year']}/{p['season_start_year']+1}", club['code'])
                    names[key] = [v for k,v in club.items() if k in ('name','abbreviatedName','editorialName') and isinstance(v,str)]
        cohort, provenance = bind_archives(cohort, provenance, archive_items, names)
    return cohort, provenance


def metadata(row):
    return {k: row[k] for k in ('league', 'season', 'fixture_id', 'fixture_start_utc',
                                'home_team_id', 'away_team_id')}


def regulation(row):
    p = row.get('periods')
    return None if p is None else [sum(p[s][:4]) for s in ('home', 'away')]


def available_at(row, mode):
    if mode == STRICT:
        return effective_time(row, 'CORE')
    if mode == ASSUMED:
        # This is an explicit research assumption, never an availability attestation.
        return row['fixture_start_utc'] + 86400
    raise ValueError('EXPLICIT_AVAILABILITY_POLICY_REQUIRED')


def prior_rows(cohort, target, mode=STRICT):
    cutoff = target['fixture_start_utc'] - 1
    result = []
    for versions in cohort:
        eligible = [r for r in versions if r['league'] == target['league'] and r['season'] == target['season']
                    and r['fixture_id'] != target['fixture_id'] and r['fixture_start_utc'] < cutoff
                    and regulation(r) is not None and available_at(r, mode) <= cutoff]
        if eligible:
            r = max(eligible, key=lambda x: (available_at(x, mode), x['source_catalog_sha256']))
            if not 0 < r['observed_at_utc'] <= r['ingested_at_utc']:
                raise ValueError('INVALID_SOURCE_CLOCK')
            result.append(r)
    # Identity deduplication and team/start conflicts have already been checked by historical_rows.
    return sorted(result, key=lambda r: (r['fixture_start_utc'], r['fixture_id']))


@dataclass(frozen=True)
class Cut:
    target: dict
    cutoff_utc: int
    evaluation_class: str
    history: tuple
    features: dict
    inputs_digest: str


def feature_cut(cohort, target, *, mode=STRICT, minimum=6, window=10):
    if type(minimum) is not int or type(window) is not int or not 1 <= minimum <= window <= 100:
        raise ValueError('INVALID_HISTORY_WINDOW')
    target = metadata(target)  # Deliberately discard labels, periods and current-game statistics.
    rows = prior_rows(cohort, target, mode)
    # League/opponent adjustments use more than each team's most recent games.
    # Trace ALL contributing history, not only the two recent-team subsets.
    features = {}
    pins = [dict(fixture_id=r['fixture_id'], catalog=r['source_catalog_sha256'],
        observed_at_utc=r['observed_at_utc'], ingested_at_utc=r['ingested_at_utc'],
        available_at_utc=available_at(r, mode), archive_evidence=r.get('archive_evidence'),
        regulation_scores=regulation(r)) for r in rows]
    league_mean = mean(sum(regulation(r)) / 2 for r in rows) if rows else None
    for side in ('home', 'away'):
        tid = target[side + '_team_id']
        recent = [r for r in rows if tid in (r['home_team_id'], r['away_team_id'])][-window:]
        if len(recent) < minimum:
            raise Abstain('INSUFFICIENT_PRE_CUTOFF_TEAM_HISTORY')
        pf, pa, qf, qa, adjusted, boxes = [], [], [], [], [], []
        for r in recent:
            own = 'home' if r['home_team_id'] == tid else 'away'
            other = 'away' if own == 'home' else 'home'
            qf.append(r['periods'][own][:4]); qa.append(r['periods'][other][:4])
            pf.append(sum(qf[-1])); pa.append(sum(qa[-1]))
            opponent = r[other + '_team_id']
            opponents = [v for v in rows if opponent in (v['home_team_id'], v['away_team_id'])][-window:]
            conceded = [regulation(v)[1 if v['home_team_id'] == opponent else 0] for v in opponents]
            adjusted.append(pf[-1] - mean(conceded) + league_mean)
            pins.append(dict(fixture_id=r['fixture_id'], catalog=r['source_catalog_sha256'],
                             observed_at_utc=r['observed_at_utc'], ingested_at_utc=r['ingested_at_utc']))
            candidates = r.get('box_versions', [r.get('box')])
            candidates = [b for b in candidates if b and (mode == ASSUMED or effective_box_time(b) <= target['fixture_start_utc']-1)
                and (not b.get('teams') or [b['teams'][s]['points'] for s in ('home','away')] == r['final_scores'])]
            box = max(candidates,key=lambda b:effective_box_time(b)) if candidates else None
            if box and len(r['periods']['home']) == len(r['periods']['away']) == 4:
                source = box['source']
                if mode == ASSUMED or effective_box_time(box) <= target['fixture_start_utc'] - 1:
                    boxes.append((r, box, own, other))
                    pins.append(dict(box_source=source, fixture_id=r['fixture_id'], available_at_utc=effective_box_time(box), archive_evidence=box.get('archive_evidence')))
        features[side] = dict(team_id=tid, n_games=len(recent), points_for=mean(pf), points_against=mean(pa),
                              points_for_std=pstdev(pf), points_against_std=pstdev(pa),
                              quarters_for=[mean(v[q] for v in qf) for q in range(4)],
                              quarters_against=[mean(v[q] for v in qa) for q in range(4)],
                              opponent_adjusted_for=mean(adjusted),
                              start_gap_hours=(target['fixture_start_utc']-recent[-1]['fixture_start_utc'])/3600,
                              start_gap_kind='START_TIME_GAP_PROXY_NOT_VERIFIED_REST', boxes=boxes,
                              recent_game_ids=[r['fixture_id'] for r in recent],
                              player_effect_status='NO_VERIFIED_PREMATCH_MINUTE_EXPOSURES')
    numeric = {side: {k: v for k, v in f.items() if k != 'boxes'} for side, f in features.items()}
    return Cut(target, target['fixture_start_utc']-1, mode, tuple(rows), features,
        digest(dict(target=target, mode=mode, sources=sorted(pins, key=digest), features=numeric)))


def reference(cut):
    """Reuse the existing score/period reference. V1 stochastic distribution is evaluated separately."""
    return reference_predict(cut.features)


def ml_vector(cut):
    values = []
    for side in ('home', 'away'):
        f = cut.features[side]
        values.extend(f[k] for k in ('points_for', 'points_against', 'points_for_std', 'points_against_std',
                                     'opponent_adjusted_for', 'start_gap_hours', 'n_games'))
        values.extend(f['quarters_for']); values.extend(f['quarters_against'])
    return values


def inventory(cohort):
    groups = {}
    for versions in cohort:
        r = versions[0]; key = r['league'] + ' ' + r['season']
        g = groups.setdefault(key, Counter())
        g['games'] += 1
        g['with_periods'] += regulation(r) is not None
        g['overtime_games'] += bool(r['periods'] and len(r['periods']['home']) > 4)
        g['with_box_statistics'] += bool(r.get('box'))
        g['with_player_box_statistics'] += bool(r.get('box') and r['box'].get('players'))
    return {k: dict(v) for k, v in sorted(groups.items())}
