"""Synthetic delivery mechanics and pinned postgame audits, not real Telegram proof."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,patch

import numpy as np

from core.team_identity import digest
from hybrid_engine.euroleague_error_audit import timing_eligibility,error_cells,allocation_diagnostics,box_diagnostics,audit
from hybrid_engine.frozen_archive import FrozenArchive,read_gzip
from hybrid_engine.data import Cut,Abstain
from hybrid_engine.forward_validation import ForwardRegistry,verified_catalog
from hybrid_engine.forward_nba_results import read_confirmed,report_euroleague
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.prospective_results import ProspectiveResults,OFFICIAL
from hybrid_engine.telegram_evidence import evidence_report,official_endpoint,plaintext
from hybrid_engine.test_bot import AuditedRequest
from hybrid_engine.quarter_shadow import predict as quarter_shadow,fit_rows
from telegram_delivery import DeliveryJournal

REPO=Path(__file__).resolve().parents[1]
ARCHIVE=REPO/'docs/prospective/euroleague-20261112'
NATIVE=REPO/'docs/evidence/phase845-euroleague-native-20261113.json.gz'


def native():
    with gzip.open(NATIVE,'rt') as f:return json.load(f)['receipts']


def events():
    # Explicitly manufactured transport records for verifier logic only.
    command=dict(kind='COMMAND_RECEIVED',update_id=7,command='/analyze',chat_id=17,is_bot=False,user_message_at_utc=100)
    accepted=dict(kind='DELIVERY_ACCEPTED',update_id=7,chat_id=17,telegram_message_id=19,telegram_sent_at_utc=101,ack_at_utc=102,
        transport='OFFICIAL_TELEGRAM_BOT_API',dedicated_bot_identity_verified=True,expected_chat_matches=True,
        response_content_matches_request=True,message_sha256='synthetic',response_sha256='synthetic')
    return [command,accepted]


class EvidenceTests(TestCase):
    def test_user_report_does_not_invent_api_chat_or_clock_evidence(self):
        r=evidence_report([],user_report=dict(reported_games=5,reported_date='2026-11-13'),asof_utc=200)
        self.assertEqual(r['status'],'USER_REPORTED_TECHNICAL_E2E_BLOCKED');self.assertEqual(r['api_verified_messages'],0)
        self.assertFalse(r['actual_telegram_delivery_verified'])

    def test_screenshot_is_visual_evidence_not_api_proof(self):
        r=evidence_report([],screenshots=[dict(artifact_sha256='synthetic',visible_fields={'text':'visible only'})],asof_utc=200)
        self.assertEqual(len(r['screenshot_evidence']),1);self.assertFalse(r['actual_telegram_delivery_verified'])

    def test_mock_and_missing_transport_are_never_real_delivery(self):
        for transport in ('LOCAL_HTTP_BOT_API_DOUBLE','MOCK_OR_UNATTESTED_ENDPOINT',None):
            with self.subTest(transport=transport):
                e=events();e[1]['transport']=transport;r=evidence_report(e,asof_utc=200)
                self.assertEqual(r['api_verified_messages'],0)

    def test_synthetic_schema_can_verify_all_separate_requirements(self):
        r=evidence_report(events(),asof_utc=200);self.assertEqual(r['api_verified_messages'],1)
        self.assertFalse(r['complete_command_suite_verified']);self.assertNotIn('chat_id',r['api_verified'][0])

    def test_wrong_chat_bot_content_or_future_clock_fails_closed(self):
        for changes in ({'chat_id':18},{'dedicated_bot_identity_verified':False},{'response_content_matches_request':False},
            {'expected_chat_matches':False},{'ack_at_utc':201},{'telegram_sent_at_utc':True},{'telegram_message_id':0}):
            with self.subTest(changes=changes):
                e=events();e[1].update(changes);self.assertFalse(evidence_report(e,asof_utc=200)['actual_telegram_delivery_verified'])

    def test_bot_self_message_does_not_prove_human_e2e(self):
        e=events();e[0]['is_bot']=True;self.assertFalse(evidence_report(e,asof_utc=200)['actual_telegram_delivery_verified'])

    def test_endpoint_does_not_trust_hostname_prefix_or_http_or_other_bot(self):
        self.assertTrue(official_endpoint('https://api.telegram.org/bot123:TEST/sendMessage',123,'sendMessage'))
        for url in ('http://api.telegram.org/bot123:TEST/sendMessage','https://api.telegram.org.evil.test/bot123:TEST/sendMessage',
            'https://api.telegram.org/bot124:TEST/sendMessage','https://api.telegram.org/bot123:TEST/sendMessage?x=1'):
            self.assertFalse(official_endpoint(url,123,'sendMessage'))

    def test_html_integrity_uses_server_plaintext_not_raw_markup(self):
        self.assertEqual(plaintext('<b>A &amp; B</b>\n&lt;x&gt;','HTML'),'A & B\n<x>')

    def test_partial_analysis_message_is_not_complete_delivery(self):
        e=events();e.append(dict(record_type='TELEGRAM_ANALYSIS_DELIVERY',update_id=7,status='TELEGRAM_ACCEPTED',
            part_count=2,part_index=0,telegram_message_id=19))
        self.assertEqual(evidence_report(e,asof_utc=200)['complete_analysis_updates'],[])
        e[-1]['part_count']=1;self.assertEqual(evidence_report(e,asof_utc=200)['complete_analysis_updates'],[7])


class APIAuditTests(IsolatedAsyncioTestCase):
    async def test_patched_http_receipt_requires_getme_and_checks_server_text(self):
        # No network call: this tests the recorder, not Telegram delivery.
        with TemporaryDirectory() as tmp:
            journal=DeliveryJournal(Path(tmp)/'delivery.sqlite')
            config=dict(bot_id=123,username='example_test_bot',chat_id=17)
            request=AuditedRequest(journal,expected_identity=config)
            me=dict(ok=True,result=dict(id=123,username='example_test_bot',is_bot=True))
            sent=dict(ok=True,result=dict(date=101,message_id=5,chat={'id':17},text='A & B'))
            with patch('telegram.request.HTTPXRequest.do_request',new=AsyncMock(side_effect=[(200,json.dumps(me).encode()),(200,json.dumps(sent).encode())])):
                await request.do_request('https://api.telegram.org/bot123:TEST/getMe','POST')
                await request.do_request('https://api.telegram.org/bot123:TEST/sendMessage','POST',
                    request_data=SimpleNamespace(parameters=dict(text='<b>A &amp; B</b>',parse_mode='HTML')))
            e=journal.read()[0];self.assertTrue(e['dedicated_bot_identity_verified']);self.assertTrue(e['response_content_matches_request'])
            self.assertNotIn('TEST',json.dumps(e));await request.shutdown()

    async def test_loopback_send_stays_mock_even_with_success_body(self):
        with TemporaryDirectory() as tmp:
            journal=DeliveryJournal(Path(tmp)/'delivery.sqlite');request=AuditedRequest(journal)
            response=dict(ok=True,result=dict(date=101,message_id=5,chat={'id':17},text='x'))
            with patch('telegram.request.HTTPXRequest.do_request',new=AsyncMock(return_value=(200,json.dumps(response).encode()))):
                await request.do_request('http://127.0.0.1:10/bot123:TEST/sendMessage','POST')
            e=journal.read()[0];self.assertEqual(e['transport'],'MOCK_OR_UNATTESTED_ENDPOINT')
            self.assertFalse(e['dedicated_bot_identity_verified']);await request.shutdown()


class EuroleagueTests(TestCase):
    @classmethod
    def setUpClass(cls):cls.archive=FrozenArchive(ARCHIVE);cls.receipts=native();cls.receipt=cls.receipts[OFFICIAL]

    def test_unknown_generation_and_archive_times_exclude_strict_success(self):
        for r in self.archive.records.values():self.assertFalse(timing_eligibility(r)['strict_pregame_eligible'])

    def test_proven_generation_and_capture_do_not_allow_late_archiving(self):
        r=deepcopy(next(iter(self.archive.records.values())));tip=r['fixture']['start_ts_utc']
        r.update(prediction_generated_at_utc=r['created_at_utc']-1,first_archived_at_utc=r['created_at_utc']+1)
        self.assertTrue(timing_eligibility(r)['strict_pregame_eligible'])
        r['first_archived_at_utc']=tip;self.assertFalse(timing_eligibility(r)['strict_pregame_eligible'])

    def test_five_fresh_finals_and_period_errors_are_matched_without_refit(self):
        with TemporaryDirectory() as tmp:
            results=ProspectiveResults(self.archive,tmp);results.ingest(self.receipt)
            report=audit(self.archive,results,box_receipts=list(self.receipts.values()))
            self.assertEqual(report['descriptive_games'],5);self.assertEqual(report['strict_pregame_performance_games'],0)
            self.assertFalse(report['calibration_fit']);self.assertFalse(report['ensemble_fit'])
            by_id={r['provider_fixture_id']:r for r in report['rows']}
            self.assertEqual(sum(by_id['E2026_106']['actual_regulation']),189)
            self.assertAlmostEqual(by_id['E2026_103']['components']['BAYES_QMC']['total_error'],26.490045509842,places=9)
            self.assertEqual(report['coverage']['BAYES_QMC']['markets']['TOTAL']['P25_P75']['hits'],3)
            self.assertEqual(report['coverage']['BAYES_QMC']['markets']['TOTAL']['P10_P90']['hits'],4)
            self.assertEqual(report['coverage']['BAYES_QMC']['markets']['TOTAL']['P05_P95']['hits'],5)
            self.assertFalse(report['comparison']['superiority_claim'])

    def test_score_period_and_margin_errors_reconcile(self):
        r=next(iter(self.archive.records.values()));p=r['models']['BAYES_QMC']['prediction']
        periods={'home':[20,22,24,26],'away':[21,23,25,27]};v=error_cells(p,periods)
        self.assertAlmostEqual(sum(v['quarter_total_errors']),v['total_error'])
        self.assertAlmostEqual(sum(v['half_total_errors']),v['total_error'])
        self.assertAlmostEqual(v['home_error']-v['away_error'],v['margin_error'])

    def test_incoherent_periods_are_not_silently_reconciled(self):
        p=deepcopy(next(iter(self.archive.records.values()))['models']['BAYES_QMC']['prediction']);p['home']+=1
        with self.assertRaisesRegex(ValueError,'INCOHERENT'):error_cells(p,{'home':[20]*4,'away':[20]*4})

    def test_real_q1_outlier_is_visible_not_removed_or_recalibrated(self):
        r=next(r for r in self.archive.records.values() if r['fixture']['home_team_id']=='MAD')
        cut=Cut(**read_gzip(ARCHIVE/('inputs-'+r['input_file_sha256']+'.json.gz')))
        q=allocation_diagnostics(self.archive.replay(r),cut,{'home':[38,18,26,23],'away':[20,21,18,25]})
        self.assertTrue(q['teams']['home']['actual_outside_p05_p95'][0]);self.assertFalse(q['model_parameters_changed'])

    def test_postgame_box_decomposition_is_exact_and_not_pregame_input(self):
        r=next(r for r in self.archive.records.values() if r['fixture']['home_team_id']=='TEL')
        cut=Cut(**read_gzip(ARCHIVE/('inputs-'+r['input_file_sha256']+'.json.gz')))
        with TemporaryDirectory() as tmp:
            results=ProspectiveResults(self.archive,tmp);results.ingest(self.receipt);o=results.outcomes()[r['fixture']['canonical_id']]
            url=OFFICIAL+'/103/stats';b=box_diagnostics(r,cut,o,self.receipts[url])
            self.assertAlmostEqual(b['pace_term']+b['efficiency_term'],153-b['possession_baseline_total'])
            self.assertGreater(b['actual_estimated_pace'],b['possession_baseline_pace'])
            self.assertFalse(b['used_for_pregame_forecast'])


class ForwardTests(TestCase):
    def payload(self):
        return dict(fixture=dict(canonical_id='synthetic',start_ts_utc=200),version='SYNTHETIC',actual=None,
            source_available_max_utc=90,prediction_generated_at_utc=95,assets=[],components={})

    def test_first_capture_is_idempotent_and_original_bytes_remain(self):
        with TemporaryDirectory() as tmp,patch('time.time',return_value=100):
            registry=ForwardRegistry(tmp);p,new=registry.record(self.payload());self.assertTrue(new)
            before={f.name:f.read_bytes() for f in Path(tmp).iterdir()};p2,new=registry.record(self.payload())
            self.assertFalse(new);self.assertEqual(p,p2);self.assertEqual(before,{f.name:f.read_bytes() for f in Path(tmp).iterdir()})

    def test_tipoff_or_target_label_cannot_be_prematch(self):
        for now,changes in ((200,{}),(100,{'actual':[100,90]}),(100,{'source_available_max_utc':101})):
            with self.subTest(now=now,changes=changes),TemporaryDirectory() as tmp,patch('time.time',return_value=now):
                p=self.payload();p.update(changes)
                with self.assertRaises(ValueError):ForwardRegistry(tmp).record(p)

    def test_publication_crossing_tipoff_is_excluded(self):
        with TemporaryDirectory() as tmp,patch('time.time',side_effect=[199,200]):
            registry=ForwardRegistry(tmp);registry.record(self.payload());row=registry.records()[0]
            self.assertFalse(row['publication']['eligible_for_prospective_audit']);self.assertEqual(row['publication']['classification'],'LATE_COMMIT_EXCLUDED')

    def test_corrupted_forecast_or_publication_hash_is_refused(self):
        for prefix in ('forecast-','first-'):
            with self.subTest(prefix=prefix),TemporaryDirectory() as tmp,patch('time.time',return_value=100):
                registry=ForwardRegistry(tmp);registry.record(self.payload());f=next(Path(tmp).glob(prefix+'*.json'))
                data=json.loads(f.read_text());data['changed']=True
                if prefix=='forecast-':data['actual']=[100,90]
                else:data['payload']['first_archived_at_utc']=99
                f.write_text(json.dumps(data))
                with self.assertRaises(ValueError):registry.records()

    def test_asset_cannot_escape_archive_or_use_mutated_content(self):
        with TemporaryDirectory() as tmp:
            r=ForwardRegistry(tmp);ref=r.asset('input',{'x':1});self.assertEqual(r.read_asset(ref),{'x':1})
            with self.assertRaises(ValueError):r.read_asset(dict(file='../foreign',sha256=ref['sha256']))
            (Path(tmp)/ref['file']).write_text('{"x":2}')
            with self.assertRaises(ValueError):r.read_asset(ref)

    def test_fresh_source_checks_real_clock_and_does_not_backdate(self):
        receipt=native()[OFFICIAL];now=receipt['ingested_at_utc']
        with patch('time.time',return_value=now):self.assertTrue(verified_catalog(receipt)['payload']['fixtures'])
        with patch('time.time',return_value=now+301),self.assertRaisesRegex(ValueError,'FRESH'):verified_catalog(receipt)
        with patch('time.time',return_value=now-1),self.assertRaisesRegex(ValueError,'FRESH'):verified_catalog(receipt)

    def test_official_final_matching_is_append_only_idempotent_and_not_training(self):
        receipt=native()[OFFICIAL];archive=FrozenArchive(ARCHIVE)
        record=next(r for r in archive.records.values() if r['fixture']['home_team_id']=='MAD');g=record['fixture']
        with TemporaryDirectory() as tmp:
            registry=ForwardRegistry(tmp);p=self.payload();p.update(fixture=g,
                source_available_max_utc=g['start_ts_utc']-120,prediction_generated_at_utc=g['start_ts_utc']-110,
                components={n:dict(m,intervals=prediction_intervals(archive.replay(record,n))) for n,m in record['models'].items()})
            with patch('time.time',return_value=g['start_ts_utc']-100):registry.record(p)
            pin=digest(registry.records()[0]['payload'])
            self.assertEqual(report_euroleague(registry)['pending'],1)
            with patch('time.time',return_value=receipt['ingested_at_utc']):
                self.assertEqual(registry.settle(receipt)[0]['status'],'VERIFIED_FINAL_APPENDED')
                self.assertEqual(registry.settle(receipt)[0]['status'],'ALREADY_VERIFIED')
            result=json.loads(next(Path(tmp).glob('outcome-*.json')).read_text())['payload']
            self.assertEqual(result['full_final'],[105,84]);self.assertFalse(result['calibration_fit'])
            self.assertEqual(digest(registry.records()[0]['payload']),pin)
            report=report_euroleague(registry);self.assertEqual(report['pending'],0)
            self.assertEqual(report['metrics']['BAYES_QMC']['n'],1)

    def test_nba_commit_proof_is_read_only_and_rejects_hash_or_clock_conflict(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'nba.sqlite';snapshot=dict(league='NBA',prediction_generated_at_utc=90,created_at_utc=91,fixture_start_utc=200)
            with sqlite3.connect(p) as db:
                db.executescript('CREATE TABLE live_analysis_snapshots (league TEXT,fixture_id TEXT,model_digest TEXT,payload TEXT,sha256 TEXT); CREATE TABLE live_analysis_commit_receipts (league TEXT,fixture_id TEXT,model_digest TEXT,snapshot_sha256 TEXT,completed_utc INTEGER);')
                db.execute('INSERT INTO live_analysis_snapshots VALUES(?,?,?,?,?)',('NBA','s','m',json.dumps(snapshot),digest(snapshot)))
                db.execute('INSERT INTO live_analysis_commit_receipts VALUES(?,?,?,?,?)',('NBA','s','m',digest(snapshot),92))
            before=p.read_bytes();self.assertEqual(read_confirmed(p)[0]['snapshot'],snapshot);self.assertEqual(p.read_bytes(),before)
            with sqlite3.connect(p) as db:db.execute('UPDATE live_analysis_commit_receipts SET completed_utc=200')
            with self.assertRaisesRegex(ValueError,'CLOCK'):read_confirmed(p)
            with sqlite3.connect(p) as db:db.execute('UPDATE live_analysis_commit_receipts SET snapshot_sha256="corrupt"')
            with self.assertRaisesRegex(ValueError,'PIN'):read_confirmed(p)


class QuarterShadowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive=FrozenArchive(ARCHIVE);cls.record=next(iter(cls.archive.records.values()))
        cls.cut=Cut(**read_gzip(ARCHIVE/('inputs-'+cls.record['input_file_sha256']+'.json.gz')))
        cls.forecast=cls.archive.replay(cls.record)

    def test_all_original_scores_and_point_periods_are_preserved(self):
        f=quarter_shadow(self.forecast,self.cut)
        from hybrid_engine.intervals import sample_paths
        np.testing.assert_array_equal(f.samples.sum(axis=1),sample_paths(self.forecast).sum(axis=1))
        np.testing.assert_array_equal(f.quarter_means,self.forecast.quarter_means)
        np.testing.assert_array_equal(f.samples[:,:2].sum(axis=1)+f.samples[:,2:].sum(axis=1),f.samples.sum(axis=1))

    def test_seed_and_actual_quantiles_are_repeatable(self):
        a=quarter_shadow(self.forecast,self.cut);b=quarter_shadow(self.forecast,self.cut)
        self.assertEqual(prediction_intervals(a),prediction_intervals(b))
        for key in ('TOTAL','HOME','AWAY','MARGIN'):
            self.assertEqual(prediction_intervals(a)['markets'][key],prediction_intervals(self.forecast)['markets'][key])

    def test_future_history_and_target_label_are_rejected(self):
        from dataclasses import replace
        for change in ({'fixture_id':self.cut.target['fixture_id']},{'ingested_at_utc':self.cut.cutoff_utc+1,'observed_at_utc':self.cut.cutoff_utc+1}):
            row=dict(self.cut.history[0],**change)
            with self.subTest(change=change),self.assertRaises(ValueError):quarter_shadow(self.forecast,replace(self.cut,history=(row,)+tuple(self.cut.history[1:])))

    def test_target_result_cannot_change_an_earlier_candidate(self):
        from dataclasses import replace
        changed=dict(self.cut.target,final_scores=[200,20],periods={'home':[50]*4,'away':[5]*4})
        a=quarter_shadow(self.forecast,self.cut);b=quarter_shadow(self.forecast,replace(self.cut,target=changed))
        np.testing.assert_array_equal(a.samples,b.samples)

    def test_insufficient_history_abstains_instead_of_fabricating_dispersion(self):
        from dataclasses import replace
        with self.assertRaises(Abstain):quarter_shadow(self.forecast,replace(self.cut,history=()))

    def test_shadow_is_never_presented_as_calibrated_or_production(self):
        f=quarter_shadow(self.forecast,self.cut)
        self.assertFalse(f.metadata['production_enabled']);self.assertFalse(f.metadata['confirmatory'])
        self.assertEqual(f.metadata['calibration_status'],'UNCALIBRATED')

    def test_fold_fit_restores_earlier_receipt_version_instead_of_later_target_cut(self):
        row=self.cut.history[0];fit=row['fixture_start_utc']+100
        early=dict(row,observed_at_utc=fit-1,ingested_at_utc=fit-1)
        later=dict(row,observed_at_utc=fit+10,ingested_at_utc=fit+10)
        restored=fit_rows([[early,later]],self.cut.target,fit)
        self.assertEqual(len(restored),1);self.assertEqual(restored[0]['ingested_at_utc'],fit-1)
