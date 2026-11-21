"""Exact official European city aliases; no fuzzy identity or historical writes."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import TeamIdentityRegistry,IdentityRefusal,digest
from providers.season_participants import parse_participants
from tests.test_team_identity import clubs,snapshot
from tests.test_season_archive_audit import NOW

ROOT=Path(__file__).resolve().parents[1]


class EuropeanCityAliasTests(TestCase):
    def test_real_tenerife_and_telekom_names_resolve_to_official_ids(self):
        path=ROOT/'docs/evidence/eurocup-city-alias-phase951-20261117.json.gz'
        w=json.loads(gzip.decompress(path.read_bytes()));self.assertEqual(digest(w['payload']),w['sha256'])
        p=w['payload'];self.assertFalse(p['new_forecast_generated'])
        b=parse_participants('EUROCUP',2026,p['documents']);registry=TeamIdentityRegistry()
        registry.ingest(b,trusted_sha256=b['sha256']);now=b['payload']['ingested_at_utc']
        for alias,expected in (('Tenerife','TNF'),('La Laguna Tenerife','TNF'),('LL Tenerife','TNF'),
                               ('Turk Telekom','TTK'),('Türk Telekom','TTK')):
            with self.subTest(alias=alias):
                team=registry.resolve('EUROCUP','2026/2027',alias,asof_utc=now)
                self.assertEqual(team.provider_ids,(('EUROLEAGUE_LIVE',expected),))
        self.assertTrue(any(a[1]=='SOURCE_CITY' and a[0]=='Tenerife' for a in
            registry.resolve('EUROCUP','2026/2027','Tenerife',asof_utc=now).aliases))

    def test_shared_city_is_ambiguous_instead_of_first_team_wins(self):
        rows=clubs();rows[0]['city']=rows[1]['city']='Shared City'
        with patch('time.time',return_value=NOW):
            b=snapshot('EUROLEAGUE',rows=rows);registry=TeamIdentityRegistry();registry.ingest(b,trusted_sha256=b['sha256'])
            with self.assertRaisesRegex(IdentityRefusal,'AMBIGUOUS_TEAM_ALIAS'):
                registry.resolve('EUROLEAGUE','2026/2027','Shared City',asof_utc=NOW)
            self.assertEqual(len(registry.refusals[-1]['candidates']),2)

    def test_city_collision_with_another_official_name_is_refused(self):
        rows=clubs();rows[0]['city']='Baskonia'
        with patch('time.time',return_value=NOW):
            b=snapshot(rows=rows);registry=TeamIdentityRegistry();registry.ingest(b,trusted_sha256=b['sha256'])
            with self.assertRaisesRegex(IdentityRefusal,'AMBIGUOUS_TEAM_ALIAS'):
                registry.resolve('EUROLEAGUE','2026/2027','Baskonia',asof_utc=NOW)

    def test_no_substrings_or_fuzzy_guessing_or_cross_league_leakage(self):
        with patch('time.time',return_value=NOW):
            b=snapshot();registry=TeamIdentityRegistry();registry.ingest(b,trusted_sha256=b['sha256'])
            for league,name in (('EUROLEAGUE','Pari'),('EUROLEAGUE','Belgrad'),('EUROCUP','Paris')):
                with self.subTest(league=league,name=name),self.assertRaises(IdentityRefusal):
                    registry.resolve(league,'2026/2027',name,asof_utc=NOW)

    def test_alias_observation_does_not_backdate_old_snapshot(self):
        rows=clubs();rows[0]['city']='New Source City'
        with patch('time.time',return_value=NOW):
            old=snapshot(at=NOW-20,rows=rows)
            for t in old['payload']['participants']:t['aliases']=[a for a in t['aliases'] if a['kind']!='SOURCE_CITY']
            old['sha256']=digest(old['payload']);before=deepcopy(old)
            new=snapshot(at=NOW,rows=rows);registry=TeamIdentityRegistry()
            for b in (old,new):registry.ingest(b,trusted_sha256=b['sha256'])
            with self.assertRaisesRegex(IdentityRefusal,'TEAM_ALIAS_NOT_REGISTERED'):
                registry.resolve('EUROLEAGUE','2026/2027','New Source City',asof_utc=NOW-1)
            self.assertEqual(registry.resolve('EUROLEAGUE','2026/2027','New Source City',asof_utc=NOW).provider_ids[0][1],'PRS')
            self.assertEqual(old,before)

    def test_nba_city_aliases_and_snapshot_identity_are_unchanged(self):
        from tests.test_team_identity import nba_names
        rows=nba_names();rows[0]['city']='Unregistered NBA City'
        with patch('time.time',return_value=NOW):
            b=snapshot('NBA',rows=rows);registry=TeamIdentityRegistry();registry.ingest(b,trusted_sha256=b['sha256'])
            self.assertFalse(any(a['kind']=='SOURCE_CITY' for t in b['payload']['participants'] for a in t['aliases']))
            with self.assertRaisesRegex(IdentityRefusal,'TEAM_ALIAS_NOT_REGISTERED'):
                registry.resolve('NBA','2026/2027','Unregistered NBA City',asof_utc=NOW)
            self.assertEqual(registry.resolve('NBA','2026/2027','SH',asof_utc=NOW).provider_ids[0][1],'1')

    def test_changed_native_city_requires_valid_source_digest(self):
        path=ROOT/'docs/evidence/eurocup-city-alias-phase951-20261117.json.gz'
        p=json.loads(gzip.decompress(path.read_bytes()))['payload']
        p['documents']['clubs']['document']['data'][0]['city']='Forged City'
        with self.assertRaisesRegex(ValueError,'PARTICIPANT_SOURCE_DIGEST_MISMATCH'):
            parse_participants('EUROCUP',2026,p['documents'])

    def test_native_short_command_reaches_time_guard_and_creates_no_forecast(self):
        import asyncio
        from universal_analysis import UniversalAnalyzeService
        path=ROOT/'docs/evidence/eurocup-city-time-phase951-20261117.json.gz';before=path.read_bytes()
        w=json.loads(gzip.decompress(before));p=w['payload'];self.assertEqual(w['sha256'],digest(p))
        self.assertFalse(p['new_forecast_generated']);self.assertFalse(p['actual_telegram_delivery_verified'])
        def offline(provider,url):
            receipt=p['documents'][url];self.assertEqual(receipt['provider'],provider)
            return deepcopy(receipt)
        # Clock replay validates the already observed public response; no new
        # historical PREMATCH prediction or ledger is generated by preflight.
        with patch('time.time',return_value=p['observed_at_utc']):
            r=asyncio.run(UniversalAnalyzeService(fetcher=offline).preflight('EUROCUP','2026-11-17','Turk Telekom','Tenerife'))
        self.assertEqual(r['stage'],'TIME');self.assertEqual(r['reason'],'FIXTURE_ALREADY_STARTED_OR_COMPLETED')
        self.assertEqual(r['home']['provider_id'],'TTK');self.assertEqual(r['away']['provider_id'],'TNF')
        self.assertEqual(r['prospective_records_created'],0);self.assertIsNone(r['prediction'])
        self.assertEqual(path.read_bytes(),before)
