"""Manufactured prices/rules only; never a real bookmaker or Telegram E2E claim."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from core.team_identity import digest
from hybrid_engine.current_market_review import admit_odds,evaluate,CurrentReviewJournal
from hybrid_engine.current_market_render import render_batch
from hybrid_engine.decision_audit import trace_for
from hybrid_engine.decision_layer import DecisionDistribution,RuleEvidence
from hybrid_engine.distributions import gaussian_forecast
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.market_views import assess,render as old_render
from hybrid_engine.market_turkish import period,market,message
from hybrid_engine.provider_access import ProviderAccess
from hybrid_engine.provider_bridge import ProviderBridge,odds_observations,render as provider_render
from tests.test_provider_bridge import SNAPSHOT,NOW,FakeProvider,SECRET
from tests.test_provider_identity import discovery,detail


class CurrentReviewTests(unittest.TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.snap=deepcopy(SNAPSHOT);self.original=digest(self.snap)
        f=gaussian_forecast([112,109],[10,10],np.ones((4,2)),method='RQMC_HALTON')
        self.dist=DecisionDistribution(f,trace_for(self.snap))
        # This deliberately synthetic archive is separate from sealed real records.
        self.snap['intervals']=prediction_intervals(f)
        self.catalog=discovery();self.detail=detail()
        self.obs=odds_observations(self.detail,self.snap,discovery=self.catalog)[0][0]
        self.quotes=admit_odds(self.obs,self.snap,self.catalog,self.detail)

    def review(self,**kw):
        return evaluate(self.obs,self.dist,asof_utc=kw.pop('asof_utc',NOW),native_quotes=kw.pop('native_quotes',self.quotes),**kw)

    def rule(self,*,overtime=False,**changes):
        q=self.quotes[0].payload
        p=dict(format='EXPLICIT_BOOK_SETTLEMENT_V1',league=q['league'],bookmaker_id=q['bookmaker_id'],
            period=q['period'],market=q['market'],include_overtime=overtime,
            stake_rule='WHOLE_STAKE_WIN_LOSS_PUSH',tie_policy='PUSH',effective_from_utc=NOW-100,effective_until_utc=None)
        p.update(changes)
        doc=dict(status='DOCUMENT_RECEIVED',http_status=200,source_url='https://rules.synthetic.invalid/only-tests',
            observed_at_utc=NOW-1,ingested_at_utc=NOW,document=p,document_sha256=digest(p))
        return RuleEvidence.admit(doc,expected_url=doc['source_url'],trusted_document_sha256=doc['document_sha256'])

    def with_rule(self,rule):
        q=self.quotes[0].payload
        return {(q['bookmaker_id'],q['league'],q['period'],q['market']):rule}

    def batch(self,review=None):
        return CurrentReviewJournal(self.root/'decisions').record(self.snap,self.dist,[review or self.review()],decision_utc=NOW)

    def test_native_admission_replays_membership_and_keeps_600_second_cutoff(self):
        p=self.quotes[0].payload
        self.assertEqual(p['event_clock_binding']['payload']['delta_seconds'],600)
        self.assertEqual(p['event_clock_binding']['payload']['prematch_deadline_utc'],self.snap['fixture_start_utc'])
        self.assertEqual(p['native_quote_sha256'],self.obs['payload']['source']['native_quote_sha256'])

    def test_changed_line_rehashed_observation_not_accepted_as_native(self):
        o=deepcopy(self.obs);o['payload']['quotes'][0]['line']+=1;o['sha256']=digest(o['payload'])
        with self.assertRaisesRegex(ValueError,'NOT_IN_RECEIPTS'):admit_odds(o,self.snap,self.catalog,self.detail)

    def test_tampered_receipt_rejected(self):
        self.detail['document']['id']='tampered'
        with self.assertRaises(ValueError):admit_odds(self.obs,self.snap,self.catalog,self.detail)

    def test_later_price_uses_current_clock_without_retiming_original_forecast(self):
        old=assess(self.obs,self.dist,asof_utc=NOW)
        new=self.review();row=new['rows'][0]
        self.assertIn('SOURCE_AVAILABLE_AFTER_ORIGINAL_FORECAST',old['reasons'])
        self.assertIn('LATER_PRICE_CURRENT_REVIEW',row['information'])
        self.assertNotIn('SOURCE_AVAILABLE_AFTER_ORIGINAL_FORECAST',row['reasons'])
        self.assertEqual(new['prediction_utc'],SNAPSHOT['prediction_generated_at_utc'])
        self.assertEqual(new['decision_utc'],NOW)
        self.assertEqual(row['status'],'SETTLEMENT_RULE_UNVERIFIED')
        self.assertNotIn('NATIVE_PRICE_EVIDENCE_REQUIRED',row['reasons'])
        self.assertFalse(new['forecast_changed']);self.assertFalse(new['eligible_for_original_forecast_metrics'])

    def test_missing_rules_never_invent_ev_or_confidence(self):
        r=self.review();row=r['rows'][0]
        self.assertIsNone(row['expected_value']);self.assertIsNone(row['raw_contract_probabilities'])
        self.assertIsNone(row['confidence_index']);self.assertIsNone(row['recommended_direction'])
        self.assertFalse(r['selection_enabled']);self.assertEqual(r['calibration_status'],'NOT_CALIBRATED')
        self.assertAlmostEqual(sum(row['conditional_regulation_probabilities'].values()),1)

    def test_price_benchmarks_are_not_event_probabilities(self):
        b=self.review()['rows'][0]['price_benchmarks']
        self.assertAlmostEqual(b['break_even_conditional_on_no_push']['over'],1/1.95)
        self.assertTrue(b['not_true_event_probabilities']);self.assertFalse(b['settlement_scope_verified'])

    def test_missing_native_quote_blocks_raw_ev_even_with_synthetic_rule(self):
        r=self.review(native_quotes=[],rules=self.with_rule(self.rule()))['rows'][0]
        self.assertEqual(r['status'],'NATIVE_PRICE_EVIDENCE_REQUIRED');self.assertIsNone(r['expected_value'])

    def test_wrong_native_bookmaker_or_clock_is_rejected(self):
        from hybrid_engine.decision_layer import QuoteEvidence
        for k,v in [('bookmaker_id','OTHER'),('observed_at_utc',NOW-1),('observation_sha256','f'*64)]:
            p=dict(self.quotes[0].payload,**{k:v});q=QuoteEvidence(p,digest(p))
            with self.subTest(k=k),self.assertRaisesRegex(ValueError,'NATIVE_SCOPE_CONFLICT'):self.review(native_quotes=[q])

    def test_synthetic_verified_regulation_rule_permits_only_raw_math(self):
        r=self.review(rules=self.with_rule(self.rule()));row=r['rows'][0];mass=row['raw_contract_probabilities']
        self.assertIsNotNone(row['expected_value']);self.assertTrue(row['price_benchmarks']['settlement_scope_verified'])
        self.assertAlmostEqual(row['expected_value']['over'],mass['over']*.95-mass['under'])
        self.assertIsNone(row['calibrated_probabilities']);self.assertIsNone(r['confidence_index'])
        self.assertFalse(r['selection_enabled']);self.assertIn('NO_APPROVED_DISJOINT_CALIBRATION',row['reasons'])

    def test_verified_ot_rule_without_ot_samples_is_blocked(self):
        row=self.review(rules=self.with_rule(self.rule(overtime=True)))['rows'][0]
        self.assertEqual(row['status'],'NO_VERIFIED_OVERTIME_SIMULATION_PATHS');self.assertIsNone(row['expected_value'])

    def test_rule_for_other_book_or_future_effective_date_not_accepted(self):
        for c in [dict(bookmaker_id='OTHER'),dict(effective_from_utc=NOW+1),dict(effective_until_utc=NOW)]:
            with self.subTest(c=c):
                row=self.review(rules=self.with_rule(self.rule(**c)))['rows'][0]
                self.assertIn('RULE_SCOPE_OR_TIME_CONFLICT',row['reasons']);self.assertIsNone(row['expected_value'])

    def test_rule_pin_tampering_refused(self):
        r=self.rule();r.payload['include_overtime']=True
        with self.assertRaisesRegex(ValueError,'RULE_PIN'):self.review(rules=self.with_rule(r))

    def test_stale_price_and_publisher_clocks_block_current_ev(self):
        with patch('time.time',return_value=NOW+301):row=self.review(asof_utc=NOW+301)['rows'][0]
        self.assertIn('STALE_AT_DECISION_TIME',row['reasons'])
        self.assertIn('STALE_PUBLISHER_PRICE_AT_DECISION_TIME',row['reasons']);self.assertIsNone(row['expected_value'])

    def test_before_forecast_and_future_review_clocks_refused(self):
        for ts in [SNAPSHOT['prediction_generated_at_utc']-1,NOW+1,True]:
            with self.subTest(ts=ts),self.assertRaisesRegex(ValueError,'TIME_INVALID'):self.review(asof_utc=ts)

    def test_earliest_official_start_blocks_current_decision(self):
        start=self.snap['fixture_start_utc']
        with patch('time.time',return_value=start):row=self.review(asof_utc=start)['rows'][0]
        self.assertIn('POST_TIPOFF_ARCHIVE_REVIEW_ONLY',row['reasons']);self.assertIsNone(row['expected_value'])

    def test_integer_push_is_not_lost_in_ev_or_break_even(self):
        d=deepcopy(self.detail)
        for o in d['document']['bookmakers'][0]['markets'][0]['outcomes']:o['point']=221
        d['document_sha256']=digest(d['document']);self.obs=odds_observations(d,self.snap,discovery=self.catalog)[0][0]
        self.quotes=admit_odds(self.obs,self.snap,self.catalog,d)
        row=self.review(rules=self.with_rule(self.rule()))['rows'][0];m=row['raw_contract_probabilities']
        self.assertGreater(m['push'],0)
        self.assertAlmostEqual(row['expected_value']['over'],m['over']*.95-m['under'])
        self.assertAlmostEqual(row['break_even_unconditional_win_probability']['over'],(1-m['push'])/1.95)

    def test_no_edge_does_not_hide_raw_numeric_forecast_or_tilt(self):
        d=deepcopy(self.detail)
        for o in d['document']['bookmakers'][0]['markets'][0]['outcomes']:o['price']=1.01
        d['document_sha256']=digest(d['document']);self.obs=odds_observations(d,self.snap,discovery=self.catalog)[0][0]
        self.quotes=admit_odds(self.obs,self.snap,self.catalog,d)
        r=self.review(rules=self.with_rule(self.rule()));row=r['rows'][0]
        self.assertEqual(row['status'],'NO_EDGE');self.assertLessEqual(max(row['expected_value'].values()),0)
        text=render_batch(self.batch(r));self.assertIn('NO_EDGE',text);self.assertIn('Ham normal süre:',text)
        self.assertIn('Model eğilimi (öneri değil):',text);self.assertIsNone(row['recommended_direction'])

    def test_quarter_asian_line_not_treated_as_simple_whole_stake(self):
        d=deepcopy(self.detail)
        for o in d['document']['bookmakers'][0]['markets'][0]['outcomes']:o['point']=221.25
        d['document_sha256']=digest(d['document']);self.obs=odds_observations(d,self.snap,discovery=self.catalog)[0][0]
        self.quotes=admit_odds(self.obs,self.snap,self.catalog,d)
        row=self.review(rules=self.with_rule(self.rule()))['rows'][0]
        self.assertIn('SPLIT_STAKE_ASIAN_QUARTER_LINE_UNSUPPORTED',row['reasons']);self.assertIsNone(row['expected_value'])

    def test_batch_has_actual_record_time_and_preserves_forecast_digest(self):
        before=digest(self.snap);batch=self.batch();p=batch['payload']
        self.assertEqual(p['original_snapshot_sha256'],before);self.assertEqual(digest(self.snap),before)
        self.assertEqual(p['recorded_at_utc'],NOW);self.assertEqual(p['record_class'],'PREGAME_CURRENT_REVIEW')
        self.assertFalse(p['eligible_for_current_prematch_metrics']);self.assertFalse(p['eligible_for_original_forecast_metrics'])
        self.assertEqual(batch['sha256'],digest(p))

    def test_identical_current_decision_is_idempotent_not_rearchived(self):
        first=self.batch();files={p:p.read_bytes() for p in (self.root/'decisions').iterdir()}
        with patch('time.time',return_value=NOW+1):second=self.batch(self.review())
        self.assertEqual(first,second);self.assertEqual(files,{p:p.read_bytes() for p in files})

    def test_corrupt_current_record_fails_without_overwriting(self):
        self.batch();path=next((self.root/'decisions').glob('*.json'));path.write_text('{}');before=path.read_bytes()
        with self.assertRaises((ValueError,KeyError)):self.batch()
        self.assertEqual(path.read_bytes(),before)

    def test_actual_record_after_start_is_never_prematch(self):
        r=self.review()
        with patch('time.time',return_value=self.snap['fixture_start_utc']):batch=self.batch(r)
        self.assertEqual(batch['payload']['record_class'],'POST_TIPOFF_REVIEW_ONLY')
        self.assertIn('yeni maç öncesi karar sayılmaz',render_batch(batch))

    def test_changed_sample_paths_do_not_enter_archive(self):
        self.snap['intervals']['sample_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'SAMPLE_PIN'):self.batch()
        self.assertFalse((self.root/'decisions').exists())

    def test_other_fixture_or_decision_cannot_enter_same_batch(self):
        for k,v in [('decision_utc',NOW-1),('model_digest','f'*64)]:
            r=self.review();r[k]=v
            with self.subTest(k=k),self.assertRaisesRegex(ValueError,'BATCH_SCOPE'):self.batch(r)

    def test_symlinked_journal_directory_refused(self):
        target=self.root/'actual';target.mkdir();link=self.root/'link';link.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):CurrentReviewJournal(link)

    def test_disk_error_is_not_a_successful_archive_write(self):
        with patch('hybrid_engine.current_market_review.publish_json',side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError):self.batch()
        self.assertFalse(list((self.root/'decisions').glob('review-*.json')))

    def test_journal_storage_budget_refuses_without_deleting_old_records(self):
        directory=self.root/'decisions';directory.mkdir()
        for i in range(256):(directory/f'review-{i:064x}.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'STORAGE_BUDGET'):self.batch()
        self.assertEqual(len(list(directory.iterdir())),256)
        self.assertTrue(all(p.read_text()=='{}' for p in directory.iterdir()))

    def test_journal_does_not_write_sqlite_or_other_existing_files(self):
        existing=self.root/'research.sqlite';existing.write_bytes(b'SYNTHETIC_SENTINEL_NOT_A_DATABASE')
        before=existing.read_bytes();self.batch()
        self.assertEqual(existing.read_bytes(),before)
        self.assertEqual({p.suffix for p in (self.root/'decisions').iterdir()},{'.json'})

    def test_wrong_original_trace_is_rejected_before_file_write(self):
        self.dist.trace['prediction_utc']-=1
        with self.assertRaisesRegex(ValueError,'ORIGINAL_TRACE_PIN'):self.batch()
        self.assertFalse((self.root/'decisions').exists())

    def test_four_real_brand_spellings_preserved_in_turkish_rows(self):
        for brand in ('FanDuel','BetOnline.ag','LowVig.ag','DraftKings'):
            r=self.review();r['bookmaker']['name']=brand;batch=self.batch(r);text=render_batch(batch)
            self.assertIn('Bahis platformu: '+brand,text)
            self.assertIn('Oran sağlayıcısı: The Odds API',text)
            self.assertIn('Maçın tamamı · Toplam sayı · 221.5',text)
            self.assertIn('Ödeme ve uzatma kuralı doğrulanmadı',text)
            self.assertNotIn('SETTLEMENT_RULE_UNVERIFIED',text)
            self.assertIn('NOT_CALIBRATED',text);self.assertIn('Karar SHA:',text)

    def test_legacy_archive_render_is_turkish_without_changing_machine_keys(self):
        v=assess(self.obs,self.dist,asof_utc=NOW);before=digest(v);text=old_render(v)
        self.assertIn('Maçın tamamı · Toplam sayı',text);self.assertNotIn('FULL · TOTAL',text)
        self.assertIn('Fiyat ilk tahminden sonra alındı',text);self.assertEqual(digest(v),before)

    def test_every_supported_period_and_market_has_turkish_label(self):
        for p in ('FULL','1Q','2Q','3Q','4Q','1H','2H'):self.assertNotIn('doğrulanamadı',period(p))
        for m in ('TOTAL','HOME','AWAY','HOME_HANDICAP','WINNER'):self.assertNotIn('doğrulanamadı',market(m))
        self.assertEqual(message('UNKNOWN'),'Doğrulama tamamlanamadı')

    def test_provider_receipt_loader_rejects_traversal_and_changed_content(self):
        bridge=ProviderBridge(ProviderAccess({}),self.root/'receipts')
        pin=bridge._save(self.detail);self.assertEqual(bridge.read_receipt(pin),self.detail)
        with self.assertRaises(ValueError):bridge.read_receipt('../secret')
        p=bridge.root/('provider-'+pin+'.json');p.write_text(json.dumps(dict(payload={},sha256=pin)))
        with self.assertRaisesRegex(ValueError,'PIN_CONFLICT'):bridge.read_receipt(pin)

    def test_provider_receipt_symlink_never_read(self):
        b=ProviderBridge(ProviderAccess({}),self.root/'receipts');b.root.mkdir()
        native=self.root/'elsewhere.json';native.write_text('{}');pin='f'*64
        (b.root/('provider-'+pin+'.json')).symlink_to(native)
        with self.assertRaises(ValueError):b.read_receipt(pin)

    def test_provider_status_translates_but_report_codes_stay_unchanged(self):
        b=ProviderBridge(ProviderAccess({'THE_ODDS_API':SECRET},getter=FakeProvider(),clock=lambda:NOW),self.root/'providers',clock=lambda:NOW)
        report=b.collect(self.snap);before=digest(report);text=provider_render(report)
        self.assertIn('The Odds API: Gerçek fiyatlar alındı',text);self.assertEqual(before,digest(report))
        self.assertEqual(report['providers']['THE_ODDS_API']['status'],'OBSERVED_RULES_AND_CALIBRATION_PENDING')


if __name__=='__main__':unittest.main()
