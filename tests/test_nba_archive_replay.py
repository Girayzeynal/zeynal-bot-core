"""Pinned NBA archive replay and real command handlers; sends are mocks, not Telegram."""
from copy import deepcopy
from datetime import datetime,timezone
from html.parser import HTMLParser
import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock,patch

from core.team_identity import digest
from hybrid_engine.nba_replay import NBAReplayArchive,PACKET_SHA256,DEFAULT_PACKET,validate_case,verify_native_identity,TSI
from hybrid_engine.frozen_archive import FrozenArchive
from hybrid_engine.elite_render import units
from hybrid_engine.test_bot import install_isolated_services

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'docs/prospective/euroleague-20261112'
NBA=None


def nba():
    global NBA
    if NBA is None:NBA=NBAReplayArchive()
    return NBA


class ArchiveTests(TestCase):
    def test_packet_contains_exactly_four_optimized_cases_and_all_fields(self):
        cases=nba().cases();self.assertEqual(len(cases),4)
        self.assertEqual(len({c['snapshot']['fixture_id'] for c in cases}),4)
        for c in cases:
            p=validate_case(c);self.assertEqual(digest(p),c['snapshot_sha256'])
            self.assertTrue({'prediction','intervals','mc_qmc'}<=set(p))

    def test_wrong_packet_hash_is_not_accepted_as_a_new_archive(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.tar.gz';p.write_bytes(b'not the trusted archive')
            with self.assertRaisesRegex(ValueError,'PACKET_SHA256'):NBAReplayArchive(p)

    def test_missing_packet_fails_closed(self):
        with TemporaryDirectory() as tmp,self.assertRaisesRegex(ValueError,'PACKET_REQUIRED'):NBAReplayArchive(Path(tmp)/'absent')

    def test_snapshot_sha_covers_prediction_intervals_and_mc_comparison(self):
        for field in ('prediction','intervals','mc_qmc'):
            with self.subTest(field=field):
                c=nba().cases()[0];c['snapshot'][field]['tamper']=True
                with self.assertRaisesRegex(ValueError,'SNAPSHOT_SHA256'):validate_case(c)

    def test_timestamps_cannot_be_backfilled_after_tipoff_or_from_bool(self):
        for change in ({'prediction_generated_at_utc':1794528000},{'created_at_utc':1794528000},{'prediction_generated_at_utc':True}):
            c=nba().cases()[0];c['snapshot'].update(change);c['snapshot_sha256']=digest(c['snapshot'])
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'CLOCK'):validate_case(c)

    def test_future_input_and_target_label_are_rejected(self):
        c=nba().cases()[0];c['snapshot']['input_clocks'][0]['ingested_at_utc']=c['snapshot']['prediction_generated_at_utc']+1;c['snapshot_sha256']=digest(c['snapshot'])
        with self.assertRaisesRegex(ValueError,'INPUT_AFTER'):validate_case(c)
        c=nba().cases()[0];c['snapshot']['actual']=[123,112];c['snapshot_sha256']=digest(c['snapshot'])
        with self.assertRaisesRegex(ValueError,'RECORD_KIND'):validate_case(c)

    def test_capture_names_must_match_snapshot_official_names(self):
        c=nba().cases()[0];c['home']='Other team'
        with self.assertRaisesRegex(ValueError,'OFFICIAL_NAME'):validate_case(c)

    def test_fake_calibration_or_confidence_is_not_admitted(self):
        for field,value in [('calibration_status','CALIBRATED'),('confidence',{'value':99})]:
            c=nba().cases()[0];c['snapshot'][field]=value;c['snapshot_sha256']=digest(c['snapshot'])
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'UNVERIFIED_CALIBRATION'):validate_case(c)

    def test_mutating_a_returned_case_does_not_mutate_the_adapter(self):
        original=nba().cases();modified=nba().cases();modified[0]['snapshot']['prediction']['home']=999
        self.assertEqual(nba().cases(),original)

    def test_native_identity_uses_all_pinned_scoreboards_not_arbitrary_url_field(self):
        # Washington/Minnesota's original URL field points to the other ESPN
        # partition. Their actual pinned dates=20261112 receipts establish ID.
        for c in nba().cases():
            fid=c['snapshot']['fixture_id'];native=nba()._native[fid]
            self.assertIn('dates=20261112',native['source_url'])
            if c['home'] in ('Washington Wizards','Minnesota Timberwolves'):
                self.assertIn('dates=20261113',c['snapshot']['fixture_source_url'])


class CommandTests(IsolatedAsyncioTestCase):
    async def exercise(self,index):
        case=nba().cases()[index];p=case['snapshot'];command='/analyze NBA 2026-11-13 '+case['home']+' vs '+case['away']
        with TemporaryDirectory() as tmp,patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_LOCAL_ONLY'}):
            main=importlib.import_module('main');app=SimpleNamespace(bot_data={},add_handler=Mock(),add_error_handler=Mock())
            install_isolated_services(app,FrozenArchive(ARCHIVE),tmp,chat_id=17,nba_replay=nba(),replay_only=True,decision_layer=True)
            message=SimpleNamespace(text=command,reply_text=AsyncMock(return_value=SimpleNamespace(date=datetime.now(timezone.utc),message_id=8)))
            update=SimpleNamespace(update_id=index+1,effective_chat=SimpleNamespace(id=17),message=message,effective_message=message)
            ctx=SimpleNamespace(args=[],application=app)
            with patch('requests.get',side_effect=AssertionError('No source downloads')),\
                 patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('No new simulations')),\
                 patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('No new fit')),\
                 patch('hybrid_engine.live_nba.LiveNBAHybridService.__init__',side_effect=AssertionError('No new ledger')):
                await main.analyze_command(update,ctx)
                report=await app.bot_data['verified_analysis_service'].analyze('NBA','2026-11-13',case['home'],case['away'])
            text='\n'.join(c.args[0] for c in message.reply_text.call_args_list)
            self.assertIn('NBA ARŞİV REPLAY',text);self.assertIn('NOT_CALIBRATED',text);self.assertIn(case['snapshot_sha256'],text)
            self.assertIn(f"{p['prediction']['home']:.2f}",text);self.assertIn('KAYITLI MC / QMC',text)
            self.assertNotIn('arşivinde bu maç için kayıt yok',text)
            self.assertEqual(report['snapshot'],p);self.assertEqual(report['prediction'],p['prediction'])
            self.assertEqual(report['intervals'],p['intervals']);self.assertEqual(report['mc_qmc'],p['mc_qmc'])
            self.assertFalse(report['new_record']);self.assertEqual(report['timeline']['prediction_generated_at_utc'],p['prediction_generated_at_utc'])
            self.assertIsNone(report['timeline']['first_archived_at_utc'])
            self.assertEqual(len(app.bot_data['decision_journal'].read()),0)
            self.assertFalse(list(Path(tmp).glob('*ledger*')))

    async def test_philadelphia_toronto_analyze_command(self):await self.exercise(0)
    async def test_washington_detroit_analyze_command(self):await self.exercise(1)
    async def test_minnesota_dallas_analyze_command(self):await self.exercise(2)
    async def test_phoenix_charlotte_analyze_command(self):await self.exercise(3)

    async def test_yesterday_is_a_date_diagnostic_not_a_replacement_forecast(self):
        c=nba().cases()[0];r=await nba().analyze('NBA','2026-11-12',c['home'],c['away'])
        self.assertEqual(r['status'],'ABSTAIN');self.assertIn('FIXTURE_LOCAL_DATE_MISMATCH',r['html'])
        self.assertIn('2026-11-13',r['html']);self.assertNotIn('snapshot',r)

    async def test_unknown_or_reversed_pair_never_creates_a_prediction(self):
        c=nba().cases()[0]
        for h,a in [('Unknown','Other'),(c['away'],c['home'])]:
            r=await nba().analyze('NBA','2026-11-13',h,a)
            self.assertIn('NBA_REPLAY_NOT_FOUND',r['html']);self.assertFalse(r['new_record'])

    async def test_rendered_parts_are_valid_bounded_html_and_not_confidence_claims(self):
        class Parser(HTMLParser):
            def __init__(self):super().__init__();self.stack=[]
            def handle_starttag(self,tag,attrs):self.stack.append(tag)
            def handle_endtag(self,tag):assert self.stack.pop()==tag
        for c in nba().cases():
            r=await nba().analyze('NBA','2026-11-13',c['home'],c['away'])
            for part in r['html_parts']:
                self.assertLessEqual(units(part),3200);p=Parser();p.feed(part);self.assertEqual(p.stack,[])
            self.assertIn('Güven endeksi: hesaplanamadı','\n'.join(r['html_parts']))

    async def test_istanbul_command_day_and_utc_tipoff_are_preserved(self):
        for c,hour in zip(nba().cases(),(3,3,4,5)):
            p=c['snapshot'];t=datetime.fromtimestamp(p['fixture_start_utc'],TSI)
            self.assertEqual(t.date().isoformat(),'2026-11-13');self.assertEqual(t.hour,hour)
        rows=await nba().list_nba_games('2026-11-13');self.assertEqual(len(rows),4)
        self.assertEqual(await nba().list_nba_games('2026-11-12'),[])

    async def test_default_installer_supports_nba_without_a_live_model(self):
        with TemporaryDirectory() as tmp:
            app=SimpleNamespace(bot_data={},add_handler=Mock(),add_error_handler=Mock())
            install_isolated_services(app,FrozenArchive(ARCHIVE),tmp,chat_id=17)
            c=nba().cases()[0];r=await app.bot_data['verified_analysis_service'].analyze('NBA','2026-11-13',c['home'],c['away'])
            self.assertEqual(r['status'],'NBA_ARCHIVE_REPLAY_OK')

    async def test_euroleague_archive_dispatch_is_preserved(self):
        archive=FrozenArchive(ARCHIVE);r=next(iter(archive.records.values()));g=r['fixture']
        with TemporaryDirectory() as tmp:
            app=SimpleNamespace(bot_data={},add_handler=Mock(),add_error_handler=Mock())
            install_isolated_services(app,archive,tmp,chat_id=17,nba_replay=nba(),replay_only=True)
            report=await app.bot_data['verified_analysis_service'].analyze('EUROLEAGUE','2026-11-12',g['home_name'],g['away_name'])
            self.assertEqual(report['status'],'FROZEN_REPLAY_OK');self.assertEqual(report['record'],r)

    async def test_replay_only_forbids_an_injected_live_service(self):
        with TemporaryDirectory() as tmp,self.assertRaisesRegex(ValueError,'FORBIDS_LIVE'):
            install_isolated_services(SimpleNamespace(),FrozenArchive(ARCHIVE),tmp,chat_id=17,nba_service=Mock(),replay_only=True)
