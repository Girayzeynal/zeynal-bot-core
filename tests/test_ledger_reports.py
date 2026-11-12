"""Read-only command integration on isolated synthetic SQLite files."""
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from core.team_identity import digest
from ledger_reports import LedgerReports, accuracy_command, compare_command, render_accuracy, render_compare
from live_analysis_ledger import LiveAnalysisLedger
from prediction_ledger import PredictionLedger, PredictionRecord
from season_archive_inventory import archive_catalog
from tests.test_release_integration import live_payload
from tests.test_season_archive_audit import nba, NOW, START


def fixture(path, *, settled=True, models=1):
    PredictionLedger(str(path)).record_prediction(PredictionRecord('legacy','NBA',START-9999,100,100,None))
    ledger=LiveAnalysisLedger(path)
    with patch('time.time',return_value=NOW):
        b=archive_catalog({'events':[nba()]},provider='ESPN',observed_at_utc=NOW-1,ingested_at_utc=NOW)
    g=b['payload']['fixtures'][0]
    for i in range(models):
        p=live_payload(START);p.update(fixture_id=g['canonical_id'],scope='REGULATION_ONLY',model_digest=str(i)*64,
            model_version='SYNTHETIC_V'+str(i),input_clocks=[dict(observed_at_utc=START-102,ingested_at_utc=START-101)])
        p['home']['official_name']='Synthetic Home';p['away']['official_name']='Synthetic Away'
        with patch('time.time',return_value=START-100+i):ledger.commit(p)
    if settled:
        with patch('time.time',return_value=NOW):ledger.reconcile(b,trusted_sha256=b['sha256'])
    return ledger,g


class ReadOnlyLedgerTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'test.sqlite'

    def test_missing_database_is_not_created(self):
        report=LedgerReports(self.path).read();self.assertEqual(report['status'],'ARCHIVE_UNAVAILABLE')
        self.assertFalse(self.path.exists())

    def test_legacy_only_is_not_labeled_verified_live(self):
        PredictionLedger(str(self.path))
        self.assertEqual(LedgerReports(self.path).read()['status'],'NO_VERIFIED_LIVE_SCHEMA')

    def test_settled_native_final_and_commit_proofs_produce_descriptive_metrics_only(self):
        fixture(self.path,models=2);r=LedgerReports(self.path).read('NBA')
        self.assertEqual(r['unique_fixtures'],1);self.assertEqual(len(r['groups']),2)
        self.assertTrue(all(g['n']==1 and g['team_mae']==7 for g in r['groups']))
        self.assertFalse(r['research_backtests_included']);self.assertNotIn('%',render_accuracy(r))

    def test_reads_are_idempotent_and_do_not_modify_any_sqlite_bytes(self):
        fixture(self.path);before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        service=LedgerReports(self.path)
        for _ in range(3):self.assertEqual(service.read('NBA')['groups'][0]['n'],1)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def test_pending_forecasts_have_no_fabricated_accuracy(self):
        fixture(self.path,settled=False);r=LedgerReports(self.path).read('NBA')
        self.assertEqual(r['pending'],1);self.assertEqual(r['groups'],[])
        self.assertIn('Başarı oranı ve kalibrasyon hesaplanamadı',render_accuracy(r))
        self.assertIn('Tek kayıtlı model',render_compare(r))

    def test_provider_id_lookup_filters_same_fixture_and_league(self):
        fixture(self.path,models=2);service=LedgerReports(self.path)
        self.assertEqual(len(service.read('NBA','401000123')['forecasts']),2)
        self.assertEqual(service.read('EUROLEAGUE','401000123')['forecasts'],[])
        self.assertEqual(len(service.read('NBA','nonexistent')['forecasts']),0)

    def test_tampered_result_with_recomputed_local_hash_still_requires_native_scores(self):
        fixture(self.path)
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER analysis_result_no_update')
            raw=db.execute('SELECT payload FROM verified_analysis_results').fetchone()[0]
            p=json.loads(raw);p['actual'][0]=999
            db.execute('UPDATE verified_analysis_results SET payload=?,sha256=?',(json.dumps(p),digest(p)))
        with self.assertRaisesRegex(ValueError,'NATIVE_SCORE_CONFLICT'):LedgerReports(self.path).read()

    def test_tampered_commit_receipt_is_excluded_by_error_not_counted(self):
        fixture(self.path)
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER live_receipt_no_update');db.execute('UPDATE live_analysis_commit_receipts SET snapshot_sha256=?',('bad',))
        with self.assertRaisesRegex(ValueError,'COMMIT_PROOF_CONFLICT'):LedgerReports(self.path).read()

    def test_unconfirmed_snapshot_and_research_table_are_not_included(self):
        fixture(self.path,settled=False)
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER live_receipt_no_delete');db.execute('DELETE FROM live_analysis_commit_receipts')
            db.execute('CREATE TABLE research_results (score INTEGER)');db.execute('INSERT INTO research_results VALUES(999)')
        self.assertEqual(LedgerReports(self.path).read()['forecasts'],[])

    def test_unknown_league_and_symlink_are_refused(self):
        fixture(self.path)
        with self.assertRaises(ValueError):LedgerReports(self.path).read('unknown')
        p=self.path.parent/'link.sqlite';p.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError,'SYMLINK'):LedgerReports(p).read()


class ReportCommandTests(IsolatedAsyncioTestCase):
    async def test_registered_commands_dispatch_to_read_only_service(self):
        with TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_ONLY','API_SPORTS_KEY':''}):
                main=importlib.import_module('main');engine=main.Faz23Engine
                with patch.object(main,'Faz23Engine',lambda:engine(str(Path(tmp)/'faz23.sqlite'))):app=main.build_app()
            names={n for hs in app.handlers.values() for h in hs for n in h.commands}
            self.assertTrue({'nba','analyze','accuracy','compare'}<=names)
            path=Path(tmp)/'test.sqlite';fixture(path);app.bot_data['ledger_reports']=LedgerReports(path)
            reply=AsyncMock();update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply))
            await accuracy_command(update,SimpleNamespace(args=['NBA'],application=app))
            await compare_command(update,SimpleNamespace(args=['NBA','401000123'],application=app))
            self.assertIn('MAE',reply.call_args_list[0].args[0]);self.assertIn('Tek kayıtlı model',reply.call_args_list[1].args[0])

    async def test_usage_and_invalid_data_do_not_expose_exception_details(self):
        reply=AsyncMock();update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply))
        await compare_command(update,SimpleNamespace(args=[],application=None))
        self.assertIn('Kullanım',reply.call_args.args[0])
        service=SimpleNamespace(read=lambda *args:(_ for _ in ()).throw(sqlite3.OperationalError('SECRET_MUST_NOT_APPEAR')))
        ctx=SimpleNamespace(args=[],application=SimpleNamespace(bot_data={'ledger_reports':service}))
        await accuracy_command(update,ctx)
        self.assertNotIn('SECRET_MUST_NOT_APPEAR',reply.call_args.args[0])
