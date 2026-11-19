"""Native identity evidence + synthetic games; no external Telegram delivery."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import patch

from core.team_identity import TeamIdentityRegistry, IdentityRefusal, digest
from hybrid_engine.europe_command_identity import EuropeanCommandRegistry, EuropeanCommandService
from hybrid_engine.europe_premium_ui import present, projection, VERSION
from hybrid_engine.europe_models import prepare, season_url
from providers.season_participants import parse_participants
from tests.test_europe_integration import Source
from tests.test_team_identity import documents, snapshot
from tests.test_season_archive_audit import NOW

ROOT=Path(__file__).resolve().parents[1]


def evidence():
    w=json.loads(gzip.decompress((ROOT/'docs/evidence/eurocup-city-alias-phase951-20261117.json.gz').read_bytes()))
    assert digest(w['payload'])==w['sha256']
    return w['payload']['documents']


PAIRS=(('Derthona Basket','Rigas Zelli','TRT','RIG'),
       ('Frankfurt Skyliners','Reyer Venezia','FRA','VNC'),
       ('JL Bourg','Napoli Basket','BOU','NAP'))


class CurrentAliasTests(TestCase):
    def setUp(self):
        self.docs=evidence();self.bundle=parse_participants('EUROCUP',2026,self.docs)
        self.now=self.bundle['payload']['ingested_at_utc']+1
        timer=patch('time.time',return_value=self.now);timer.start();self.addCleanup(timer.stop)
        self.registry=EuropeanCommandRegistry()
        self.registry.ingest(self.bundle,trusted_sha256=self.bundle['sha256'])

    def test_all_reported_variants_bind_to_native_season_members_without_mutation(self):
        before=deepcopy(self.bundle)
        for h,a,hid,aid in PAIRS:
            for alias,pid in ((h,hid),(a,aid)):
                with self.subTest(alias=alias):
                    team=self.registry.resolve('EuroCup','2026/2027',alias,asof_utc=self.now)
                    self.assertEqual(team.provider_ids,(('EUROLEAGUE_LIVE',pid),))
        self.assertEqual(self.bundle,before)
        self.assertEqual(self.registry.refusals,())

    def test_reproduces_old_resolver_failures(self):
        old=TeamIdentityRegistry();old.ingest(self.bundle,trusted_sha256=self.bundle['sha256'])
        for alias in ('Derthona Basket','Rigas Zelli','Frankfurt Skyliners','Reyer Venezia','Napoli Basket'):
            with self.subTest(alias=alias),self.assertRaisesRegex(IdentityRefusal,'TEAM_ALIAS_NOT_REGISTERED'):
                old.resolve('EUROCUP','2026/2027',alias,asof_utc=self.now)
        self.assertEqual(old.resolve('EUROCUP','2026/2027','JL Bourg',asof_utc=self.now).provider_ids[0][1],'BOU')

    def test_new_alias_is_not_backdated_or_leaked_to_other_leagues_seasons(self):
        for league,season,clock,name in (
                ('EUROCUP','2026/2027',self.now-1,'Napoli Basket'),
                ('EUROLEAGUE','2026/2027',self.now,'Napoli Basket'),
                ('EUROCUP','2025/2026',self.now,'Napoli Basket'),
                ('EUROCUP','2026/2027',self.now,'Napol Basket')):
            with self.subTest(league=league,season=season,clock=clock),self.assertRaises(IdentityRefusal):
                self.registry.resolve(league,season,name,asof_utc=clock)

    def test_native_alias_collision_cannot_override_another_club(self):
        b=deepcopy(self.bundle)
        target=next(t for t in b['payload']['participants'] if t['provider_id']=='RIG')
        target['aliases'].append(dict(name='Napoli Basket',kind='TEST_COLLISION',language='und',
            valid_from_utc=self.now,valid_until_utc=None))
        b['payload']['ingested_at_utc']=self.now;b['sha256']=digest(b['payload'])
        self.registry.ingest(b,trusted_sha256=b['sha256'])
        with self.assertRaisesRegex(IdentityRefusal,'AMBIGUOUS_TEAM_ALIAS'):
            self.registry.resolve('EUROCUP','2026/2027','Napoli Basket',asof_utc=self.now)

    def test_wrong_native_code_or_name_anchor_is_not_accepted(self):
        for change in ('code','name'):
            docs=deepcopy(self.docs);rows=docs['clubs']['document']['data']
            row=next(r for r in rows if r['code']=='NAP')
            if change=='code':row['code']='OTHER'
            else:
                for key in ('name','abbreviatedName','editorialName','clubPermanentName','clubPermanentAlias','sponsor'):
                    row[key]='Unrelated Club'
            docs['clubs']['document_sha256']=digest(docs['clubs']['document'])
            b=parse_participants('EUROCUP',2026,docs);registry=EuropeanCommandRegistry()
            registry.ingest(b,trusted_sha256=b['sha256'])
            with self.subTest(change=change),self.assertRaisesRegex(IdentityRefusal,'TEAM_ALIAS_NOT_REGISTERED'):
                registry.resolve('EUROCUP','2026/2027','Napoli Basket',asof_utc=self.now)

    def test_nba_remains_exact_native_identity(self):
        b=snapshot('NBA',at=self.now)
        self.registry.ingest(b,trusted_sha256=b['sha256'])
        self.assertEqual(self.registry.resolve('NBA','2026/2027','SH',asof_utc=self.now).provider_ids[0][1],'1')
        with self.assertRaises(IdentityRefusal):self.registry.resolve('NBA','2026/2027','Napoli Basket',asof_utc=self.now)


class NativeNamedSyntheticSource(Source):
    """Real club labels/IDs, invented games exclusively for regression tests."""
    def __init__(self,clock,home,away):
        super().__init__('EUROCUP',clock)
        self.docs=evidence()
        directory={r['code']:r for r in self.docs['clubs']['document']['data']}
        codes=[home,away]+[c for c in ('TRT','RIG','FRA','VNC') if c not in (home,away)][:2]
        mapping=dict(zip(('PRS','ULK','PAR','BAS'),codes))
        for row in self.raw['data']:
            for side in ('local','road'):
                row[side]['club']=deepcopy(directory[mapping[row[side]['club']['code']]])

    def __call__(self,provider,url):
        if url!=season_url('EUROCUP',2026) and not self.offline:
            for receipt in self.docs.values():
                if receipt['source_url']==url:
                    self.calls.append(url)
                    return self.receipt(url,receipt['document'])
        return super().__call__(provider,url)


class ArchiveAliasTests(IsolatedAsyncioTestCase):
    async def test_all_short_pairs_replay_after_tipoff_and_restart_without_inference_network_or_writes(self):
        for home,away,hid,aid in PAIRS:
            with self.subTest(home=home),TemporaryDirectory() as temp:
                root=Path(temp);clock=[NOW]
                with patch('time.time',side_effect=lambda:clock[0]):
                    source=NativeNamedSyntheticSource(lambda:clock[0],hid,aid)
                    prepare(root/'models','EUROCUP',2026,source('EUROLEAGUE_LIVE',season_url('EUROCUP',2026)))
                    service=EuropeanCommandService('EUROCUP',root/'archive',root/'models',source)
                    first=await service.analyze('EuroCup','2026-11-11',home,away)
                    self.assertEqual(first['status'],'EUROPE_HYBRID_OK',first)
                    self.assertTrue(first['new_record'])
                    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    clock[0]+=5*3600;source.offline=True;calls=len(source.calls)
                    service=EuropeanCommandService('EUROCUP',root/'archive',root/'models',source)
                    with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('REPLAY_INFERENCE')):
                        report=await service.analyze('EUROCUP','2026-11-11',home,away)
                        self.assertFalse(report['new_record']);self.assertEqual(first['forecast_sha256'],report['forecast_sha256'])
                        cache={};display=present(report,'EUROCUP',cache,17,service=service)
                        self.assertEqual(display['presentation_version'],VERSION)
                        self.assertIn('EUROCUP ANALİZ',display['html'])
                        self.assertEqual(sum(map(len,display['reply_markup'].inline_keyboard)),6)
                        self.assertEqual(first['timeline']['first_archived_at_utc'],report['timeline']['first_archived_at_utc'])
                    self.assertEqual(calls,len(source.calls))
                    self.assertEqual(before,{p:p.read_bytes() for p in root.rglob('*') if p.is_file()})
                    # Wrong day/direction is never mistaken for the archive.
                    self.assertIsNone(service.existing('2026-11-12',home,away))
                    self.assertIsNone(service.existing('2026-11-11',away,home))
                    with self.assertRaisesRegex(IdentityRefusal,'LEAGUE_MISMATCH'):
                        await service.analyze('EUROLEAGUE','2026-11-11',home,away)
