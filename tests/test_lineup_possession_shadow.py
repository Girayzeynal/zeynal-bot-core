"""All fixtures/coach/player numbers below are SYNTHETIC. Not NBA evidence."""
import copy
import hashlib
import json
import unittest
import numpy as np

from lineup_possession_shadow import VERSION,digest,simulate,validate,markets,tilt_probabilities


def wrap(payload):
    return {'payload':payload,'sha256':digest(payload)}


def synthetic():
    t=1795000000
    fixture=dict(league='NBA',fixture_id='synthetic-game',home_team_id='synthetic-h',
        away_team_id='synthetic-a',tipoff_utc=t+3000,decision_utc=t)
    statuses={}
    coeffs={}
    for side,prefix in (('home','h'),('away','a')):
        statuses[side]=[dict(player_id=f'{prefix}{i}',status='OUT' if i==8 else 'AVAILABLE') for i in range(1,9)]
        coeffs[side]={f'{prefix}{i}':dict(attack=.02 if i<=5 else .17,defense=.015,pace=0.0) for i in range(1,9)}
    model=dict(format='PREFIT_LINEUP_POSSESSION_PARAMETERS_V1',training_scope='PREVIOUSLY_AVAILABLE_GAMES_ONLY',
        fit_cutoff_utc=t-20,training_available_max_utc=t-30,
        training_source_sha256='a'*64,training_fixture_ids=['old-fixture-1','old-fixture-2'],
        player_coefficients_fit_status='PREGAME_HISTORICAL_EXPOSURE_FIT_DECLARED',
        base_pace_per_48={'home':101.0,'away':100.0},
        point_outcome_probabilities={'home':[.48,.08,.29,.13,.02],
                                     'away':[.49,.08,.29,.12,.02]},
        player_coefficients=coeffs,
        coach_quarter_log_effects={side:dict(pace=[-.05,.02,.04,0.0],
                attack=[-.18,.08,.08,-.04]) for side in ('home','away')},
        home_court_attack_log_effect=.03,home_court_pace_log_effect=.01)
    roster=dict(format='PREGAME_NBA_ROSTER_STATUS_V1',fixture_id=fixture['fixture_id'],
        observed_at_utc=t-10,available_at_utc=t-5,source_url='https://example.org/synthetic-roster',
        source_document_sha256='b'*64,attestation='DECLARED_SOURCE_NOT_INDEPENDENTLY_VERIFIED',
        coverage='DECLARED_COMPLETE_RELEVANT_PLAYERS',players=statuses)
    stints=[]
    for quarter in range(1,5):
        for index in range(2):
            stints.append(dict(quarter=quarter,minutes=6.,
                 home=['h1','h2','h3','h4','h5'] if index==0 else ['h1','h2','h5','h6','h7'],
                 away=['a1','a2','a3','a4','a5'] if index==0 else ['a1','a2','a5','a6','a7']))
    rotation=dict(format='PREGAME_LINEUP_ROTATION_ESTIMATE_V1',record_class='PREGAME_PROJECTED_NOT_CONFIRMED',
        fixture_id=fixture['fixture_id'],observed_at_utc=t-6,available_at_utc=t-3,
        source_url='https://example.org/synthetic-rotations',source_document_sha256='c'*64,
        attestation='DECLARED_SOURCE_NOT_INDEPENDENTLY_VERIFIED',stints=stints)
    return dict(format=VERSION,fixture=fixture,model=wrap(model),roster=wrap(roster),rotation=wrap(rotation))


class SyntheticShadow(unittest.TestCase):
    def test_quarter_first_score_paths_and_player_minutes(self):
        b=synthetic()
        raw=json.dumps(b,sort_keys=True)
        out,paths=simulate(b,scenarios=10000,seed=31)
        self.assertEqual(raw,json.dumps(b,sort_keys=True))
        self.assertEqual(paths.shape,(10000,4,2))
        self.assertEqual(out['score_paths_sha256'],hashlib.sha256(paths.tobytes()).hexdigest())
        self.assertAlmostEqual(out['total_mean'],float(paths.sum(axis=(1,2)).mean()))
        self.assertAlmostEqual(out['home_mean']+out['away_mean'],out['total_mean'])
        self.assertAlmostEqual(sum(sum(x) for x in out['quarters_mean']),out['total_mean'])
        self.assertEqual(out['projected_minutes_by_team']['home']['h8'],0.)
        self.assertAlmostEqual(sum(out['projected_minutes_by_team']['home'].values()),240.)
        self.assertGreater(out['quarters_mean'][1][0],out['quarters_mean'][0][0]+8.0)
        self.assertGreater(out['quarters_mean'][2][0],out['quarters_mean'][0][0]+8.0)
        self.assertTrue(np.any(paths[:,0,0]!=paths[:,2,0]))
        self.assertTrue(out['lineup_stints_projected_not_confirmed'])
        self.assertFalse(out['deployable'])
        self.assertFalse(out['roster_source_authenticity_independently_verified'])
        self.assertFalse(out['production_changed'])

    def test_seed_stability_no_fitting_or_archive_write(self):
        b=synthetic()
        a1,_=simulate(b,scenarios=1000,seed=71)
        a2,_=simulate(b,scenarios=1000,seed=71)
        a3,_=simulate(b,scenarios=1000,seed=72)
        self.assertEqual(a1['score_paths_sha256'],a2['score_paths_sha256'])
        self.assertNotEqual(a1['score_paths_sha256'],a3['score_paths_sha256'])
        self.assertEqual(a1['evidence_sha256']['model'],b['model']['sha256'])

    def test_lineup_out_player_refused(self):
        b=synthetic()
        b['rotation']['payload']['stints'][0]['home'][0]='h8'
        b['rotation']=wrap(b['rotation']['payload'])
        with self.assertRaisesRegex(ValueError,'OUT_OR_UNKNOWN_PLAYER'):
            validate(b)

    def test_missing_player_coefficient_refused(self):
        b=synthetic()
        del b['model']['payload']['player_coefficients']['home']['h6']
        b['model']=wrap(b['model']['payload'])
        with self.assertRaisesRegex(ValueError,'NO_IMPUTED_OR_MISSING_PLAYER'):
            validate(b)

    def test_unresolved_questionable_status_refused(self):
        b=synthetic()
        b['roster']['payload']['players']['home'][0]['status']='QUESTIONABLE'
        b['roster']=wrap(b['roster']['payload'])
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_PLAYER'):
            validate(b)

    def test_future_or_post_tipoff_input_refused(self):
        b=synthetic()
        b['roster']['payload']['available_at_utc']=b['fixture']['decision_utc']+1
        b['roster']=wrap(b['roster']['payload'])
        with self.assertRaisesRegex(ValueError,'PREGAME_CLOCK'):
            validate(b)
        b=synthetic()
        b['model']['payload']['fit_cutoff_utc']=b['fixture']['decision_utc']+1
        b['model']=wrap(b['model']['payload'])
        with self.assertRaisesRegex(ValueError,'NO_POSTFORECAST'):
            validate(b)

    def test_hash_mismatch_refused(self):
        b=synthetic()
        b['roster']['payload']['players']['home'][0]['status']='OUT'
        with self.assertRaisesRegex(ValueError,'HASH_CONFLICT'):
            validate(b)

    def test_non_12_minute_quarter_refused(self):
        b=synthetic()
        b['rotation']['payload']['stints'][0]['minutes']=5
        b['rotation']=wrap(b['rotation']['payload'])
        with self.assertRaisesRegex(ValueError,'EACH_QUARTER'):
            validate(b)

    def test_unsupported_stint_tactic_without_verified_fit_refused(self):
        b=synthetic()
        del b['model']['payload']['coach_quarter_log_effects']['home']['attack']
        b['model']=wrap(b['model']['payload'])
        with self.assertRaisesRegex(ValueError,'TACTIC_PARAMS'):
            validate(b)

    def test_period_market_score_distributions_are_coherent(self):
        b=synthetic()
        out,samples=simulate(b,scenarios=1200,seed=29)
        lines=[dict(period='1Q',market='TOTAL',line=50.5),
               dict(period='2Q',market='HOME',line=29.5),
               dict(period='1H',market='TOTAL',line=110.5),
               dict(period='FULL',market='TOTAL',line=220.5),
               dict(period='FULL',market='HOME_HANDICAP',line=-5.5)]
        records=markets(samples,lines)
        self.assertEqual(len(records),5)
        for rec in records:
            self.assertAlmostEqual(sum(rec['probabilities'].values()),1)
            self.assertIsNone(rec['calibrated_confidence'])
            self.assertFalse(rec['selection_enabled'])
        with self.assertRaisesRegex(ValueError,'MARKET_PERIOD'):
            markets(samples,[dict(period='5Q',market='TOTAL',line=220.5)])

    def test_no_unsigned_bundle_can_simulate(self):
        b=synthetic()
        del b['model']
        with self.assertRaisesRegex(ValueError,'INPUT_BUNDLE'):
            simulate(b)

    def test_player_pregame_impact_changes_only_the_provided_lineup_stints(self):
        b=synthetic();a=copy.deepcopy(b)
        a['model']['payload']['player_coefficients']['home']['h6']['attack']+=.25
        a['model']=wrap(a['model']['payload'])
        orig,so=simulate(b,scenarios=10000,seed=2)
        changed,sc=simulate(a,scenarios=10000,seed=2)
        self.assertGreater(changed['home_mean'],orig['home_mean'])
        self.assertEqual(orig['original_model_untouched'],True)


if __name__=='__main__':unittest.main()
