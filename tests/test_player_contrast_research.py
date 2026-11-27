"""Minute contrast research stays separate from live player admission."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.player_box_pilot import verified_box_rows,fit_box_association,paired_holdout
from hybrid_engine.player_contrast_research import fit,fit_for_comparison,conditional_pair
from tests.test_player_box_pilot import BASE,fixture


def varied_rows():
    cohort=[]
    for i in range(80):
        g=fixture(i)
        for side,m in (('home',i%10),('away',(i*3)%10)):
            players=[p for p in g['box']['players'] if p['side']==side]
            players[0]['minutes_display']=str(20+m)+':00'
            players[1]['minutes_display']=str(40-m)+':00'
        cohort.append([g])
    return verified_box_rows(cohort,BASE+90*86400)[0]


class MinuteContrastTests(TestCase):
    def setUp(self):
        self.cut=BASE+90*86400
        clock=patch('time.time',return_value=self.cut);clock.start();self.addCleanup(clock.stop)

    def test_static_minutes_are_not_individual_player_information(self):
        rows,_=verified_box_rows([[fixture(i)] for i in range(80)],self.cut)
        self.assertEqual(len(fit_box_association(rows,self.cut)['players']),16)
        with self.assertRaisesRegex(Abstain,'NO_IDENTIFIABLE_MINUTE_VARIATION'):
            fit(rows,self.cut)

    def test_selection_has_independent_contrasts_and_keeps_reference_unchanged(self):
        rows=varied_rows();before=deepcopy(rows)
        reference=fit_box_association(rows,self.cut)
        wrapper=fit(rows,self.cut);p=wrapper['payload']
        self.assertEqual(wrapper['sha256'],digest(p))
        self.assertEqual(len(p['players']),2)
        self.assertEqual(p['full_design_rank'],p['base_design_rank']+2)
        self.assertLess(p['estimated_parameters'],p['score_observations'])
        self.assertFalse(p['selection_uses_score_outcomes'])
        self.assertFalse(p['live_player_effect_applied'])
        self.assertFalse(p['causal_player_effect'])
        self.assertFalse(p['production_enabled'])
        self.assertEqual(rows,before)
        self.assertEqual(fit_box_association(rows,self.cut),reference)

    def test_changing_only_scores_cannot_choose_other_players(self):
        rows=varied_rows();changed=deepcopy(rows)
        for i,g in enumerate(changed):g['score']=[80+i%17,120-i%11]
        first=fit(rows,self.cut)['payload'];second=fit(changed,self.cut)['payload']
        self.assertEqual(first['players'],second['players'])
        self.assertEqual(first['full_design_rank'],second['full_design_rank'])
        self.assertNotEqual(first['coefficients'],second['coefficients'])

    def test_cutoff_identity_and_minute_budget_cannot_be_bypassed(self):
        rows=varied_rows()
        bad=deepcopy(rows);bad[0]['available_at_utc']=self.cut+1
        with self.assertRaisesRegex(ValueError,'LATE_LABEL'):fit(bad,self.cut)
        bad=deepcopy(rows);bad[0]['league']='EUROLEAGUE'
        with self.assertRaisesRegex(ValueError,'NBA_ONLY'):fit(bad,self.cut)
        with self.assertRaisesRegex(ValueError,'PAST_CUTOFF'):fit(rows,self.cut+1)
        bad=deepcopy(rows);bad[0]['minutes']['home']['1100']=49
        with self.assertRaisesRegex(ValueError,'MINUTE_BUDGET'):fit(bad,self.cut)
        bad=deepcopy(rows);bad[0]['score'][0]=float('inf')
        with self.assertRaisesRegex(ValueError,'FINITE'):fit(bad,self.cut)

    def test_conditional_rotation_is_not_a_verified_injury_forecast(self):
        rows=varied_rows();wrapper=fit(rows,self.cut)
        h=rows[-1]['minutes']['home'];a=rows[-1]['minutes']['away']
        result=conditional_pair(wrapper,'1','2',h,a)
        self.assertEqual(len(result['prediction']),2)
        self.assertTrue(result['conditional_on_supplied_minutes'])
        self.assertFalse(result['source_availability_verified'])
        self.assertFalse(result['live_player_effect_applied'])
        tampered=deepcopy(wrapper);tampered['payload']['coefficients'][0]+=1
        with self.assertRaisesRegex(ValueError,'MODEL_PIN'):conditional_pair(tampered,'1','2',h,a)
        for bad in (dict(h,**{'1100':-1}),dict(h,**{'1100':float('nan')}),dict(h,**{'1100':1})):
            with self.assertRaises(ValueError):conditional_pair(wrapper,'1','2',bad,a)

    def test_same_chronological_holdout_requires_minute_variation(self):
        rows=varied_rows()
        paired=paired_holdout(rows,now_utc=self.cut,candidate_fitter=fit_for_comparison)
        self.assertGreater(paired['matched_test_games'],0)
        self.assertEqual(paired['paired_score_metrics']['candidate']['n'],paired['paired_score_metrics']['control']['n'])
        self.assertFalse(paired['demonstrated_superiority'])
        self.assertFalse(paired['prospective_accuracy_evidence'])
        static,_=verified_box_rows([[fixture(i)] for i in range(80)],self.cut)
        self.assertEqual(paired_holdout(static,now_utc=self.cut,candidate_fitter=fit_for_comparison)['status'],'MODEL_FIT_ABSTAINED')

    def test_sparse_training_abstains_instead_of_creating_a_model(self):
        with self.assertRaisesRegex(Abstain,'THIRTY_NATIVE_BOX_GAMES'):fit(varied_rows()[:29],self.cut)
