"""Native posterior algebra plus deliberately invalid synthetic histories."""
from copy import deepcopy
from dataclasses import replace
import unittest

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain, Cut, regulation
from hybrid_engine.live_nba import PreparedBayes
from hybrid_engine.posterior_refresh import refresh
from hybrid_engine.prediction_audit import Assets
from tests import test_phase90 as native


class PosteriorRefreshTests(unittest.TestCase):
    def setUp(self):
        self.h=native.FrozenPhiladelphiaAudit('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.p=self.h.p; self.cut=Cut(**Assets(self.h.assets).read(self.p['input_asset']))
        self.prepared=PreparedBayes(self.h.assets/self.p['prepared_asset']['file'],trusted_sha256=self.p['prepared_artifact_sha256'])

    def test_native_recent_window_is_not_misrepresented_as_a_complete_league_refit(self):
        model,trace=refresh(self.prepared,self.cut)
        self.assertEqual(len(self.cut.history),19);self.assertEqual(trace['original_training_games'],170)
        self.assertGreater(trace['updates'],0);self.assertFalse(trace['full_league_refit'])
        self.assertEqual(model.noise_variance,self.prepared.model.noise_variance)
        self.assertEqual(len(model.training_ids),170+trace['updates'])

    def test_batch_update_matches_independent_scalar_kalman_updates(self):
        model,trace=refresh(self.prepared,self.cut)
        mean=self.prepared.model.coefficients.copy();cov=self.prepared.model.covariance.copy()
        ids=set(trace['update_ids']); rows=sorted((r for r in self.cut.history if r['fixture_id'] in ids),key=lambda r:r['fixture_id'])
        for row in rows:
            for i,(own,other) in enumerate((('home','away'),('away','home'))):
                x,_=model._vector(row[own+'_team_id'],row[other+'_team_id'],own=='home')
                cx=cov@x;gain=cx/(model.noise_variance+x@cx)
                mean=mean+gain*(regulation(row)[i]-x@mean)
                cov=cov-np.outer(gain,cx)
        np.testing.assert_allclose(model.coefficients,mean,rtol=0,atol=1e-9)
        np.testing.assert_allclose(model.covariance,cov,rtol=0,atol=1e-9)

    def test_original_artifact_and_parameters_remain_unchanged(self):
        before=digest(self.prepared.payload);coef=self.prepared.model.coefficients.copy()
        refresh(self.prepared,self.cut)
        self.assertEqual(digest(self.prepared.payload),before)
        np.testing.assert_array_equal(self.prepared.model.coefficients,coef)

    def test_old_training_games_are_not_counted_twice(self):
        old=set(self.prepared.model.training_ids)
        history=[r for r in self.cut.history if r['fixture_id'] in old]
        self.assertTrue(history)
        model,trace=refresh(self.prepared,replace(self.cut,history=history))
        self.assertEqual(trace['updates'],0)
        np.testing.assert_array_equal(model.coefficients,self.prepared.model.coefficients)
        np.testing.assert_array_equal(model.covariance,self.prepared.model.covariance)

    def test_revised_old_labels_require_explicit_full_refit(self):
        history=deepcopy(self.cut.history); old=set(self.prepared.model.training_ids)
        row=next(r for r in history if r['fixture_id'] in old);row['periods']['home'][0]+=1
        with self.assertRaisesRegex(Abstain,'REVISION_REQUIRES_FULL_REFIT'):
            refresh(self.prepared,replace(self.cut,history=history))

    def test_unknown_team_requires_full_refit_instead_of_arbitrary_new_coefficient(self):
        history=deepcopy(self.cut.history); old=set(self.prepared.model.training_ids)
        row=next(r for r in history if r['fixture_id'] not in old);row['home_team_id']='SYNTHETIC_UNKNOWN'
        with self.assertRaisesRegex(Abstain,'NEW_TEAM_REQUIRES'): refresh(self.prepared,replace(self.cut,history=history))

    def test_duplicate_or_future_history_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'HISTORY_LEAKAGE_OR_DUPLICATION'):
            refresh(self.prepared,replace(self.cut,history=self.cut.history+[self.cut.history[0]]))
        history=deepcopy(self.cut.history);history[0]['ingested_at_utc']=self.cut.cutoff_utc+1
        with self.assertRaisesRegex(ValueError,'HISTORY_LEAKAGE_OR_DUPLICATION'):
            refresh(self.prepared,replace(self.cut,history=history))

    def test_target_label_or_wrong_season_cannot_enter_update(self):
        history=deepcopy(self.cut.history);history[0]['fixture_id']=self.cut.target['fixture_id']
        with self.assertRaisesRegex(ValueError,'HISTORY_LEAKAGE'):refresh(self.prepared,replace(self.cut,history=history))
        target=dict(self.cut.target,season='2025/2026')
        with self.assertRaisesRegex(ValueError,'SCOPE_OR_CUTOFF'):refresh(self.prepared,replace(self.cut,target=target))

    def test_repeated_update_is_deterministic(self):
        a,ta=refresh(self.prepared,self.cut);b,tb=refresh(self.prepared,self.cut)
        self.assertEqual(ta,tb);self.assertEqual(a.artifact_digest,b.artifact_digest)
        np.testing.assert_array_equal(a.coefficients,b.coefficients)
