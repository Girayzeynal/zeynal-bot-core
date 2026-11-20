"""Synthetic delivery attacks + real journal hashing; no external Telegram claim."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.device_verification import inspect,read_journal
from hybrid_engine.telegram_evidence import evidence_report
from telegram_delivery import DeliveryJournal


def suite():
    events=[]
    for i,command in enumerate(('/nba','/analyze','/accuracy','/compare','/start'),1):
        text=command+' NBA';pin=digest('RESPONSE '+str(i))
        events.append(dict(kind='COMMAND_RECEIVED',update_id=i,command=command,chat_id=17,bot_id=123,is_bot=False,
            request_sha256=digest(text),user_message_at_utc=100))
        events.append(dict(kind='DELIVERY_ACCEPTED',update_id=i,chat_id=17,bot_id=123,telegram_message_id=i,
            telegram_sent_at_utc=101,ack_at_utc=102,transport='OFFICIAL_TELEGRAM_BOT_API',
            dedicated_bot_identity_verified=True,expected_chat_matches=True,response_content_matches_request=True,
            message_sha256=pin,response_sha256=digest(str(i)),request_text_sha256=pin))
        if command=='/analyze':events.append(dict(record_type='TELEGRAM_ANALYSIS_DELIVERY',update_id=i,
            status='TELEGRAM_ACCEPTED',part_count=1,part_index=0,telegram_message_id=i,
            attempted_at_utc=100,telegram_sent_at_utc=101,telegram_ack_at_utc=102,
            message_sha256=pin,request_sha256=digest(text)))
    return events


class DeliveryBindingTests(TestCase):
    def report(self,events):return evidence_report(events,asof_utc=200)

    def test_complete_scope_requires_hash_bound_analysis_same_chat_and_bot(self):
        r=self.report(suite());self.assertTrue(r['complete_command_suite_verified'])
        self.assertEqual(r['complete_analysis_updates'],[2]);self.assertFalse(r['independent_server_signature'])
        self.assertFalse(r['application_result_correctness_verified'])

    def test_sidecar_matching_id_but_wrong_message_request_or_clock_does_not_prove_analysis(self):
        for key,value in [('message_sha256','f'*64),('request_sha256','e'*64),('telegram_ack_at_utc',201),
                          ('telegram_sent_at_utc',99),('part_index',True),('part_count',True)]:
            e=suite();part=next(x for x in e if x.get('record_type'));part[key]=value
            with self.subTest(key=key):
                r=self.report(e);self.assertFalse(r['complete_command_suite_verified']);self.assertEqual(r['complete_analysis_updates'],[])

    def test_duplicate_command_conflict_cannot_be_overwritten_by_the_last_row(self):
        e=suite();command=deepcopy(e[2]);command['command']='/test';e.insert(0,command)
        r=self.report(e);self.assertFalse(r['complete_command_suite_verified'])
        self.assertIn('CONFLICTING_COMMAND_UPDATE',[reason for row in r['excluded'] for reason in row['reasons']])

    def test_duplicate_delivery_or_sidecar_cannot_inflate_or_complete_a_missing_part(self):
        e=suite();self.assertEqual(self.report(e+e)['api_verified_messages'],5)
        part=next(x for x in e if x.get('record_type'));part['part_count']=2
        extra=dict(part,part_index=1);e.append(extra)
        self.assertFalse(self.report(e)['complete_command_suite_verified'])

    def test_four_delivered_commands_across_different_chat_or_bot_are_not_one_suite(self):
        for key,value in [('chat_id',18),('bot_id',124)]:
            e=suite()
            for row in e:
                if row.get('update_id')==4 and key in row:row[key]=value
            self.assertFalse(self.report(e)['complete_command_suite_verified'])

    def test_conflicting_same_server_message_id_is_not_accepted(self):
        e=suite();extra=dict(e[1],request_text_sha256='f'*64);e.append(extra)
        self.assertEqual(self.report(e)['api_verified_messages'],4)

    def test_legacy_unbound_part_keeps_delivery_evidence_without_complete_suite(self):
        e=suite();next(x for x in e if x.get('record_type')).pop('request_sha256')
        r=self.report(e);self.assertTrue(r['actual_telegram_delivery_verified']);self.assertFalse(r['complete_command_suite_verified'])


class DeviceReviewTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def journal(self):
        p=self.root/'telegram-delivery.sqlite';journal=DeliveryJournal(p)
        for i,event in enumerate(suite()):journal.append(str(i),event)
        return p

    def test_missing_device_archive_or_journal_is_not_created(self):
        root=self.root/'missing';r=inspect(root);self.assertFalse(root.exists())
        self.assertEqual(r['nba']['status'],'NOT_PRESENT');self.assertEqual(r['telegram']['status'],'NOT_PRESENT')
        self.assertEqual(r['acceptance'],'NO_GO');self.assertFalse(r['api_requests_made'])
        self.assertEqual(r['acceptance_scope'],'RESEARCH_EVIDENCE_REVIEW_NOT_FUNCTIONAL_ACTIVATION')
        self.assertFalse(r['features_disabled_by_this_review'])

    def test_real_readonly_sqlite_retains_bytes_and_does_not_export_ids_or_raw_content(self):
        p=self.journal();before=p.read_bytes()
        r=read_journal(p,asof_utc=200);self.assertEqual(r['status'],'LOCAL_JOURNAL_INSPECTED')
        self.assertTrue(r['complete_command_suite_verified']);self.assertEqual(before,p.read_bytes())
        text=json.dumps(r)
        for word in ('chat_id','bot_id','message_id','request_text','RESPONSE','api.telegram.org',str(p)):self.assertNotIn(word,text)
        self.assertFalse(r['application_result_correctness_verified'])

    def test_corrupt_payload_or_wrong_hash_blocks_not_partial_success(self):
        p=self.journal()
        with sqlite3.connect(p) as db:
            db.execute('DROP TRIGGER delivery_no_update');db.execute("UPDATE delivery_events SET sha256=? WHERE event_key='0'",('0'*64,))
        r=read_journal(p,asof_utc=200);self.assertFalse(r['actual_telegram_delivery_verified'])
        self.assertIn('NOT_VERIFIED',r['status'])

    def test_scan_limit_fails_closed_instead_of_claiming_partial_complete_suite(self):
        p=self.journal()
        with patch('hybrid_engine.device_verification.MAX_EVENTS',2):r=read_journal(p,asof_utc=200)
        self.assertFalse(r['complete_command_suite_verified']);self.assertIn('NOT_VERIFIED',r['status'])

    def test_invalid_ledger_is_not_replaced_or_counted_as_empty_valid_archive(self):
        folder=self.root/'live-nba';folder.mkdir();p=folder/'nba-hybrid.sqlite';p.write_bytes(b'not a database')
        r=inspect(self.root);self.assertEqual(p.read_bytes(),b'not a database')
        self.assertEqual(r['nba']['status'],'NOT_VERIFIED_NATIVE_ARCHIVE_AUDIT_FAILED')

    def test_symlink_cannot_read_production_or_another_store(self):
        p=self.journal();link=self.root/'link.sqlite';link.symlink_to(p)
        with self.assertRaises(ValueError):read_journal(link,asof_utc=200)

    def test_native_ledger_aggregates_reuse_existing_audit_without_queries_or_new_forecasts(self):
        from tests.test_ledger_reports import fixture
        path=self.root/'live-nba/nba-hybrid.sqlite';path.parent.mkdir();fixture(path)
        before=path.read_bytes()
        with patch('requests.get',side_effect=AssertionError('NO_NETWORK')),patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO_FIT')):
            result=inspect(self.root)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(result['nba']['status'],'READ_ONLY_NATIVE_VERIFIED')
        self.assertEqual(result['nba']['unique_fixtures'],1)
        # This legacy synthetic fixture has no separately proven generation
        # time/native input assets; the strict comparison must stay empty.
        self.assertEqual(result['nba']['comparison']['groups'],[])
        self.assertFalse(result['nba']['all_original_input_sources_verified'])
        self.assertEqual(result['acceptance'],'NO_GO')

    def test_database_size_budget_refuses_before_hashing_or_sql(self):
        p=self.journal()
        with patch('hybrid_engine.device_verification.MAX_JOURNAL_BYTES',1),patch('hybrid_engine.device_verification.file_sha',side_effect=AssertionError('NO_SCAN')):
            result=read_journal(p,asof_utc=200)
        self.assertEqual(result['status'],'NOT_VERIFIED_JOURNAL_SIZE_LIMIT')

    def test_launcher_review_precedes_polling_lock_git_and_credentials(self):
        import os,subprocess,sys
        checkout=self.root/'zeynal-hybrid-844';binary=checkout/'.venv/bin/python';binary.parent.mkdir(parents=True)
        binary.symlink_to(sys.executable);module=checkout/'hybrid_engine';module.mkdir()
        (module/'__init__.py').write_text('')
        (module/'device_verification.py').write_text('import json,sys;print(json.dumps(sys.argv[1:]))')
        launcher=Path(__file__).resolve().parents[1]/'scripts/run_isolated_test_bot.sh'
        installed=checkout/'scripts/run_isolated_test_bot.sh';installed.parent.mkdir()
        installed.write_text(launcher.read_text())
        result=subprocess.run(['bash',str(installed),'--verification-review'],env=dict(os.environ,HOME=str(self.root)),
            text=True,capture_output=True,check=True,timeout=5)
        self.assertEqual(json.loads(result.stdout),['--data-directory',str(self.root/'zeynal-test-isolated/data')])
        self.assertFalse((self.root/'zeynal-test-isolated').exists())
