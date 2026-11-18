"""Counterexamples found after #90. Synthetic evidence, no real performance claims."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.decision_layer import DecisionDistribution,settled_value
from hybrid_engine.distributions import Forecast
from hybrid_engine.nba_ledger_settlement import settle
from hybrid_engine import shadow_learning
from ledger_reports import LedgerReports
from tests.test_handoff_hardening import snapshot_ledger,receipt
from tests.test_issue90 import shadow_audit
from tests.test_release_integration import live_payload
from tests.test_season_archive_audit import nba,NOW,START


class SharedLedgerTests(TestCase):
    def test_database_failure_stops_instead_of_being_hidden_as_bad_source(self):
        import sqlite3
        with TemporaryDirectory() as tmp:
            ledger=snapshot_ledger(Path(tmp)/'isolated.sqlite',[nba()])
            with patch('time.time',return_value=NOW),patch.object(ledger,'reconcile',side_effect=sqlite3.OperationalError('SYNTHETIC_DB_FAILURE')):
                with self.assertRaises(sqlite3.OperationalError):settle(ledger,fetcher=lambda p,u:receipt(dict(events=[nba()]),u))
    def test_valid_european_record_does_not_disable_nba_settlement(self):
        with TemporaryDirectory() as tmp:
            ledger=snapshot_ledger(Path(tmp)/'mixed.sqlite',[nba()])
            p=live_payload(START);p.update(league='EUROLEAGUE',fixture_id='EUROPEAN_SYNTHETIC',provider_fixture_ids=['E2026_1'],
                prediction_generated_at_utc=START-101,scope='REGULATION_ONLY',
                input_clocks=[dict(observed_at_utc=START-103,ingested_at_utc=START-102)])
            with patch('time.time',return_value=START-100):ledger.commit(p)
            from hybrid_engine.forward_nba_results import read_confirmed
            with self.assertRaisesRegex(ValueError,'NBA_FORWARD_SNAPSHOT_PIN'):read_confirmed(ledger.path)
            before=ledger.commit_proofs()
            with patch('time.time',return_value=NOW):
                r=settle(ledger,fetcher=lambda p,u:receipt(dict(events=[nba()]),u))
            self.assertEqual(r['pending'],0);self.assertEqual(r['settled'],1)
            self.assertEqual(ledger.commit_proofs(),before)
            self.assertEqual(LedgerReports(ledger.path).read('EUROLEAGUE')['pending'],1)

    def test_corrupt_earlier_day_does_not_starve_valid_later_final(self):
        with TemporaryDirectory() as tmp:
            ledger=snapshot_ledger(Path(tmp)/'isolated.sqlite',[nba()])
            def fetch(p,u):
                r=receipt(dict(events=[nba()]),u)
                if 'dates=20261024' in u:r['document_sha256']='0'*64
                return r
            with patch('time.time',return_value=NOW):r=settle(ledger,fetcher=fetch)
            self.assertEqual(r['settled'],1);self.assertEqual(r['pending'],0)
            self.assertEqual(r['status'],'SOURCE_INCOMPLETE')

    def test_already_settled_fixtures_make_no_repeated_historical_requests(self):
        with TemporaryDirectory() as tmp:
            ledger=snapshot_ledger(Path(tmp)/'isolated.sqlite',[nba()])
            with patch('time.time',return_value=NOW):
                settle(ledger,fetcher=lambda p,u:receipt(dict(events=[nba()]),u))
                fetch=Mock(side_effect=AssertionError('ALREADY_SETTLED_NETWORK_REQUEST'))
                r=settle(ledger,fetcher=fetch)
            fetch.assert_not_called();self.assertEqual(r['due'],0)


class PeriodScopeTests(TestCase):
    def test_ot_never_leaks_into_quarter_or_half_samples(self):
        paths=np.full((10000,4,2),25,dtype=np.int32)
        f=Forecast('SYNTHETIC',paths.mean(axis=0),samples=paths)
        d=DecisionDistribution(f,dict(inputs_available_max_utc=1,prediction_utc=2,tipoff_utc=3),
            overtime_paths=np.tile([9,6],(10000,1)))
        self.assertEqual(d.values('FULL','TOTAL',include_overtime=True)[0],215)
        self.assertEqual(d.values('2H','TOTAL',include_overtime=True)[0],115)
        self.assertEqual(d.values('4Q','TOTAL',include_overtime=True)[0],65)
        for period in ('1Q','2Q','3Q','1H'):
            with self.subTest(period=period),self.assertRaises(Abstain):d.values(period,'TOTAL',include_overtime=True)

    def test_ot_never_leaks_into_quarter_or_half_realized_settlement(self):
        periods=dict(home=[25]*4+[9],away=[25]*4+[6])
        self.assertEqual(settled_value(periods,'FULL','TOTAL',include_overtime=True),215)
        self.assertEqual(settled_value(periods,'2H','TOTAL',include_overtime=True),115)
        self.assertEqual(settled_value(periods,'4Q','TOTAL',include_overtime=True),65)
        for period in ('1Q','2Q','3Q','1H'):
            with self.subTest(period=period),self.assertRaises(Abstain):settled_value(periods,period,'TOTAL',include_overtime=True)


class ShadowCohortTests(TestCase):
    def future(self,n=100,models=1,variants=False):
        now=1794900000;pubs=[];labels=[]
        with patch('time.time',return_value=now):
            for model in range(models):
                md=digest(dict(model=model));a=shadow_audit(now=now)
                for r in a['performance']['forecasts']:r['model_digest']=md
                for r in a['rows']:r['model_digest']=md
                c=shadow_learning.fit(a,model_digest=md,season='2026/2027')
                for i in range(n//models):
                    fid='unseen-'+str(i//5 if variants else model*1000+i)
                    start=now+(i//5+1)*86400
                    row=dict(league='NBA',season='2026/2027',fixture_id=fid,fixture_start_utc=start,
                        snapshot_sha256=digest(dict(fixture=fid,variant=i)),model_digest=md,winner=[.8,.05,.15])
                    pubs.append(shadow_learning.apply(c,row,generated_at_utc=now))
                    labels.append(dict(row,actual=[100,110],label_available_utc=start+7200))
        return pubs,labels,now

    def test_two_fifty_game_fits_cannot_pass_one_hundred_game_gate(self):
        pubs,labels,now=self.future(100,models=2)
        # Give both cohorts twenty actual dates without adding games.
        for i,(p,r) in enumerate(zip(pubs,labels)):
            p['fixture_start_utc']=r['fixture_start_utc']=now+(i%25+1)*86400
            r['label_available_utc']=r['fixture_start_utc']+7200
        with patch('time.time',return_value=now+30*86400):r=shadow_learning.evaluate(pubs,labels,registered_at_utc=now)
        self.assertNotEqual(r['status'],'CANDIDATE_FOR_MANUAL_REVIEW')
        self.assertEqual(sorted(g['n'] for g in r['groups']),[50,50])
        self.assertIsNone(r['n'])

    def test_pending_mixed_cohorts_do_not_claim_settled_games(self):
        pubs,labels,now=self.future(10,models=2)
        for r in labels:r['actual']=None
        with patch('time.time',return_value=now+3*86400):r=shadow_learning.evaluate(pubs,labels,registered_at_utc=now)
        self.assertIsNone(r['n']);self.assertEqual(r['matched_forecasts_across_cohorts'],0)
        self.assertEqual(r['unique_published_fixtures'],10)

    def test_five_snapshot_variants_do_not_turn_twenty_matches_into_one_hundred(self):
        pubs,labels,now=self.future(100,variants=True)
        with patch('time.time',return_value=now+30*86400),self.assertRaisesRegex(ValueError,'INDEPENDENT_FIXTURE'):
            shadow_learning.evaluate(pubs,labels,registered_at_utc=now)

    def test_same_snapshot_cannot_have_different_original_probability(self):
        pubs,labels,now=self.future(1);labels[0]['winner']=[.1,.1,.8]
        with patch('time.time',return_value=now+3*86400),self.assertRaisesRegex(ValueError,'ORIGINAL_PROBABILITY_CONFLICT'):
            shadow_learning.evaluate(pubs,labels,registered_at_utc=now)

    def test_foreign_league_label_cannot_settle_nba_publication(self):
        pubs,labels,now=self.future(1);labels[0]['league']='EUROCUP'
        with patch('time.time',return_value=now+3*86400):r=shadow_learning.evaluate(pubs,labels,registered_at_utc=now)
        self.assertEqual(r['n'],0)


class StudyIntegrityTests(TestCase):
    def setUp(self):
        from tests.test_issue90 import Issue90ForwardTests
        Issue90ForwardTests.setUp(self)

    def label(self):
        t=self.case['target']
        return dict(fixture_id=t['fixture_id'],snapshot_sha256=self.case['original'],model_digest='a'*64,
            model_version='SYNTHETIC',season=t['season'],league='NBA',fixture_start_utc=t['fixture_start_utc'],
            label_available_utc=t['fixture_start_utc']+7200,prediction=[110.,110.],actual=[100,100],
            actual_periods=dict(home=[25]*4,away=[25]*4),predicted_quarters=[[27.5,27.5]]*4,
            winner=[.4,.2,.4],prediction_generated_at_utc=t['fixture_start_utc']-3600,intervals=None)

    def test_two_unsupported_fixtures_cannot_starve_later_supported_fixture(self):
        cases=[]
        for i in range(3):
            c=deepcopy(self.case);c['target']['fixture_id']='pending-'+str(i)
            c['snapshot']['fixture_id']=c['target']['fixture_id'];c['original']=digest(c['snapshot']);cases.append(c)
        self.worker.cases=lambda:cases
        def verify(t):
            if t['fixture_id']!='pending-2':raise Abstain('NATIVE_SOURCE_UNAVAILABLE')
            return dict(ingested_at_utc=self.now)
        self.worker.verify=verify
        with patch('hybrid_engine.issue90_research.audit_ledger',return_value=shadow_audit(0,now=self.now)),\
             patch.object(self.study,'fit',return_value=(self.model,False)):
            first=self.study.tick();self.now+=60;second=self.study.tick()
        self.assertEqual([c['status'] for c in first['captures']],['ABSTAIN','ABSTAIN'])
        self.assertEqual(second['captures'][0]['fixture_id'],'pending-2')
        self.assertEqual(second['captures'][0]['status'],'ARCHIVED')
        self.assertEqual(second['performance']['admitted'],3)

    def test_candidate_without_prior_admission_cannot_enter_acceptance_metrics(self):
        self.study.capture(self.case,self.model,self.plan)
        self.now=self.case['target']['fixture_start_utc']+7200
        with self.assertRaisesRegex(ValueError,'WITHOUT_PRIOR_ADMISSION'):self.study.performance([self.label()],self.plan)

    def test_conflicting_duplicate_native_labels_are_rejected_not_last_wins(self):
        self.study.admit(self.case,self.plan);self.study.capture(self.case,self.model,self.plan)
        self.now=self.case['target']['fixture_start_utc']+7200
        row=self.label();other=dict(row,actual=[110,110],actual_periods=dict(home=[27,27,28,28],away=[27,27,28,28]))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_NATIVE_LABEL'):self.study.performance([row,other],self.plan)

    def test_old_report_is_preserved_but_not_attested_as_current_integrity(self):
        from hybrid_engine.boxes import publish_json
        from hybrid_engine.issue90_research import status
        p=dict(status='CHECKED',observed_at_utc=self.now,performance=dict(gate='CANDIDATE_FOR_MANUAL_REVIEW'))
        path=self.study.root/('report-'+digest(p)+'.json');publish_json(path,dict(payload=p,sha256=digest(p)))
        before=path.read_bytes();r=status(self.study.root)
        self.assertEqual(r['report'],p);self.assertEqual(path.read_bytes(),before)
        self.assertEqual(r['evaluation_status'],'NO_CURRENT_INTEGRITY_ATTESTATION')
        self.assertFalse(r['automatic_promotion'])
