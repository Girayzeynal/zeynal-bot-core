"""Request-scoped reuse of verified European source assets and season catalogs."""
from collections import OrderedDict
from copy import copy
import json
from pathlib import Path

from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.europe_live import EuropeanRegistry, EuropeanService
from hybrid_engine.europe_models import catalog
from hybrid_engine.live_euroleague import names

_MAX_CACHED_BYTES = 4 * 1024 * 1024
_MAX_CACHED_ASSETS = 32
_MAX_CATALOGS = 3


def _signature(path):
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


class EuropeanReportAssets:
    """Use the existing publication scan, with no cache shared between reports."""

    def __init__(self, registry):
        self.registry = copy(registry)
        self._verify_asset = registry.read_asset
        self.registry.read_asset = self.read_asset
        self._assets = OrderedDict()
        self._catalogs = OrderedDict()
        self._cached_bytes = 0

    def read_asset(self, ref):
        filename = ref['file']
        if Path(filename).name != filename:
            raise ValueError('FORWARD_ASSET_PATH')
        path = local_path(self.registry.root / filename)
        signature = _signature(path)
        key = (filename, ref['sha256'], signature)
        if key in self._assets:
            self._assets.move_to_end(key)
            return self._assets[key]
        value = self._verify_asset(ref)
        if _signature(path) != signature:
            raise ValueError('EUROPE_REPORT_ASSET_CHANGED_DURING_READ')
        size = signature[2]
        if size <= _MAX_CACHED_BYTES:
            while self._assets and (self._cached_bytes + size > _MAX_CACHED_BYTES
                                    or len(self._assets) >= _MAX_CACHED_ASSETS):
                old, _ = self._assets.popitem(last=False)
                self._cached_bytes -= old[2][2]
            self._assets[key] = value
            self._cached_bytes += size
        return value

    def source_index(self, ref, year, *, include_names=False):
        receipt = self.read_asset(ref)
        key = (ref['sha256'], year)
        if key in self._catalogs:
            fixtures, labels = self._catalogs[key]
            self._catalogs.move_to_end(key)
        else:
            bundle = catalog(receipt, self.registry.league, year, max_age=None)
            fixtures, labels = {}, None
            for game in bundle['payload']['fixtures']:
                fixtures.setdefault(game['canonical_id'], []).append(game)
        if include_names and labels is None:
            labels = names(receipt['document'])
        self._catalogs[key] = (fixtures, labels)
        if len(self._catalogs) > _MAX_CATALOGS:
            self._catalogs.popitem(last=False)
        return receipt, (fixtures, labels)

    def pair(self, payload):
        fixture = payload['fixture']
        _, (fixtures, labels) = self.source_index(payload['fixture_source'], fixture['season_start_year'], include_names=True)
        if fixtures.get(fixture['canonical_id'], []).count(fixture) != 1:
            raise ValueError('EUROPE_ARCHIVED_FIXTURE_PIN')
        return labels[fixture['provider_fixture_ids'][0]]

    def outcome(self, payload):
        fixture = payload['fixture']
        fixture_id = fixture['canonical_id']
        forecast_sha = digest(payload)
        found, label_clock = None, None
        for path in sorted(self.registry.root.glob('outcome-' + fixture_id + '-*.json')):
            wrapper = json.loads(local_path(path).read_text())
            outcome = wrapper['payload']
            pin = wrapper['sha256']
            if digest(outcome) != pin or path.stem != 'outcome-' + fixture_id + '-' + pin:
                raise ValueError('EUROPE_OUTCOME_PIN')
            if outcome['forecast_sha256'] != forecast_sha:
                continue
            receipt, (fixtures, _) = self.source_index(outcome['source'], fixture['season_start_year'])
            matches = [row for row in fixtures.get(fixture_id, []) if row['completed'] and row['periods']]
            if len(matches) != 1:
                raise ValueError('EUROPE_OFFICIAL_FINAL_REQUIRED')
            final = matches[0]
            keys = ('start_ts_utc', 'home_team_id', 'away_team_id', 'provider_fixture_ids')
            if (any(final[key] != fixture[key] for key in keys)
                    or receipt['observed_at_utc'] <= fixture['start_ts_utc']
                    or outcome['periods'] != final['periods'] or outcome['full_final'] != final['final_scores']):
                raise ValueError('EUROPE_FINAL_IDENTITY_SCORE_OR_CLOCK')
            if found is not None and found != outcome:
                raise ValueError('EUROPE_CONFLICTING_FINALS_REQUIRE_REVIEW')
            found, label_clock = outcome, receipt['ingested_at_utc']
        return found, label_clock


def reporting_assets(service):
    """Legacy registries/adapters keep their own native verification policy."""
    if (isinstance(service.registry, EuropeanRegistry)
            and getattr(service.pair, '__func__', None) is EuropeanService.pair
            and getattr(service.registry.outcome, '__func__', None) is EuropeanRegistry.outcome):
        return EuropeanReportAssets(service.registry)
    return None
