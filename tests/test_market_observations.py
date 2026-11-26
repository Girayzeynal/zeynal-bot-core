"""Synthetic market/image cases and exact frozen-source replay, not real E2E."""
import base64
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from core.team_identity import digest
from hybrid_engine.decision_layer import DecisionDistribution,QuoteEvidence,RuleEvidence
from hybrid_engine.distributions import gaussian_forecast
from hybrid_engine.market_observations import ObservationStore,from_espn,fixture_identity,MAX_FILES
from hybrid_engine.market_views import assess,render,replay_nba
from hybrid_engine.market_panels import nba_panel,euroleague_panel
from hybrid_engine.observed_markets import observe_espn
from hybrid_engine.market_evidence_report import observed_market_evidence
from tests.test_observed_markets import receipt
from tests.test_season_archive_audit import NOW

ROOT=Path(__file__).resolve().parents[1]
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDfoAAAAASUVORK5CYII=')


def setup_native(*,price=None):
    r=receipt()
    if price is not None:
        for side in ('over','under'):
            r['document']['events'][0]['competitions'][0]['odds'][0]['total'][side]['close']['odds']=price
        r['document_sha256']=digest(r['document'])
    observed=observe_espn(r,now_utc=NOW)['quotes'][0]
    batch=from_espn(observed,r);fixture=batch['payload']['fixture']
    f=gaussian_forecast([110,100],[10,10],np.ones((4,2)),method='RQMC_HALTON')
    trace=dict(fixture,prediction_utc=NOW,inputs_available_max_utc=NOW-5,model_version='SYNTHETIC_ONLY',model_digest='a'*64)
    return r,observed,batch,DecisionDistribution(f,trace)


def manual_input(fixture):
    return dict(fixture=deepcopy(fixture),bookmaker=dict(id='synthetic-manual-book',name='SYNTHETIC TEST ONLY'),
        source=dict(provider_id='USER_SCREENSHOT',provider_name='SYNTHETIC USER INPUT',url=None,
                    captured_at_utc=NOW-10,published_at_utc=None),
        quotes=[dict(period='FULL',market='TOTAL',line=210.5,prices=dict(under=1.9,over=1.9)),
                dict(period='FULL',market='TOTAL',line=220.5,prices={}),
                dict(period='1Q',market='TOTAL',line=55.5,prices={})])


def rule_for(native,*,overtime=False):
    p=native.payload
    doc=dict(format='EXPLICIT_BOOK_SETTLEMENT_V1',league=p['league'],bookmaker_id=p['bookmaker_id'],
        period=p['period'],market=p['market'],include_overtime=overtime,
        stake_rule='WHOLE_STAKE_WIN_LOSS_PUSH',tie_policy='PUSH',effective_from_utc=NOW-1000,effective_until_utc=None)
    r=dict(status='DOCUMENT_RECEIVED',http_status=200,source_url='https://rules.synthetic.invalid/settlement',
        observed_at_utc=NOW-10,ingested_at_utc=NOW-9,document=doc,document_sha256=digest(doc))
    return RuleEvidence.admit(r,expected_url=r['source_url'],trusted_document_sha256=r['document_sha256'])


class ObservationStoreTests(TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.image=self.root/'synthetic.png';self.image.write_bytes(PNG)
        _,_,native,self.distribution=setup_native()
        self.input=manual_input(native['payload']['fixture']);self.store=ObservationStore(self.root/'observations')

    def save(self,doc=None):
        return self.store.import_screenshot(self.input if doc is None else doc,self.image)

    def test_constructor_and_missing_read_do_not_create_files(self):
        self.assertFalse(self.store.root.exists())
        self.assertEqual(self.store.read(self.input['fixture'],asof_utc=NOW),[])
        self.assertFalse(self.store.root.exists())

    def test_alternative_lines_are_preserved_and_book_source_separate(self):
        w=self.save();p=w['payload']
        self.assertEqual(len(p['quotes']),3)
        self.assertEqual({q['line'] for q in p['quotes']},{210.5,220.5,55.5})
        self.assertNotEqual(p['bookmaker']['id'],p['source']['provider_id'])
        self.assertEqual(p['source']['method'],'MANUAL_SCREENSHOT')
        self.assertEqual(p['source']['attestation'],'USER_TRANSCRIPTION_NOT_INDEPENDENTLY_VERIFIED')
        self.assertEqual(self.store.read(self.input['fixture'],asof_utc=NOW),[w])

    def test_import_is_idempotent_and_first_available_time_is_not_refreshed(self):
        first=self.save();before={str(p):p.read_bytes() for p in self.store.root.rglob('*') if p.is_file()}
        with patch('time.time',return_value=NOW+120):second=self.save()
        self.assertEqual(first,second);self.assertEqual(second['payload']['available_at_utc'],NOW)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.store.root.rglob('*') if p.is_file()})

    def test_old_image_capture_cannot_backdate_local_availability(self):
        self.input['source']['captured_at_utc']=NOW-86400
        w=self.save();self.assertEqual(w['payload']['available_at_utc'],NOW)
        self.assertEqual(self.store.read(self.input['fixture'],asof_utc=NOW-1),[])

    def test_unknown_capture_clock_is_preserved_as_unknown(self):
        self.input['source']['captured_at_utc']=None
        self.assertIsNone(self.save()['payload']['source']['captured_at_utc'])

    def test_published_clock_does_not_invent_unknown_capture_time(self):
        self.input['source'].update(captured_at_utc=None,published_at_utc=NOW-100)
        self.assertIsNone(self.save()['payload']['source']['captured_at_utc'])

    def test_future_and_reversed_source_clocks_are_rejected(self):
        for updates in [dict(captured_at_utc=NOW+1),dict(published_at_utc=NOW),dict(captured_at_utc=True)]:
            doc=deepcopy(self.input);doc['source'].update(updates)
            with self.subTest(updates=updates),self.assertRaises(ValueError):self.save(doc)
        self.assertFalse(self.store.root.exists())

    def test_supplied_ingestion_time_or_verified_flag_is_not_accepted(self):
        for k,v in [('available_at_utc',NOW-100),('verified',True)]:
            doc=dict(self.input,**{k:v})
            with self.subTest(k=k),self.assertRaises(ValueError):self.save(doc)

    def test_duplicate_or_conflicting_same_line_rejected_before_write(self):
        self.input['quotes'].append(dict(self.input['quotes'][0],prices=dict(over=2.1)))
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):self.save()
        self.assertFalse(self.store.root.exists())

    def test_changed_transcription_of_same_image_does_not_replace_old_evidence(self):
        first=self.save();doc=deepcopy(self.input);doc['quotes'][0]['line']=215.5
        with self.assertRaisesRegex(ValueError,'TRANSCRIPTION_CONFLICT'):self.save(doc)
        self.assertEqual(self.store.read(self.input['fixture'],asof_utc=NOW),[first])

    def test_two_books_or_provider_inputs_are_not_blended(self):
        first=self.save();doc=deepcopy(self.input);doc['bookmaker']=dict(id='other-synthetic-book',name='OTHER SYNTHETIC')
        doc['quotes'][0]['prices']=dict(over=2.1,under=1.8)
        second=self.save(doc);rows=self.store.read(self.input['fixture'],asof_utc=NOW)
        self.assertEqual({w['sha256'] for w in rows},{first['sha256'],second['sha256']})
        self.assertEqual(first['payload']['quotes'][1]['prices'],dict(over=1.9,under=1.9))

    def test_png_bytes_are_preserved_and_source_path_is_not_published(self):
        before=self.image.read_bytes();w=self.save();s=w['payload']['source']
        self.assertEqual((self.store.root/'evidence'/s['evidence']['file']).read_bytes(),before)
        self.assertNotIn(str(self.image),json.dumps(w))

    def test_image_tampering_or_symlink_is_rejected(self):
        w=self.save();path=self.store.root/'evidence'/w['payload']['source']['evidence']['file']
        path.write_bytes(PNG+b'changed')
        with self.assertRaisesRegex(ValueError,'SCREENSHOT_PIN'):self.store.read(self.input['fixture'],asof_utc=NOW)

    def test_symlinked_image_is_not_copied(self):
        link=self.root/'link.png';link.symlink_to(self.image)
        with self.assertRaises(ValueError):self.store.import_screenshot(self.input,link)
        self.assertFalse(self.store.root.exists())

    def test_json_tampering_and_fake_native_verification_fail_closed(self):
        w=self.save();path=next(self.store.root.glob('observation-*.json'));bad=deepcopy(w)
        bad['payload']['quotes'][0]['line']=999
        path.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):self.store.read(self.input['fixture'],asof_utc=NOW)

    def test_stored_manual_file_cannot_upgrade_itself_to_native_api_source(self):
        w=self.save();p=w['payload'];s=p['source']
        s.update(method='NATIVE_RETRIEVAL',attestation='LOCAL_NATIVE_RECEIPT_NOT_PROVIDER_SIGNATURE',
                 receipt_sha256='a'*64,document_sha256='b'*64,native_quote_sha256='c'*64)
        w['sha256']=digest(p);next(self.store.root.glob('observation-*.json')).write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'CANNOT_CLAIM_NATIVE'):self.store.read(self.input['fixture'],asof_utc=NOW)

    def test_foreign_fixture_is_not_returned(self):
        self.save();f=dict(self.input['fixture'],fixture_id='b'*64)
        self.assertEqual(self.store.read(f,asof_utc=NOW),[])

    def test_negative_or_boolean_prices_and_nonfinite_lines_are_rejected(self):
        changes=[dict(line=float('nan')),dict(line=True),dict(line=1001),dict(prices={'over':1}),dict(prices={'over':True}),dict(prices={'home':1.9})]
        for change in changes:
            doc=deepcopy(self.input);doc['quotes'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.save(doc)

    def test_unsupported_period_and_wrong_home_away_are_rejected(self):
        doc=deepcopy(self.input);doc['quotes'][0]['period']='OT'
        with self.assertRaises(ValueError):self.save(doc)
        doc=deepcopy(self.input);doc['fixture']['away_team_id']=doc['fixture']['home_team_id']
        with self.assertRaises(ValueError):self.save(doc)

    def test_secret_bearing_urls_are_not_imported(self):
        for url in ('https://user:secret@synthetic.invalid','https://synthetic.invalid/?api_key=secret','http://synthetic.invalid'):
            doc=deepcopy(self.input);doc['source']['url']=url
            with self.subTest(url=url),self.assertRaises(ValueError):self.save(doc)

    def test_image_size_and_non_image_payload_are_bounded(self):
        self.image.write_bytes(b'not an image')
        with self.assertRaises(ValueError):self.save()
        self.image.write_bytes(PNG)
        with patch('hybrid_engine.market_observations.MAX_IMAGE_BYTES',10),self.assertRaises(ValueError):self.save()

    def test_competitions_are_separate_and_euroleague_is_supported(self):
        for league in ('EuroLeague','EuroCup'):
            doc=deepcopy(self.input);doc['fixture']['league']=league
            w=self.save(doc)
            self.assertEqual(w['payload']['fixture']['league'],league.upper())
        self.assertEqual(self.store.read(self.input['fixture'],asof_utc=NOW),[])

    def test_store_count_budget_is_explicit(self):
        self.store.root.mkdir()
        for i in range(3):(self.store.root/f'observation-{i}.json').write_text('{}')
        with patch('hybrid_engine.market_observations.MAX_FILES',2),self.assertRaisesRegex(ValueError,'COUNT_BUDGET'):
            self.store.read(self.input['fixture'],asof_utc=NOW)

    def test_disk_error_does_not_modify_source_image_or_create_forecast(self):
        with patch('hybrid_engine.market_observations.publish_json',side_effect=OSError('disk full')),self.assertRaises(OSError):self.save()
        self.assertEqual(self.image.read_bytes(),PNG)
        self.assertFalse(list(self.root.rglob('*.sqlite')))


class ConditionalMarketViewTests(TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
        self.receipt,self.native,self.observation,self.distribution=setup_native()
        self.quote=QuoteEvidence.from_espn(self.native,trusted_sha256=self.native['sha256'])

    def test_native_publisher_is_not_misreported_as_bookmaker(self):
        p=self.observation['payload']
        self.assertEqual(p['source']['provider_id'],'ESPN')
        self.assertEqual(p['bookmaker']['id'],'synthetic-book')
        self.assertEqual(p['source']['attestation'],'LOCAL_NATIVE_RECEIPT_NOT_PROVIDER_SIGNATURE')

    def test_native_quote_must_really_be_in_bound_receipt(self):
        fake=deepcopy(self.native);fake['payload']['line']=999;fake['sha256']=digest(fake['payload'])
        with self.assertRaisesRegex(ValueError,'NOT_IN_BOUND'):from_espn(fake,self.receipt)

    def test_unknown_rules_keep_raw_model_mass_visible_without_contract_ev(self):
        v=assess(self.observation,self.distribution,asof_utc=NOW,native_quote=self.quote)
        r=v['rows'][0];p=r['conditional_regulation_probabilities']
        self.assertAlmostEqual(sum(p.values()),1.)
        self.assertFalse(r['conditional_probability_is_contract_settlement'])
        self.assertIsNone(r['expected_value']);self.assertIsNone(r['recommended_direction'])
        self.assertIn('Ham normal süre',render(v));self.assertIn('NOT_CALIBRATED',render(v))

    def test_capture_with_no_publication_clock_cannot_be_reused_as_a_current_price(self):
        with patch('time.time',return_value=NOW+1):
            v=assess(self.observation,self.distribution,asof_utc=NOW+1,
                     native_quote=self.quote,rule=rule_for(self.quote))
        self.assertIsNone(v['rows'][0]['expected_value'])
        self.assertIn('PUBLISHER_PRICE_TIME_UNKNOWN',v['rows'][0]['reasons'])

    def test_model_direction_changes_with_actual_distribution_mass(self):
        for line,direction in [(100.5,'over'),(300.5,'under')]:
            p=deepcopy(self.observation['payload']);p['quotes'][0]['line']=line
            v=assess(dict(payload=p,sha256=digest(p)),self.distribution,asof_utc=NOW)
            self.assertEqual(v['rows'][0]['conditional_direction'],direction)

    def test_probability_equals_count_of_original_paths_not_quantile_interpolation(self):
        v=assess(self.observation,self.distribution,asof_utc=NOW)
        total=self.distribution.paths.sum(axis=(1,2));line=v['rows'][0]['line']
        self.assertEqual(v['rows'][0]['conditional_regulation_probabilities']['under'],float(np.mean(total<line)))

    def test_whole_line_push_mass_is_reported(self):
        p=deepcopy(self.observation['payload']);p['quotes'][0]['line']=210.
        v=assess(dict(payload=p,sha256=digest(p)),self.distribution,asof_utc=NOW)
        self.assertGreater(v['rows'][0]['conditional_regulation_probabilities']['push'],0)

    def test_home_handicap_uses_negative_line_threshold_and_cover_labels(self):
        r=observe_espn(self.receipt,now_utc=NOW)['quotes'][1];o=from_espn(r,self.receipt)
        v=assess(o,self.distribution,asof_utc=NOW)
        margin=self.distribution.paths.sum(axis=1)[:,0]-self.distribution.paths.sum(axis=1)[:,1]
        self.assertEqual(v['rows'][0]['conditional_regulation_probabilities']['over'],float(np.mean(margin>-v['rows'][0]['line'])))
        self.assertIn('EV KARŞILAR',render(v));self.assertIn('DEP KARŞILAR',render(v))

    def test_no_edge_does_not_hide_probabilities_or_forecast(self):
        receipt_,native,observation,d=setup_native(price='-10000')
        quote=QuoteEvidence.from_espn(native,trusted_sha256=native['sha256'])
        v=assess(observation,d,asof_utc=NOW,native_quote=quote,rule=rule_for(quote))
        r=v['rows'][0]
        self.assertEqual(r['decision_status'],'NO_EDGE')
        self.assertIsNotNone(r['expected_value']);self.assertLess(max(r['expected_value'].values()),0)
        self.assertIn('Ham normal süre',render(v));self.assertIn('NO_EDGE',render(v))
        self.assertIsNone(r['recommended_direction']);self.assertIsNone(r['confidence_index'])

    def test_refund_ev_and_conditional_break_even_arithmetic(self):
        # Native receipt is changed, repinned and parsed, not a line/price splice.
        r=receipt(210);native=observe_espn(r,now_utc=NOW)['quotes'][0];o=from_espn(native,r)
        q=QuoteEvidence.from_espn(native,trusted_sha256=native['sha256'])
        row=assess(o,self.distribution,asof_utc=NOW,native_quote=q,rule=rule_for(q))['rows'][0]
        probs=row['contract_raw_probabilities']
        for side,price in q.payload['prices'].items():
            other='over' if side=='under' else 'under'
            self.assertAlmostEqual(row['expected_value'][side],probs[side]*(price-1)-probs[other])
            self.assertAlmostEqual(row['break_even_unconditional_win_probability'][side],(1-probs['push'])/price)

    def test_missing_overtime_paths_never_become_ticket_probability(self):
        v=assess(self.observation,self.distribution,asof_utc=NOW,native_quote=self.quote,rule=rule_for(self.quote,overtime=True))
        r=v['rows'][0];self.assertIsNone(r['expected_value'])
        self.assertIn('NO_VERIFIED_OVERTIME_SIMULATION_PATHS',r['reasons'])

    def test_asian_quarter_lines_do_not_get_whole_stake_ev(self):
        r=receipt(210.25);n=observe_espn(r,now_utc=NOW)['quotes'][0];o=from_espn(n,r);q=QuoteEvidence.from_espn(n,trusted_sha256=n['sha256'])
        row=assess(o,self.distribution,asof_utc=NOW,native_quote=q,rule=rule_for(q))['rows'][0]
        self.assertIsNone(row['expected_value']);self.assertIn('SPLIT_STAKE_ASIAN_QUARTER_LINE_UNSUPPORTED',row['reasons'])

    def test_stale_current_price_is_archival_only_even_if_fresh_at_forecast(self):
        with patch('time.time',return_value=NOW+600):
            v=assess(self.observation,self.distribution,asof_utc=NOW+600,native_quote=self.quote,rule=rule_for(self.quote))
        row=v['rows'][0];self.assertIn('STALE_AT_DECISION_TIME',row['reasons']);self.assertIsNone(row['expected_value'])

    def test_new_quote_keeps_original_forecast_clock_and_is_not_backfilled(self):
        r=deepcopy(self.receipt);r.update(observed_at_utc=NOW+10,ingested_at_utc=NOW+11)
        with patch('time.time',return_value=NOW+12):
            n=observe_espn(r,now_utc=NOW+12)['quotes'][0];o=from_espn(n,r)
            v=assess(o,self.distribution,asof_utc=NOW+12)
        self.assertEqual(v['prediction_utc'],NOW)
        self.assertIn('SOURCE_AVAILABLE_AFTER_ORIGINAL_FORECAST',v['reasons'])
        self.assertIsNone(v['rows'][0]['expected_value'])

    def test_source_not_yet_available_does_not_enter_past_view(self):
        p=deepcopy(self.observation['payload']);p['available_at_utc']=NOW+1
        with patch('time.time',return_value=NOW+2):
            v=assess(dict(payload=p,sha256=digest(p)),self.distribution,asof_utc=NOW)
        self.assertEqual(v['status'],'NOT_YET_AVAILABLE')

    def test_future_decision_clock_and_wrong_fixture_rejected(self):
        with self.assertRaises(ValueError):assess(self.observation,self.distribution,asof_utc=NOW+1)
        with self.assertRaisesRegex(ValueError,'BEFORE_FORECAST'):assess(self.observation,self.distribution,asof_utc=NOW-1)
        p=deepcopy(self.observation['payload']);p['fixture']['fixture_id']='b'*64
        with self.assertRaisesRegex(ValueError,'FIXTURE_SCOPE'):assess(dict(payload=p,sha256=digest(p)),self.distribution,asof_utc=NOW)

    def test_another_books_native_price_cannot_be_spliced_into_observation(self):
        q=deepcopy(self.quote.payload);q['bookmaker_id']='other'
        with self.assertRaisesRegex(ValueError,'PRICE_BINDING'):assess(self.observation,self.distribution,asof_utc=NOW,native_quote=QuoteEvidence(q,digest(q)))

    def test_post_tipoff_view_is_explicit_retrospective_with_no_ev(self):
        tip=self.distribution.trace['tipoff_utc']
        with patch('time.time',return_value=tip):v=assess(self.observation,self.distribution,asof_utc=tip,native_quote=self.quote,rule=rule_for(self.quote))
        self.assertIn('POST_TIPOFF_ARCHIVE_REVIEW_ONLY',v['reasons']);self.assertIsNone(v['rows'][0]['expected_value'])

    def test_forecast_samples_and_trace_are_not_changed(self):
        paths=self.distribution.paths.copy();trace=deepcopy(self.distribution.trace)
        assess(self.observation,self.distribution,asof_utc=NOW)
        np.testing.assert_array_equal(paths,self.distribution.paths);self.assertEqual(trace,self.distribution.trace)

    def test_all_period_and_team_markets_use_the_same_coherent_paths(self):
        doc=manual_input(self.observation['payload']['fixture'])
        doc['quotes']=[dict(period=period,market=market,line=-3.5 if market=='HOME_HANDICAP' else 100.5,prices={})
                       for period in ('FULL','1Q','2Q','3Q','4Q','1H','2H') for market in ('TOTAL','HOME','AWAY','HOME_HANDICAP')]
        with TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'synthetic.png';image.write_bytes(PNG)
            w=ObservationStore(root/'observations').import_screenshot(doc,image)
            view=assess(w,self.distribution,asof_utc=NOW)
        paths=self.distribution.paths
        for row in view['rows']:
            period=row['period'];kind=row['market']
            q=paths if period=='FULL' else paths[:,:2] if period=='1H' else paths[:,2:] if period=='2H' else paths[:,int(period[0])-1:int(period[0])]
            teams=q.sum(axis=1)
            values=teams.sum(axis=1) if kind=='TOTAL' else teams[:,0] if kind=='HOME' else teams[:,1] if kind=='AWAY' else teams[:,0]-teams[:,1]
            threshold=-row['line'] if kind=='HOME_HANDICAP' else row['line']
            self.assertEqual(row['conditional_regulation_probabilities']['over'],float(np.mean(values>threshold)))
            self.assertAlmostEqual(sum(row['conditional_regulation_probabilities'].values()),1)
        self.assertEqual(len(view['rows']),28)


class RealFrozenMarketReplayTests(TestCase):
    def setUp(self):
        from tests.test_phase90 import FrozenPhiladelphiaAudit
        from hybrid_engine.live_nba import PreparedBayes
        self.fixture=FrozenPhiladelphiaAudit('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.p=self.fixture.p;self.assets=self.fixture.assets
        self.service=SimpleNamespace(assets=self.assets,prepared=PreparedBayes(self.assets/self.p['prepared_asset']['file'],trusted_sha256=self.p['prepared_artifact_sha256']))

    def test_original_samples_replay_without_training_download_or_forecast_mutation(self):
        before=digest(self.p)
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('fit')),patch('requests.get',side_effect=AssertionError('network')):
            d=replay_nba(self.p,self.service)
        self.assertEqual(len(d.paths),10000);self.assertEqual(digest(self.p),before)

    def test_changed_archived_sample_pin_rejected(self):
        p=deepcopy(self.p);p['intervals']['sample_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'SAMPLE_SHA'):replay_nba(p,self.service)

    def test_different_prepared_model_is_not_silently_used(self):
        p=dict(self.p,model_digest='other')
        with self.assertRaisesRegex(ValueError,'ORIGINAL_PREPARED'):replay_nba(p,self.service)

    def test_panel_reuses_real_pinned_native_receipt_and_keeps_score(self):
        with TemporaryDirectory() as tmp:
            rows=observed_market_evidence(self.assets,{str(i):r for i,r in enumerate(self.p['source_assets'])},
                self.p['fixture_id'],self.p['prediction_generated_at_utc'],self.p['fixture_start_utc'])
            before=digest(self.p);panel=nba_panel(self.p,self.service,rows,ObservationStore(Path(tmp)/'none'))
        self.assertGreater(panel['lines'],0);self.assertIn('Ham normal süre',panel['html'])
        self.assertEqual(digest(self.p),before);self.assertIn('NOT_CALIBRATED',panel['html'])

    def test_no_source_lines_does_not_trigger_new_distribution(self):
        with TemporaryDirectory() as tmp,patch('hybrid_engine.market_panels.replay_nba',side_effect=AssertionError('replay')):
            panel=nba_panel(self.p,self.service,[],ObservationStore(Path(tmp)/'none'))
        self.assertEqual(panel['lines'],0);self.assertIn('model skoru korunuyor',panel['html'])


class ImportCLITests(TestCase):
    def test_fixture_lookup_uses_read_only_archive_and_creates_no_barems(self):
        from tests.test_phase91 import ten_game_ledger
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic-ledger.sqlite';ten_game_ledger(path,count=1);before=path.read_bytes()
            result=subprocess.run([sys.executable,'-m','hybrid_engine.market_observations','--show-fixture',
                '--ledger',str(path),'--fixture-id','401000123'],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr);out=json.loads(result.stdout)
            self.assertEqual(out['market_lines_created'],0);self.assertEqual(out['fixture']['league'],'NBA')
            self.assertEqual(path.read_bytes(),before)

    def test_import_cli_uses_existing_local_evidence_and_never_claims_api_verification(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'synthetic.png';image.write_bytes(PNG)
            with patch('time.time',return_value=NOW):_,_,o,_=setup_native()
            doc=manual_input(o['payload']['fixture']);doc['source']['captured_at_utc']=None
            path=root/'input.json';path.write_text(json.dumps(doc))
            result=subprocess.run([sys.executable,'-m','hybrid_engine.market_observations','--input',str(path),
                '--screenshot',str(image),'--output-directory',str(root/'out')],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout);self.assertEqual(report['status'],'IMPORTED_MANUAL_UNVERIFIED')
            self.assertFalse(report['forecast_changed']);self.assertFalse(report['production_changed'])

    def test_cli_failure_does_not_echo_input_secret_or_create_store(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'input.json';path.write_text('{"secret":"DONT_ECHO_THIS"}')
            result=subprocess.run([sys.executable,'-m','hybrid_engine.market_observations','--input',str(path),
                '--screenshot',str(root/'missing'),'--output-directory',str(root/'out')],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(result.returncode,2);self.assertNotIn('DONT_ECHO_THIS',result.stdout+result.stderr)
            self.assertFalse((root/'out').exists())


class EuroLeagueManualPanelTests(TestCase):
    def test_frozen_euroleague_manual_lines_keep_legacy_generation_limit_visible(self):
        from hybrid_engine.frozen_archive import FrozenArchive
        archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
        record=next(iter(archive.records.values()));g=record['fixture']
        fixture=dict(league='EUROLEAGUE',season=f"{g['season_start_year']}/{g['season_start_year']+1}",
            fixture_id=g['canonical_id'],home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],tipoff_utc=g['start_ts_utc'])
        with TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'synthetic.png';image.write_bytes(PNG)
            doc=manual_input(fixture);doc['source']['captured_at_utc']=None
            store=ObservationStore(root/'quotes');store.import_screenshot(doc,image)
            before=digest(record)
            with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('fit')):
                body=euroleague_panel(dict(record=record,status='FROZEN_REPLAY_OK'),archive,store)
        self.assertIn('EUROLEAGUE',body);self.assertIn('ayrı kanıtlanmadı',body)
        self.assertIn('Ham normal süre',body);self.assertIn('MANUEL EKRAN',body)
        self.assertEqual(digest(record),before)

    def test_forward_euroleague_replays_published_input_and_sample_hash_only(self):
        from hybrid_engine.frozen_archive import FrozenArchive
        from hybrid_engine.stage_forward_archive import stage
        from hybrid_engine.forward_validation import ForwardRegistry
        archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
        with TemporaryDirectory() as tmp:
            root=Path(tmp);stage(ROOT/'docs/evidence/handoff-forward-el-20261115.tar.gz',root/'forward')
            registry=ForwardRegistry(root/'forward');item=registry.records()[0];p=item['payload'];g=p['fixture']
            fixture=dict(league='EUROLEAGUE',season=f"{g['season_start_year']}/{g['season_start_year']+1}",
                fixture_id=g['canonical_id'],home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],tipoff_utc=g['start_ts_utc'])
            image=root/'synthetic.png';image.write_bytes(PNG);doc=manual_input(fixture);doc['source']['captured_at_utc']=None
            store=ObservationStore(root/'quotes');store.import_screenshot(doc,image)
            before=digest(p)
            with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('fit')):
                body=euroleague_panel(dict(status='FORWARD_EUROLEAGUE_OK',forecast_sha256=digest(p)),archive,store,forward_registry=registry)
            self.assertEqual(digest(registry.records()[0]['payload']),before)
        self.assertIn('Önceden yayımlanmış',body);self.assertIn('NOT_CALIBRATED',body)


from unittest import IsolatedAsyncioTestCase

class TelegramMarketCallbackTests(IsolatedAsyncioTestCase):
    async def test_real_ptb_market_button_shows_manual_alternatives_without_hiding_score(self):
        import importlib
        import os
        from aiohttp import web
        from telegram import Update
        from telegram.ext import Application
        from unittest.mock import AsyncMock
        from tests.test_phase90 import FrozenPhiladelphiaAudit
        from hybrid_engine.live_nba import PreparedBayes
        from hybrid_engine.frozen_archive import FrozenArchive
        from hybrid_engine.test_bot import AuditedRequest,install_isolated_services
        from live_analysis_ledger import LiveAnalysisLedger
        from telegram_delivery import DeliveryJournal
        fixture=FrozenPhiladelphiaAudit('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        p=fixture.p;before=digest(p);now=p['prediction_generated_at_utc']+1
        with TemporaryDirectory() as tmp,patch('time.time',return_value=now):
            root=Path(tmp);sent=[];edits=[]
            async def api(request):
                name=request.path.rsplit('/',1)[-1]
                if name=='getMe':result=dict(id=123456,is_bot=True,first_name='Synthetic',username='zeynal_test_bot')
                elif name in ('sendMessage','editMessageText'):
                    value=dict(await request.post());(sent if name=='sendMessage' else edits).append(value['text'])
                    result=dict(message_id=100+len(sent),date=now,chat=dict(id=17,type='private'),text=value['text'])
                else:result=True
                return web.json_response(dict(ok=True,result=result))
            server=web.Application();server.router.add_route('*','/{path:.*}',api);runner=web.AppRunner(server);await runner.setup()
            site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
            journal=DeliveryJournal(root/'http-journal.sqlite')
            with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_LOCAL_ONLY','API_SPORTS_KEY':'','PREDICTION_LEDGER_DB':str(root/'unused.sqlite')}):
                main=importlib.import_module('main');engine=main.Faz23Engine
                class Local:
                    @staticmethod
                    def builder():return Application.builder().base_url(f'http://127.0.0.1:{port}/bot').request(AuditedRequest(journal))
                with patch.object(main,'Application',Local),patch.object(main,'Faz23Engine',lambda:engine(str(root/'faz23.sqlite'))):app=main.build_app()
            service=SimpleNamespace(assets=fixture.assets,prepared=PreparedBayes(fixture.assets/p['prepared_asset']['file'],trusted_sha256=p['prepared_artifact_sha256']),
                ledger=LiveAnalysisLedger(root/'nba.sqlite'),analyze=AsyncMock(return_value=dict(status='ANALYSIS_OK',snapshot=p,new_record=False,
                    html='ARŞİV',html_parts=['<b>TAHMİN ARALIKLARI</b>','<b>PERİYOT ANALİZİ</b>',
                                         '<b>PİYASA KARŞILAŞTIRMASI</b>','<b>MODEL DENETİMİ</b>'])))
            archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
            installed,_=install_isolated_services(app,archive,root/'isolated',chat_id=17,nba_service=service)
            trace=dict(league=p['league'],season=p['season'],fixture_id=p['fixture_id'],home_team_id=p['home']['provider_id'],away_team_id=p['away']['provider_id'],tipoff_utc=p['fixture_start_utc'])
            image=root/'synthetic.png';image.write_bytes(PNG);doc=manual_input(trace);doc['source']['captured_at_utc']=now
            app.bot_data['market_observation_store'].import_screenshot(doc,image)
            await app.initialize()
            try:
                command='/analyze NBA 2026-11-15 Philadelphia 76ers vs Indiana Pacers'
                update=Update.de_json(dict(update_id=1,message=dict(message_id=1,date=now,chat=dict(id=17,type='private'),
                    **{'from':dict(id=23,is_bot=False,first_name='Synthetic')},text=command,entities=[dict(type='bot_command',offset=0,length=8)])),app.bot)
                await app.process_update(update)
                self.assertTrue(any('112.5' in s and '221.8' in s for s in sent))
                token=next(iter(app.bot_data['premium_reports']))
                callback=Update.de_json(dict(update_id=2,callback_query=dict(id='synthetic-callback',chat_instance='synthetic',
                    data='zui:'+token+':market',**{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
                    message=dict(message_id=101,date=now,chat=dict(id=17,type='private'),text=sent[0]))),app.bot)
                await app.process_update(callback)
                entry=app.bot_data['premium_reports'][token]
                for page in range(len(entry['section_pages']['market'])):
                    detail=Update.de_json(dict(update_id=20+page,callback_query=dict(
                        id='manual-page-'+str(page),chat_instance='synthetic',
                        data=f'zui:{token}:market:{page}',**{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
                        message=dict(message_id=101,date=now,chat=dict(id=17,type='private'),text=sent[0]))),app.bot)
                    await app.process_update(detail)
                self.assertEqual(len(sent),1)
                all_text='\n'.join(sent+edits)
                self.assertIn('MANUEL EKRAN AKTARIMI',all_text);self.assertIn('210,5',all_text);self.assertIn('220,5',all_text)
                self.assertIn('Ham normal süre',all_text);self.assertIn('NOT_CALIBRATED',all_text)
                self.assertFalse(any(e.get('kind')=='HANDLER_ERROR' for e in installed.read()))
                self.assertEqual(digest(p),before)
            finally:
                await app.shutdown();await runner.cleanup()
