"""Prospective publication boundaries; all future clocks/records are synthetic."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.challenger_forward import POLICY, admission, register, load_plan, capture, performance, main
from hybrid_engine.challenger_review import NAMES

NOW=1794900000


class ProtocolTests(unittest.TestCase):
    def test_registration_is_idempotent_and_preserves_first_clock(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('time.time',return_value=NOW):a,new=register(root)
            with patch('time.time',return_value=NOW+100):b,newer=register(root)
            self.assertTrue(new);self.assertFalse(newer);self.assertEqual(a,b)
            self.assertEqual(b['payload']['registered_at_utc'],NOW)
            self.assertFalse(b['payload']['policy']['automatic_promotion'])

    def test_missing_plan_read_creates_no_directory(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/'missing'
            with self.assertRaisesRegex(ValueError,'ONE_EXISTING'):load_plan(root)
            self.assertFalse(root.exists())

    def test_future_clock_policy_change_and_source_change_fail_closed(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('time.time',return_value=NOW):w,_=register(root)
            with self.assertRaises(ValueError):load_plan(root,now=NOW-1)
            path=next(root.glob('plan-*.json'));p=deepcopy(w['payload']);p['policy']['minimum_future_games']=1
            path.write_text(json.dumps(dict(payload=p,sha256=digest(p))))
            with self.assertRaises(ValueError):load_plan(root,now=NOW)
            path.write_text(json.dumps(w))
            with patch('hybrid_engine.challenger_forward.source_pins',return_value={'changed':'a'*64}):
                with self.assertRaises(ValueError):load_plan(root,now=NOW)

    def test_development_capture_before_registration_cannot_become_confirmatory(self):
        p=dict(feature_cutoff_utc=NOW-1,prediction_generated_at_utc=NOW-1,fixture_start_utc=NOW+7200)
        plan=dict(payload=dict(registered_at_utc=NOW))
        self.assertEqual(admission(p,plan,NOW),'ORIGINAL_CAPTURE_PRECEDES_PROTOCOL')

    def test_tipoff_staleness_lead_and_future_capture_clocks(self):
        plan=dict(payload=dict(registered_at_utc=NOW-10000))
        p=dict(feature_cutoff_utc=NOW-100,prediction_generated_at_utc=NOW-99,fixture_start_utc=NOW+7200)
        self.assertIsNone(admission(p,plan,NOW))
        self.assertEqual(admission(dict(p,fixture_start_utc=NOW),plan,NOW),'MATCH_ALREADY_STARTED')
        self.assertEqual(admission(dict(p,fixture_start_utc=NOW+899),plan,NOW),'INSUFFICIENT_PRETIPOFF_LEAD')
        self.assertEqual(admission(dict(p,feature_cutoff_utc=NOW-3601),plan,NOW),'ORIGINAL_INPUTS_TOO_OLD_FOR_PROTOCOL')
        self.assertEqual(admission(dict(p,prediction_generated_at_utc=NOW+1),plan,NOW),'INVALID_ORIGINAL_CAPTURE_CLOCK')

    def test_empty_future_report_never_says_go_or_synthesizes_training_games(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('time.time',return_value=NOW):register(root)
            with patch('hybrid_engine.challenger_forward.LedgerReports') as reader:
                reader.return_value.read.return_value={'forecasts':[]}
                with patch('time.time',return_value=NOW):r=performance(root/'missing.sqlite',root)
            self.assertEqual(r['settled'],0);self.assertFalse(r['groups']);self.assertFalse(r['automatic_promotion'])
            self.assertIn('NO_GO',r['release_decision']);self.assertFalse((root/'missing.sqlite').exists())

    def test_started_native_ledger_rows_never_reenter_as_new_prematch(self):
        from tests.test_phase91 import ten_game_ledger,NOW as SOURCE_NOW
        with TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=root/'nba.sqlite'
            ten_game_ledger(ledger);before=ledger.read_bytes()
            with patch('time.time',return_value=SOURCE_NOW):register(root/'protocol')
            with patch('time.time',return_value=SOURCE_NOW),patch('hybrid_engine.challenger_forward.predict_snapshot',side_effect=AssertionError('NO FIT')):
                r=capture(ledger,root/'assets',root/'protocol')
            self.assertEqual(r['eligible'],0);self.assertFalse(r['results'])
            self.assertEqual(r['skipped']['RESULT_ALREADY_AVAILABLE'],1)
            self.assertEqual(r['skipped']['ORIGINAL_CUTOFF_UNAVAILABLE_OR_INVALID'],9)
            self.assertEqual(ledger.read_bytes(),before)

    def test_cli_missing_protocol_never_registers_implicitly(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/'protocol'
            with patch('sys.argv',['forward','capture','--ledger',str(Path(tmp)/'native'/'nba.sqlite'),
                '--assets-directory',str(Path(tmp)/'native'/'assets'),'--directory',str(root)]):
                self.assertEqual(main(),2)
            self.assertFalse(root.exists())

    def test_invalid_batch_limits_do_not_open_files(self):
        for maximum in (0,9,True):
            with self.subTest(maximum=maximum),self.assertRaises(ValueError):capture('/missing','/assets','/plan',maximum=maximum)

    def test_live_archive_directory_cannot_be_used_for_protocol_output(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'native'/'assets'/'new'
            with patch('sys.argv',['forward','plan','--ledger',str(root/'native'/'nba.sqlite'),'--directory',str(output)]):
                self.assertEqual(main(),2)
            self.assertFalse(output.exists())


class SyntheticForwardPublicationTests(unittest.TestCase):
    """Real append-only files, mocked source adapter: not a native capture claim."""
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.directory=self.root/'protocol'
        with patch('time.time',return_value=NOW):self.plan,_=register(self.directory)
        self.snapshot=dict(fixture_id='synthetic-future',fixture_start_utc=NOW+7200,feature_cutoff_utc=NOW+1,
            prediction_generated_at_utc=NOW+2,created_at_utc=NOW+3,source_data_time_utc=NOW+1,
            provider_fixture_ids=['401000999'],league='NBA',season='SYNTHETIC')
        self.pin=digest(self.snapshot)
        projection=dict(home=100.,away=90.,total=190.,margin=10.,quarters=[[25.,22.5]]*4,
            halves=[[50.,45.]]*2,winner=[.6,.1,.3])
        component=dict(status='AVAILABLE',prediction=projection,intervals=dict(status='UNSUPPORTED'))
        self.experiment=dict(snapshot_sha256=self.pin,prediction_cutoff_utc=NOW+1,history_available_max_utc=NOW,
            components={name:deepcopy(component) for name in NAMES})
        self.row=dict(fixture_id='synthetic-future',fixture_start_utc=NOW+7200,first_archived_at_utc=NOW+3,
            snapshot_sha256=self.pin,prediction_generated_at_utc=NOW+2,actual=None,
            league='NBA',season='SYNTHETIC',model_version='SYNTHETIC',model_digest='a'*64,
            actual_periods=dict(home=[25]*4,away=[20,20,25,25]),label_available_utc=NOW+20000)

    def capture(self,clock=NOW+5):
        with patch('time.time',return_value=clock),patch('hybrid_engine.challenger_forward.LedgerReports') as reader,\
             patch('hybrid_engine.challenger_forward.read_confirmed',return_value=[dict(snapshot=self.snapshot,snapshot_sha256=self.pin)]),\
             patch('hybrid_engine.challenger_forward.predict_snapshot',return_value=deepcopy(self.experiment)) as predictor:
            reader.return_value.read.return_value={'forecasts':[deepcopy(self.row)]}
            return capture(self.root/'native.sqlite',self.root/'assets',self.directory),predictor.call_count

    def report(self,clock):
        with patch('time.time',return_value=clock),patch('hybrid_engine.challenger_forward.LedgerReports') as reader:
            reader.return_value.read.return_value={'forecasts':[deepcopy(self.row)]}
            return performance(self.root/'native.sqlite',self.directory)

    def test_first_publication_is_preserved_and_repeat_does_not_recompute(self):
        a,calls=self.capture();self.assertEqual(calls,1);self.assertEqual(a['results'][0]['status'],'ARCHIVED')
        paths=list((self.directory/'forecasts').glob('first-*.json'));self.assertEqual(len(paths),1)
        before=paths[0].read_bytes();b,calls=self.capture(NOW+10)
        self.assertEqual(calls,0);self.assertEqual(b['skipped']['ALREADY_PUBLISHED_UNDER_PROTOCOL'],1)
        self.assertEqual(paths[0].read_bytes(),before)

    def test_pending_label_is_not_success_and_later_final_joins_without_forecast_rewrite(self):
        self.capture();r=self.report(NOW+6);self.assertEqual(r['settled'],0);self.assertEqual(r['pending'],1)
        before={p.name:p.read_bytes() for p in (self.directory/'forecasts').glob('*.json')}
        self.row['actual']=[100,90]
        r=self.report(NOW+20001);self.assertEqual(r['settled'],1);self.assertEqual(r['pending'],0)
        g=r['groups'][0];self.assertEqual(g['primary_statistical_gate'],'NOT_PROVEN')
        self.assertEqual(g['models']['UPDATED_BAYES_QMC']['n'],1)
        self.assertEqual({p.name:p.read_bytes() for p in (self.directory/'forecasts').glob('*.json')},before)

    def test_final_not_yet_available_cannot_count(self):
        self.capture();self.row['actual']=[100,90]
        r=self.report(NOW+10000);self.assertEqual(r['settled'],0);self.assertEqual(r['pending'],1)

    def test_after_tipoff_never_creates_new_forecast(self):
        r,calls=self.capture(NOW+7200);self.assertEqual(calls,0);self.assertEqual(r['eligible'],0)
        self.assertFalse(list((self.directory/'forecasts').glob('first-*.json')))

    def test_native_result_identity_mismatch_is_not_joined(self):
        self.capture();self.row['fixture_id']='different-fixture';self.row['actual']=[100,90]
        with self.assertRaisesRegex(ValueError,'RESULT_ORIGINAL_IDENTITY'):self.report(NOW+20001)

    def test_tampered_publication_fails_closed(self):
        self.capture();path=next((self.directory/'forecasts').glob('first-*.json'))
        w=json.loads(path.read_text());w['payload']['first_archived_at_utc']+=1;path.write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'PUBLICATION_PIN'):self.report(NOW+20001)

    def test_inference_failure_is_visible_and_does_not_publish_success(self):
        with patch('time.time',return_value=NOW+5),patch('hybrid_engine.challenger_forward.LedgerReports') as reader,\
             patch('hybrid_engine.challenger_forward.read_confirmed',return_value=[dict(snapshot=self.snapshot,snapshot_sha256=self.pin)]),\
             patch('hybrid_engine.challenger_forward.predict_snapshot',side_effect=ValueError('SYNTHETIC_INVALID_SOURCE')):
            reader.return_value.read.return_value={'forecasts':[self.row]}
            r=capture(self.root/'native.sqlite',self.root/'assets',self.directory)
        self.assertEqual(r['results'][0]['status'],'BLOCKED');self.assertFalse(list((self.directory/'forecasts').glob('first-*.json')))
