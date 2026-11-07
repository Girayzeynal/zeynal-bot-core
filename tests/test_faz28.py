"""Synthetic model tests and atomic future-ledger integration; no real accuracy claims."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import unittest
from tests import test_faz24 as fixtures
from faz24 import build_bundle,report
from faz28 import build_multilayer,validate_multilayer
from prediction_inputs import digest


def exact(values):return sum(Decimal(str(v)) for v in values)


class MultilayerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup=fixtures.Faz24Tests();await self.setup.asyncSetUp()
        self.addCleanup(self.setup.doCleanups)
        self.fx=self.setup.fixture;self.addCleanup(self.fx.folder.cleanup)
        self.snapshot=self.fx.core.meta['input_snapshot'];self.version='a'*40

    def model(self,config=None):
        return build_multilayer(self.snapshot,model_version=self.version,config=config)

    async def test_quarters_halves_team_totals_reconcile_exactly(self):
        r=self.model()
        for side in ('home','away','total'):
            self.assertEqual(exact(q[side] for q in r['quarters'].values()),Decimal(str(r['team_totals'][side])))
            self.assertEqual(exact(h[side] for h in r['halves'].values()),Decimal(str(r['team_totals'][side])))
        self.assertEqual(r['team_totals']['home'],self.snapshot['payload']['expected_home'])
        self.assertEqual(r['spread']['expected_home_margin'],-r['spread']['fair_home_handicap'])

    async def test_10000_scenarios_reproducible_probability_partition(self):
        first=self.model();second=self.model()
        self.assertEqual(first,second);simulation=first['simulation']
        self.assertEqual(simulation['simulations'],10000)
        self.assertAlmostEqual(sum(simulation[k] for k in ('home_regulation_win_probability','away_regulation_win_probability','regulation_tie_probability')),1)
        self.assertEqual(first['calibration_status'],'NOT_ESTABLISHED')
        self.assertIsNone(first['eventual_game_win_probability'])
        self.assertEqual(first['scope_status'],'UNVALIDATED_REGULATION_PROXY')

    async def test_missing_fields_and_no_fake_market(self):
        r=self.model()
        self.assertIn('VERIFIED_INJURIES',r['missing_data'])
        self.assertIn('VERIFIED_ROSTERS',r['missing_data'])
        self.assertIn('SCOPED_MARKET_LINE',r['missing_data'])
        self.assertIsNone(r['simulation']['over_probability'])
        self.assertEqual(r['pace_status'],'UNVERIFIED_SOURCE_PACE')

    async def test_invalid_configuration_rejected(self):
        for cfg in ({'simulations':9999},{'simulations':True},{'seed':True},
                    {'score_correlation':float('nan')},{'market_total':220}, {'invented':1}):
            with self.subTest(config=cfg),self.assertRaises(ValueError):self.model(cfg)

    async def test_explicit_regulation_market_partition(self):
        r=self.model({'market_total':220,'market_scope':'REGULATION_ONLY'})['simulation']
        self.assertAlmostEqual(r['over_probability']+r['under_probability']+r['push_probability'],1)

    async def test_semantically_tampered_output_rejected(self):
        r=self.model();r['quarters']['1']['home']+=1
        with self.assertRaises(ValueError):validate_multilayer(r,self.snapshot,self.version)

    async def test_atomic_ledger_binding_and_legacy_forecast_unchanged(self):
        cores=[self.fx.core,deepcopy(self.fx.core),deepcopy(self.fx.core)]
        self.setup.bundle=build_bundle(cores,self.version,{})
        await self.setup.persist()
        before=Path(self.fx.ledger.db_path).read_bytes()
        result=report(self.fx.ledger.db_path)
        self.assertEqual(before,Path(self.fx.ledger.db_path).read_bytes())
        self.assertIn('synthetic-target',result['multilayer_predictions'])
        self.assertIsNone(result['multilayer_evaluation']['metrics'])
        self.assertEqual(result['prospective']['sample_size'],0)

    async def test_no_posthoc_extension_and_no_mutation(self):
        await self.setup.persist()
        before=Path(self.fx.ledger.db_path).read_bytes()
        self.setup.bundle['multilayer']=self.model()
        self.setup.bundle['multilayer_captured_at_utc']=self.setup.bundle['stages'][-1]['captured_at_utc']
        for stage in self.setup.bundle['stages']:stage['multilayer_sha256']=digest(self.setup.bundle['multilayer'])
        with self.assertRaises(ValueError):await self.setup.persist()
        self.assertEqual(before,Path(self.fx.ledger.db_path).read_bytes())

    async def test_simulated_period_means_reconcile_without_display_rounding(self):
        sim=self.model()['simulation']
        self.assertAlmostEqual(sum(sim['period_home_means']),sim['expected_home_score'],places=10)
        self.assertAlmostEqual(sum(sim['period_away_means']),sim['expected_away_score'],places=10)
        self.assertAlmostEqual(sim['expected_home_score']+sim['expected_away_score'],sim['expected_total'],places=10)

    async def test_zero_variance_does_not_invent_volatility(self):
        core=deepcopy(self.fx.core)
        from prediction_inputs import seal_prediction_inputs
        teams=deepcopy(self.snapshot['payload']['teams'])
        for side in teams:
            for row in teams[side]['records']:
                row['pts_for']=100;row['pts_against']=100
        core.meta.update(expected_home=100,expected_away=100,expected_total=200)
        snapshot=seal_prediction_inputs(core,teams['home'],teams['away'])
        r=build_multilayer(snapshot,model_version=self.version)
        self.assertIsNone(r['simulation'])
        self.assertIn('NONZERO_EMPIRICAL_SCORE_VARIANCE',r['missing_data'])

    async def test_tipoff_crossed_during_replay_cannot_commit(self):
        from unittest.mock import patch
        import time
        cores=[self.fx.core,deepcopy(self.fx.core),deepcopy(self.fx.core)]
        self.setup.bundle=build_bundle(cores,self.version,{})
        now=time.time()
        def replay_crosses_tipoff(*args):
            clock.return_value=self.fx.tipoff+1
        with patch('faz24.time.time',return_value=now) as clock:
            with patch('faz28.validate_multilayer',side_effect=replay_crosses_tipoff):
                with self.assertRaisesRegex(ValueError,'started during stage replay'):
                    await self.setup.persist()
        self.fx.assert_no_prediction()
