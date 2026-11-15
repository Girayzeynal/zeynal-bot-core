"""New routing/report tests use pinned original captures and native final evidence."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,Mock,patch

from core.team_identity import digest
from hybrid_engine.frozen_archive import FrozenArchive,FrozenHybridService
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.forward_reports import ForwardEuroLeagueReports
from hybrid_engine.live_euroleague import LiveEuroLeagueService
from hybrid_engine.fixture_menu import euroleague_blocks
from hybrid_engine.prospective_results import OFFICIAL,ResearchReports,ProspectiveResults

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'docs/evidence/handoff-native-20261115.json.gz'
PACKET=ROOT/'docs/evidence/phase845-forward-native-20261113.tar.gz'


def native():
    with gzip.open(EVIDENCE,'rt') as f:w=json.load(f)
    assert digest(w['payload'])==w['sha256']
    return next(r for r in w['payload']['receipts'] if r['source_url']==OFFICIAL)


def stage(directory):
    root=Path(directory)
    # A trusted test fixture capsule: only bounded plain files in its EL prefix.
    with tarfile.open(PACKET,'r:gz') as tar:
        for member in tar:
            p=Path(member.name)
            if len(p.parts)!=2 or p.parts[0]!='forward-euroleague' or not member.isfile():continue
            if member.size>2*1024*1024:raise ValueError('FIXTURE_LIMIT')
            (root/p.name).write_bytes(tar.extractfile(member).read())
    return ForwardRegistry(root)


class EuroLeagueBridgeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.registry=stage(Path(self.tmp.name))
        self.archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
        self.fetch=Mock(side_effect=AssertionError('unexpected network'))
        self.service=LiveEuroLeagueService(self.archive,self.registry,self.fetch,FrozenHybridService(self.archive))
        self.receipt=native()

    def hashes(self):return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.registry.root.iterdir()}

    async def test_three_real_records_replay_without_training_or_new_forecast(self):
        before=self.hashes()
        for item in self.registry.records():
            h,a=self.service._pair(item['payload'])
            with patch('hybrid_engine.live_euroleague.capture',side_effect=AssertionError('capture')):
                r=await self.service.analyze('EUROLEAGUE','2026-11-13',h,a)
            self.assertEqual(r['status'],'FORWARD_EUROLEAGUE_OK');self.assertFalse(r['new_record'])
            text='\n'.join(r['html_parts'])
            self.assertIn('ARŞİV REPLAY',text);self.assertIn('NOT_CALIBRATED',text);self.assertIn('1Q:',text)
            self.assertIn(digest(item['payload']),text)
            self.assertTrue(all(len(x.encode('utf-16-le'))//2<=3200 for x in r['html_parts']))
        self.assertEqual(before,self.hashes());self.fetch.assert_not_called()

    async def test_five_original_matches_keep_original_replay_route(self):
        record=next(iter(self.archive.records.values()));g=record['fixture']
        r=await self.service.analyze('EUROLEAGUE','2026-11-12',g['home_name'],g['away_name'])
        self.assertEqual(r['status'],'FROZEN_REPLAY_OK');self.fetch.assert_not_called()

    async def test_unknown_fixture_refuses_without_invented_prediction(self):
        self.fetch.side_effect=None;self.fetch.return_value=self.receipt
        with patch('time.time',return_value=self.receipt['ingested_at_utc']):
            r=await self.service.analyze('EUROLEAGUE','2026-11-15','Imaginary Home','Imaginary Away')
        self.assertEqual(r['status'],'ABSTAIN');self.assertNotIn('forecast_sha256',r)

    async def test_final_without_original_snapshot_cannot_be_created_as_prematch(self):
        # Wrong day prevents reuse; choose a finalized match with no local capture.
        g=next(e for e in self.receipt['document']['data'] if e['played'] and e['utcDate'].startswith('2026-11-12'))
        self.fetch.side_effect=None;self.fetch.return_value=self.receipt
        with patch('time.time',return_value=self.receipt['ingested_at_utc']):
            r=await self.service.analyze('EUROLEAGUE','2026-11-12',g['local']['club']['name'],g['road']['club']['name'])
        # Some Nov12 matches intentionally route to the five-game archive.
        self.assertIn(r['status'],('ABSTAIN','FROZEN_REPLAY_OK'));self.assertNotEqual(r.get('new_record'),True)

    async def test_new_forward_route_captures_only_the_verified_requested_fixture(self):
        raw=deepcopy(self.receipt);now=raw['ingested_at_utc']
        g=next(e for e in raw['document']['data'] if e['identifier']=='E2026_109')
        from datetime import datetime,timezone
        g.update(played=False,utcDate=datetime.fromtimestamp(now+7200,timezone.utc).isoformat())
        for side in ('local','road'):
            g[side].update(score=None,partials=None)
        raw['document_sha256']=digest(raw['document'])
        self.fetch.side_effect=None;self.fetch.return_value=raw
        seen=[]
        def captured(archive,registry,r,**kwargs):
            seen.append(kwargs['fixture_id'])
            return [{'status':'ABSTAIN'}]
        day=datetime.fromtimestamp(now+7200,timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Istanbul')).date().isoformat()
        with patch('time.time',return_value=now),patch('hybrid_engine.live_euroleague.capture',side_effect=captured):
            r=await self.service.analyze('EUROLEAGUE',day,g['local']['club']['name'],g['road']['club']['name'])
        self.assertEqual(r['status'],'ABSTAIN');self.assertEqual(len(seen),1)

    async def test_official_three_finals_are_append_only_and_reported(self):
        before=self.hashes()
        with patch('time.time',return_value=self.receipt['ingested_at_utc']):
            results=self.registry.settle(self.receipt)
            again=self.registry.settle(self.receipt)
        self.assertTrue(all(r['status']=='VERIFIED_FINAL_APPENDED' for r in results))
        self.assertTrue(all(r['status']=='ALREADY_VERIFIED' for r in again))
        for name,pin in before.items():self.assertEqual(self.hashes()[name],pin)
        fallback=ResearchReports(ProspectiveResults(self.archive,Path(self.tmp.name)/'frozen-results'))
        reports=ForwardEuroLeagueReports(self.service,fallback)
        r=reports.read('EUROLEAGUE')['report'];self.assertEqual(r['unique_fixtures'],3)
        self.assertEqual(r['pending'],0);self.assertEqual(len(r['groups']),2)
        self.assertTrue(all(m['n']==3 for m in r['groups']))
        self.assertIn('Eski beş maç',reports.render_accuracy({'source':'forward','report':r}))
        for item in self.registry.records():self.assertIsNotNone(self.registry.outcome(item['payload']))

    async def test_multiple_model_builds_do_not_duplicate_the_first_issued_cohort(self):
        p=deepcopy(self.registry.records()[0]['payload']);p['version']='ANOTHER_RESEARCH_BUILD'
        with patch('time.time',return_value=p['fixture']['start_ts_utc']-10):self.registry.record(p)
        self.assertEqual(len(self.registry.records()),4);self.assertEqual(len(self.registry.independent_records()),3)
        with patch('time.time',return_value=self.receipt['ingested_at_utc']):self.registry.settle(self.receipt)
        for row in self.registry.records():self.assertIsNotNone(self.registry.outcome(row['payload']))

    async def test_forged_final_with_recomputed_local_hash_fails_native_replay(self):
        with patch('time.time',return_value=self.receipt['ingested_at_utc']):self.registry.settle(self.receipt)
        f=next(self.registry.root.glob('outcome-*'));w=json.loads(f.read_text());w['payload']['full_final'][0]+=1
        w['sha256']=digest(w['payload']);f.unlink();(f.parent/(f.name.rsplit('-',1)[0]+'-'+w['sha256']+'.json')).write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'NATIVE_FINAL_CONFLICT'):
            for item in self.registry.records():self.registry.outcome(item['payload'])

    async def test_invalid_source_menu_never_lists_unverified_commands(self):
        with patch('time.time',return_value=self.receipt['ingested_at_utc']):
            parts=euroleague_blocks(self.receipt,'2026-11-15')
            self.assertIn('doğrulanmış maç yok','\n'.join(parts))
            bad=dict(self.receipt,document_sha256='bad')
            with self.assertRaises(ValueError):euroleague_blocks(bad,'2026-11-15')

class CapsuleSafetyTests(TestCase):
    def test_staging_keeps_original_publication_clocks_and_is_idempotent(self):
        from hybrid_engine.stage_forward_archive import stage as pinned_stage
        packet=ROOT/'docs/evidence/handoff-forward-el-20261115.tar.gz'
        with TemporaryDirectory() as tmp:
            first=pinned_stage(packet,tmp);registry=ForwardRegistry(tmp)
            before={p.name:p.read_bytes() for p in Path(tmp).iterdir()}
            self.assertEqual(first['records'],3);self.assertEqual(first['verified_finals'],3)
            self.assertEqual(pinned_stage(packet,tmp),first)
            self.assertEqual(before,{p.name:p.read_bytes() for p in Path(tmp).iterdir()})
            self.assertTrue(all(x['publication']['first_archived_at_utc']<x['payload']['fixture']['start_ts_utc'] for x in registry.records()))

    def test_staging_refuses_unknown_packet_and_preserves_existing_conflicting_file(self):
        from hybrid_engine.stage_forward_archive import stage as pinned_stage
        packet=ROOT/'docs/evidence/handoff-forward-el-20261115.tar.gz'
        with TemporaryDirectory() as tmp:
            fake=Path(tmp)/'bad.tar.gz';fake.write_bytes(b'not a real capsule')
            with self.assertRaisesRegex(ValueError,'TRUSTED_PIN'):pinned_stage(fake,Path(tmp)/'bad')
            pinned_stage(packet,Path(tmp)/'staged')
            victim=next((Path(tmp)/'staged').glob('forecast-*'));victim.write_bytes(b'conflicting local record')
            with self.assertRaisesRegex(ValueError,'EXISTING_CONFLICT'):pinned_stage(packet,Path(tmp)/'staged')
            self.assertEqual(victim.read_bytes(),b'conflicting local record')

    def test_semantically_forged_source_clock_fails_even_with_rehashed_files(self):
        from hybrid_engine.stage_forward_archive import stage as pinned_stage
        packet=ROOT/'docs/evidence/handoff-forward-el-20261115.tar.gz'
        with TemporaryDirectory() as tmp:
            pinned_stage(packet,tmp);registry=ForwardRegistry(tmp)
            slot=next(Path(tmp).glob('first-*'));w=json.loads(slot.read_text())
            p=registry.read_asset(w['payload']['forecast']);p['source_available_max_utc']=p['prediction_generated_at_utc']+1
            w['payload']['forecast']=registry.asset('forecast',p);w['sha256']=digest(w['payload']);slot.write_text(json.dumps(w))
            with self.assertRaisesRegex(ValueError,'CLOCK_OR_KIND'):registry.records()
