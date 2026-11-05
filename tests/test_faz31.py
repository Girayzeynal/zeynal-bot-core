"""All trained examples here are synthetic; no real forecast is backdated."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from period_feature_layer import materialize_period
from prediction_inputs import digest
from shadow_features import make_features,replay_features
from shadow_ridge import train,predict
from shadow_probability import probability_metrics


def original():
    return json.loads((Path(__file__).parent/'fixtures/espn-summary-401909903.json').read_text())


def synthetic_history(cutoff):
    records=[]
    for i in range(6):
        raw=original();h=raw['header'];c=h['competitions'][0]
        h['id']=c['id']=f'SYNTHETIC-H-{cutoff}-{i}'
        c['date']=datetime.fromtimestamp(cutoff-(i+1)*86400,timezone.utc).isoformat()
        if i%2:
            for row in c['competitors']:row['homeAway']='away' if row['homeAway']=='home' else 'home'
            for row in raw['boxscore']['teams']:row['homeAway']='away' if row['homeAway']=='home' else 'home'
        with patch('time.time',return_value=cutoff-1):
            records.append(materialize_period(raw,source_observed_utc=cutoff-100,
                source_evidence_sha256='a'*64,input_ref={'SYNTHETIC_TEST':True}))
    return records


def target(cutoff,index):
    return dict(provider='ESPN',provider_fixture_id=f'SYNTHETIC-T-{index}',start_ts_utc=cutoff+3600,home_team_id='19',away_team_id='2')


def example(cutoff,index):
    fixture=target(cutoff,index)
    with patch('time.time',return_value=cutoff):features=make_features(synthetic_history(cutoff),fixture,cutoff)
    raw=original();h=raw['header'];c=h['competitions'][0]
    h['id']=c['id']=fixture['provider_fixture_id'];c['date']=datetime.fromtimestamp(fixture['start_ts_utc'],timezone.utc).isoformat()
    for row,score in zip(c['competitors'],(100+index%17,80+index%11)):
        qs=[int(score*w) for w in (.2,.23,.26)];qs.append(score-sum(qs))
        row['score']=str(score);row['linescores']=[{'displayValue':str(x)} for x in qs]
    label=dict(summary=raw,observed_utc=cutoff+10800)
    return dict(features=features,label=label,label_sha256=digest(label))


class ShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=int(time.time())-150*86400
        cls.examples=[example(base+i*86400,i) for i in range(100)]
        cls.trained=train(cls.examples,'a'*40)

    def test_insufficient_real_sized_sample_is_not_trained(self):
        result=train(self.examples[:3],'a'*40)
        self.assertEqual(result['status'],'NOT_TRAINED');self.assertNotIn('artifact',result)

    def test_ridge_has_purged_chronological_60_20_20_partitions(self):
        self.assertEqual(self.trained['status'],'TRAINED_EXPERIMENTAL')
        p=self.trained['artifact']['payload']
        self.assertEqual([len(p['split_ids'][k]) for k in ('train','validation','test')],[60,20,20])
        self.assertEqual(p['untouched_test_metrics']['games'],20)
        self.assertEqual(p['calibration_status'],'NOT_ESTABLISHED')
        self.assertTrue(p['last_training_label_utc']<self.examples[60]['features']['payload']['cutoff_utc'])

    def test_late_labels_are_purged_instead_of_training_with_future_results(self):
        examples=deepcopy(self.examples)
        examples[59]['label']['observed_utc']=examples[60]['features']['payload']['cutoff_utc']
        examples[59]['label_sha256']=digest(examples[59]['label'])
        self.assertEqual(train(examples,'a'*40)['status'],'NOT_TRAINED')

    def test_rehashed_feature_change_cannot_bypass_source_replay(self):
        envelope=deepcopy(self.examples[0]['features'])
        envelope['payload']['values']['home_pace']+=1;envelope['sha256']=digest(envelope['payload'])
        with self.assertRaises(ValueError):replay_features(envelope)

    def test_new_future_prediction_uses_learned_unequal_quarters(self):
        cutoff=int(time.time())+2
        with patch('time.time',return_value=cutoff):
            features=make_features(synthetic_history(cutoff),target(cutoff,'future'),cutoff)
            r=predict(self.trained['artifact'],features)
        self.assertNotEqual(len(set(r['quarters']['home'])),1)
        self.assertAlmostEqual(sum(r['quarters']['home']),r['expected_home'])
        self.assertAlmostEqual(sum(r['quarters']['away']),r['expected_away'])
        self.assertAlmostEqual(sum(r['probabilities'].values()),1)
        self.assertFalse(r['coefficients_promoted'])

    def test_trained_artifact_cannot_be_applied_to_earlier_cutoff(self):
        with self.assertRaises(ValueError):predict(self.trained['artifact'],self.examples[0]['features'])

    def test_test_labels_never_change_fitted_coefficients(self):
        examples=deepcopy(self.examples)
        for e in examples[80:]:
            for row in e['label']['summary']['header']['competitions'][0]['competitors']:
                row['score']=str(int(row['score'])+4)
                row['linescores'][0]['displayValue']=str(int(row['linescores'][0]['displayValue'])+4)
            e['label_sha256']=digest(e['label'])
        second=train(examples,'a'*40)
        self.assertEqual(second['artifact']['payload']['head'],self.trained['artifact']['payload']['head'])
        self.assertEqual(second['artifact']['payload']['penalty'],self.trained['artifact']['payload']['penalty'])

    def test_probabilities_are_scored_separately_with_no_calibration_claim(self):
        result=probability_metrics([{'home':.6,'away':.3,'tie':.1}],['home'])
        self.assertAlmostEqual(result['brier'],.26)
        self.assertEqual(result['calibration_status'],'NOT_ESTABLISHED')
        self.assertIsNone(probability_metrics([],[])['log_loss'])

    def test_expanding_walk_forward_has_disjoint_test_periods(self):
        from shadow_ridge import walk_forward
        base=self.examples[0]['features']['payload']['cutoff_utc']
        data=self.examples+[example(base+i*86400,i) for i in range(100,120)]
        result=walk_forward(data,'a'*40)
        self.assertEqual(len(result['folds']),2)
        first,second=result['folds']
        self.assertTrue(set(first['split_ids']['test']).isdisjoint(second['split_ids']['test']))
        self.assertEqual([len(f['split_ids']['train']) for f in result['folds']],[60,80])
        self.assertFalse(result['models_promoted'])

    def test_trained_shadow_pair_has_same_cutoff_and_input_binding(self):
        from shadow_pairs import build_attempt,validate_attempt
        cutoff=int(time.time())+2;fixture=target(cutoff,'pair')
        reference=dict(generated_at=cutoff,model_version='a'*40,multilayer={'reference':'SYNTHETIC_FAZ28'})
        inputs={'sha256':'f'*64}
        with patch('time.time',return_value=cutoff):
            attempt=build_attempt(reference,inputs,dict(target=fixture,period_records=synthetic_history(cutoff),artifact=self.trained['artifact']))
            validate_attempt(attempt,reference,inputs,fixture['provider_fixture_id'],fixture['start_ts_utc'],cutoff)
        self.assertEqual(attempt['payload']['status'],'PREDICTED_EXPERIMENTAL')
        self.assertEqual(attempt['payload']['cutoff_utc'],reference['generated_at'])


class PairTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests import test_faz24 as fixtures
        self.setup=fixtures.Faz24Tests();await self.setup.asyncSetUp()
        self.addCleanup(self.setup.doCleanups)
        self.fx=self.setup.fixture;self.addCleanup(self.fx.folder.cleanup)

    async def test_untrained_shadow_abstention_and_reference_record_are_atomic(self):
        from faz24 import build_bundle
        from shadow_pairs import evaluate_pairs
        cores=[self.fx.core,deepcopy(self.fx.core),deepcopy(self.fx.core)]
        self.setup.bundle=build_bundle(cores,'a'*40,{},dict(target=self.fx.fixture,period_records=[],artifact=None))
        self.assertIsNone(self.setup.bundle['shadow_pair']['payload']['prediction'])
        await self.setup.persist()
        r=evaluate_pairs(self.fx.ledger.db_path)
        self.assertEqual(r['real_paired_games'],0)
        self.assertTrue(r['pending_or_abstained'][0]['status'].startswith('ABSTAIN_'))
        with self.fx.ledger._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM faz24_stages').fetchone()[0],1)

    async def test_shadow_tamper_rolls_back_reference(self):
        from faz24 import build_bundle
        cores=[self.fx.core,deepcopy(self.fx.core),deepcopy(self.fx.core)]
        self.setup.bundle=build_bundle(cores,'a'*40,{},dict(target=self.fx.fixture,period_records=[],artifact=None))
        self.setup.bundle['shadow_pair']['payload']['reference_input_sha256']='bad'
        self.setup.bundle['shadow_pair']['sha256']=digest(self.setup.bundle['shadow_pair']['payload'])
        with self.assertRaises(ValueError):await self.setup.persist()
        self.fx.assert_no_prediction()

    async def test_old_reference_cannot_receive_shadow_after_insertion(self):
        from faz24 import build_bundle
        await self.setup.persist()
        with self.fx.ledger._connect() as db:before=db.execute('SELECT * FROM faz24_stages').fetchall()
        cores=[self.fx.core,deepcopy(self.fx.core),deepcopy(self.fx.core)]
        self.setup.bundle=build_bundle(cores,'a'*40,{},dict(target=self.fx.fixture,period_records=[],artifact=None))
        with self.assertRaises(ValueError):await self.setup.persist()
        with self.fx.ledger._connect() as db:self.assertEqual(before,db.execute('SELECT * FROM faz24_stages').fetchall())
