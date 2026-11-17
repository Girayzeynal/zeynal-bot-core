"""Coverage view regressions and immutable protocol; no real Telegram claims."""
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

from core.team_identity import digest
from hybrid_engine.challenger_summary import read_report,latest_report,summarize,main,MAX_BYTES
from hybrid_engine.challenger_review import source_pins
from hybrid_engine.challenger_forward import FORMAT,POLICY

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    # Explicit synthetic report, not additional native or prospective games.
    cells={'P25_P75':dict(n=18,hits=9,observed_coverage=.5,nominal_mass=.5),
           'P05_P95':dict(n=18,hits=14,observed_coverage=14/18,nominal_mass=.9)}
    m=dict(n=18,team_scores={'mae':10.74},total={'mae':16.69},winner={'correct':13},
        coverage=dict(markets={'TOTAL':cells},status='DESCRIPTIVE_NOT_CALIBRATION_PROOF'),
        calibration_status='NOT_CALIBRATED')
    return dict(format='SAME_INPUT_OFFLINE_CHALLENGERS_V1',status='REVIEW_COMPLETE',
        reviewed=18,blocked=0,remaining=0,database_and_wal_unchanged=True,
        predictions_replaced=False,prematch_records_created=0,production_changed=False,calibration_fit=False,
        acceptance={'decision':'NO_GO'},groups=[dict(cohort={'league':'NBA'},n=18,day_clusters=3,
            models={'FROZEN_ARCHIVED':m,'UNSUPPORTED':dict(n=0)},abstentions={})])


def publish(root,p):
    path=root/('challengers-'+digest(p)+'.json')
    path.write_text(json.dumps(dict(payload=p,sha256=digest(p))))
    return path


class CoverageSummaryTests(unittest.TestCase):
    def test_reads_correct_nested_market_level_without_calibration_claim(self):
        p=fixture();before=digest(p);r=summarize(p,'/synthetic.json',before)
        m=r['groups'][0]['models']['FROZEN_ARCHIVED']
        self.assertEqual(m['total_coverage']['P25_P75']['hits'],9)
        self.assertEqual(m['total_coverage']['P05_P95']['hits'],14)
        self.assertEqual(m['total_coverage_status'],'DESCRIPTIVE_NOT_CALIBRATION_PROOF')
        self.assertEqual(m['winner'],13);self.assertIsNone(m['confidence_index'])
        self.assertEqual(digest(p),before);self.assertTrue(r['view_only'])

    def test_unsupported_model_stays_missing_not_zero_coverage(self):
        r=summarize(fixture(),'synthetic','a'*64)['groups'][0]['models']['UNSUPPORTED']
        self.assertIsNone(r['total_coverage'])
        self.assertEqual(r['total_coverage_status'],'NO_SETTLED_SUPPORTED_FORECASTS')
        p=fixture();p['groups'][0]['models']['UNSUPPORTED']['n']=1
        r=summarize(p,'synthetic','a'*64)['groups'][0]['models']['UNSUPPORTED']
        self.assertEqual(r['total_coverage_status'],'NO_SUPPORTED_TOTAL_INTERVALS')

    def test_saved_report_bytes_and_first_metadata_unchanged(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);path=publish(root,fixture());before=path.read_bytes();stamp=path.stat().st_mtime_ns
            p,pin=read_report(path,root);self.assertEqual(pin,digest(p))
            with redirect_stdout(StringIO()):self.assertEqual(main(['--directory',str(root)]),0)
            self.assertEqual(path.read_bytes(),before);self.assertEqual(path.stat().st_mtime_ns,stamp)

    def test_wrong_filename_or_tampered_body_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);path=publish(root,fixture());w=json.loads(path.read_text());w['payload']['reviewed']=999
            path.write_text(json.dumps(w))
            with self.assertRaisesRegex(ValueError,'PIN_OR_FORMAT'):read_report(path,root)
            other=root/'arbitrary.json';other.write_text('{}')
            with self.assertRaisesRegex(ValueError,'PATH_OR_NAME'):read_report(other,root)

    def test_missing_report_directory_is_not_created(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'missing'
            with redirect_stdout(StringIO()) as out:self.assertEqual(main(['--directory',str(path)]),2)
            self.assertFalse(path.exists());self.assertEqual(json.loads(out.getvalue())['status'],'BLOCKED')

    def test_symlink_and_production_paths_refused(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);path=publish(root,fixture());link=root/('challengers-'+'a'*64+'.json');link.symlink_to(path)
            with self.assertRaisesRegex(ValueError,'ISOLATED_REPORT_PATH'):read_report(link,root)
        with self.assertRaisesRegex(ValueError,'ISOLATED_REPORT_PATH'):read_report('/data/report.json','/data')

    def test_oversized_report_rejected_before_json_load(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/('challengers-'+'a'*64+'.json')
            with path.open('wb') as f:f.truncate(MAX_BYTES+1)
            with self.assertRaisesRegex(ValueError,'SIZE_OR_MISSING'):read_report(path,root)

    def test_latest_is_by_write_time_not_model_metric_and_invalid_latest_is_not_skipped(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);a=publish(root,fixture());p=fixture();p['reviewed']=17;b=publish(root,p)
            os.utime(a,ns=(1000000000,1000000000));os.utime(b,ns=(2000000000,2000000000))
            self.assertEqual(latest_report(root),b);b.write_text('{}')
            with redirect_stdout(StringIO()):self.assertEqual(main(['--directory',str(root)]),2)

    def test_legacy_review_child_exit_and_arguments_are_preserved(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);path=publish(root,fixture())
            result=SimpleNamespace(returncode=2,stdout=json.dumps(dict(path=str(path))))
            with patch('hybrid_engine.challenger_summary.subprocess.run',return_value=result) as child,redirect_stdout(StringIO()) as out:
                code=main(['--run-review','--ledger','synthetic.sqlite','--assets-directory','synthetic-assets','--output-directory',str(root)])
            self.assertEqual(code,2)
            self.assertIn('hybrid_engine.challenger_review',child.call_args.args[0])
            self.assertIn('synthetic.sqlite',child.call_args.args[0])
            self.assertEqual(json.loads(out.getvalue())['groups'][0]['models']['FROZEN_ARCHIVED']['total_coverage']['P05_P95']['hits'],14)

    def test_legacy_child_block_is_not_disguised_as_success(self):
        result=SimpleNamespace(returncode=2,stdout=json.dumps(dict(status='BLOCKED',reason='SYNTHETIC_FAILURE')))
        with patch('hybrid_engine.challenger_summary.subprocess.run',return_value=result),redirect_stdout(StringIO()) as out:
            self.assertEqual(main(['--run-review','--ledger','missing']),2)
        self.assertEqual(json.loads(out.getvalue())['status'],'BLOCKED')

    def test_real_native_archived_report_has_coverage_at_nested_location(self):
        path=ROOT/'docs/evidence/challenger-phase94-native-20261117.json.gz'
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        with gzip.open(path,'rt') as f:w=json.load(f)
        self.assertEqual(digest(w['payload']),w['sha256']);r=summarize(w['payload'],path,w['sha256'])
        m=r['groups'][0]['models']['FROZEN_ARCHIVED'];self.assertEqual(m['total_coverage']['P05_P95']['n'],1)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_phone_registered_protocol_hash_is_unchanged(self):
        # User-reported registration metadata + public source pins, not a
        # fabricated copy of their private plan or an independent signature.
        p=dict(format=FORMAT,registered_at_utc=1794926907,policy=POLICY,source_pins=source_pins(),production_enabled=False)
        self.assertEqual(digest(p),'1e8f24a665a8b34a2ca22c37e408591ae8547b12788fe70c7150079b43249317')
        self.assertNotIn('challenger_summary.py',source_pins())

    def test_view_rejects_a_rehashed_report_claiming_replaced_forecasts(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);p=fixture();p['predictions_replaced']=True;path=publish(root,p)
            with self.assertRaisesRegex(ValueError,'REPORT_SCOPE'):read_report(path,root)

    def test_actual_review_child_failure_is_formatted_and_preserves_sqlite(self):
        import subprocess
        import sys
        from tests.test_phase91 import ten_game_ledger
        with TemporaryDirectory() as tmp:
            root=Path(tmp);native=root/'native';native.mkdir();assets=native/'assets';assets.mkdir()
            ledger=native/'nba.sqlite';ten_game_ledger(ledger);before=ledger.read_bytes()
            child=subprocess.run([sys.executable,'-B','-m','hybrid_engine.challenger_summary','--run-review',
                '--ledger',str(ledger),'--assets-directory',str(assets),'--output-directory',str(root/'reports')],
                cwd=ROOT,capture_output=True,text=True,timeout=30)
            self.assertEqual(child.returncode,2);r=json.loads(child.stdout)
            self.assertEqual(r['status'],'REVIEW_WITH_BLOCKS');self.assertEqual(r['blocked'],1)
            self.assertTrue(r['view_only']);self.assertEqual(ledger.read_bytes(),before)
            self.assertFalse(r['production_changed'])
