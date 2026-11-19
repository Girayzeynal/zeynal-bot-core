"""Captured public catalog replay and synthetic failures; no live price claim."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

from core.team_identity import digest
from hybrid_engine.adaptive_data import native_catalog
from hybrid_engine.nesine_catalog import inspect,NesineCatalog
from hybrid_engine.provider_bridge import ProviderBridge,render

ROOT=Path(__file__).resolve().parents[1]


class NesineCatalogTests(TestCase):
    def setUp(self):
        w=json.loads(gzip.decompress((ROOT/'docs/evidence/nesine-catalog-20261119.json.gz').read_bytes()))
        self.assertEqual(w['sha256'],digest(w['payload']));self.receipt=w['payload']['receipt']
        self.now=self.receipt['ingested_at_utc']
        clock=patch('time.time',side_effect=lambda:self.now);clock.start();self.addCleanup(clock.stop)
        # Locate the provider day containing the exact four official NBA events.
        packet=json.loads(gzip.decompress((ROOT/'docs/evidence/nba-provider-calendar-20261119.json.gz').read_bytes()))['payload']
        native=next(r for r in packet['receipts'] if any(e['id']=='401910019' for e in r['document']['events']))
        games=native_catalog(native,'NBA',2026)['payload']['fixtures'];self.snapshots=[]
        for g in games:
            event=next(e for e in native['document']['events'] if e['id'] in g['provider_fixture_ids'])
            teams={r['homeAway']:r['team'] for r in event['competitions'][0]['competitors']}
            self.snapshots.append(dict(league='NBA',season='2026/2027',fixture_id=g['canonical_id'],fixture_start_utc=g['start_ts_utc'],
                home=dict(provider_id=g['home_team_id'],official_name=teams['home']['displayName']),
                away=dict(provider_id=g['away_team_id'],official_name=teams['away']['displayName'])))

    def test_independent_official_catalogs_bind_four_games_but_not_prices_or_rules(self):
        self.assertEqual(len(self.snapshots),4)
        for snapshot in self.snapshots:
            r=inspect(self.receipt,snapshot,now=self.now)
            self.assertEqual(r['status'],'FIXTURE_MATCHED_PRICES_NOT_ADMITTED')
            self.assertFalse(r['prices_admitted']);self.assertFalse(r['rules_verified'])
            self.assertEqual(r['matched']['native_market_count'],0)

    def test_wrong_team_clock_hash_and_ambiguous_event_never_confirm_match(self):
        snapshot=self.snapshots[0]
        bad=deepcopy(snapshot);bad['away']['official_name']='Los Angeles Lakers'
        self.assertEqual(inspect(self.receipt,bad,now=self.now)['status'],'EXACT_FIXTURE_MATCH_REQUIRED')
        bad=dict(snapshot,fixture_start_utc=snapshot['fixture_start_utc']+60)
        self.assertEqual(inspect(self.receipt,bad,now=self.now)['status'],'EXACT_FIXTURE_MATCH_REQUIRED')
        r=deepcopy(self.receipt);r['document']['sc']=500
        with self.assertRaises(ValueError):inspect(r,snapshot,now=self.now)
        r=deepcopy(self.receipt);r['document']['d']['sg']['EAW']*=2;r['document_sha256']=digest(r['document'])
        self.assertEqual(inspect(r,snapshot,now=self.now)['status'],'EXACT_FIXTURE_MATCH_REQUIRED')

    def test_cached_read_after_start_never_queries_or_changes_original(self):
        snapshot=self.snapshots[0];before=digest(snapshot)
        getter=Mock(return_value=self.receipt)
        with TemporaryDirectory() as folder:
            reader=NesineCatalog(folder,getter)
            first=reader.review(snapshot);second=reader.review(snapshot)
            self.assertEqual(first,second);getter.assert_called_once()
            self.now=snapshot['fixture_start_utc']+1
            self.assertEqual(reader.review(snapshot)['status'],'POST_TIPOFF_NO_QUERY')
            getter.assert_called_once();self.assertEqual(before,digest(snapshot))

    def test_http_failure_is_visible_and_cached_instead_of_reported_as_no_edge(self):
        getter=Mock(return_value=dict(status='SOURCE_HTTP_ERROR',http_status=503))
        with TemporaryDirectory() as folder:
            reader=NesineCatalog(folder,getter)
            for _ in range(2):
                r=reader.review(self.snapshots[0]);self.assertEqual(r['http_status'],503)
                self.assertFalse(r['prices_admitted']);self.assertEqual(r['status'],'SOURCE_HTTP_ERROR')
            getter.assert_called_once()

    def test_provider_panel_reports_native_nesine_match_separately_without_paid_keys(self):
        access=SimpleNamespace(configuration=lambda:{k:'KEY_NOT_AVAILABLE_IN_TEST_PROCESS' for k in ('THE_ODDS_API','API_BASKETBALL')})
        with TemporaryDirectory() as folder:
            bridge=ProviderBridge(access,Path(folder)/'providers')
            getter=Mock(return_value=self.receipt)
            bridge.nesine=NesineCatalog(Path(folder)/'nesine',getter)
            snapshot=dict(self.snapshots[0],prediction_generated_at_utc=self.now-60)
            report=bridge.collect(snapshot);text=render(report)
            self.assertEqual(report['nesine']['status'],'FIXTURE_MATCHED_PRICES_NOT_ADMITTED')
            self.assertIn('Hedef bahis platformu: Nesine',text)
            self.assertIn(report['nesine']['matched']['provider_fixture_id'],text)
            self.assertIn('Nesine oranı ve ödeme kuralı henüz doğrulanmadı',text)
            self.assertTrue(all(r['status']=='KEY_NOT_AVAILABLE_IN_TEST_PROCESS' for r in report['providers'].values()))
            getter.assert_called_once()
