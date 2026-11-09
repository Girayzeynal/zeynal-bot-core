"""Real trimmed final plus synthetic duplicate/conflict regression cases."""
import json
from pathlib import Path
from copy import deepcopy
import unittest
from nba_real_data_validation import verify_pair, deduplicate_finals


class RealFinalValidationTests(unittest.TestCase):
    def setUp(self):
        self.raw=json.loads((Path(__file__).parent/'fixtures/espn-final-401909911.json').read_text())

    def result(self):
        return verify_pair(self.raw['event'],self.raw['summary'],self.raw['observed_at_utc'])

    def test_real_identity_orientation_and_missing_boxscore_are_explicit(self):
        row=self.result()
        self.assertEqual(row['home'],'1610612753')
        self.assertEqual(row['away'],'1610612764')
        self.assertEqual((row['home_score'],row['away_score']),(94,103))
        self.assertIsNone(row['pace'])  # Trimmed fixture intentionally lacks stats.
        self.assertEqual(row['historical_availability'],'NOT_ESTABLISHED')

    def test_provider_alias_does_not_increase_sample(self):
        row=self.result()
        second={**row,'provider':'SYNTHETIC_SECOND_SOURCE','provider_fixture_id':'other-id'}
        self.assertEqual(deduplicate_finals([row,second]),dict(observations=2,distinct_games=1,duplicates=1))

    def test_conflicting_score_and_direction_rejected(self):
        row=self.result()
        for changes in ({'home_score':95},{'home':row['away'],'away':row['home']}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                deduplicate_finals([row,{**row,**changes,'provider_fixture_id':'other'}])

    def test_summary_score_time_or_id_disagreement_rejected(self):
        for field,value in (('id','999'),('date','2026-11-02T00:00:00Z')):
            s=deepcopy(self.raw['summary'])
            s['header']['competitions'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                verify_pair(self.raw['event'],s,self.raw['observed_at_utc'])

    def test_provider_id_reuse_and_same_team_start_conflict_rejected(self):
        row=self.result()
        for changes in ({'start_ts_utc':row['start_ts_utc']+3600},
                        {'away':'1610612738','provider_fixture_id':'different'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                deduplicate_finals([row,{**row,**changes}])

    def test_unknown_canonical_team_and_boolean_score_rejected(self):
        for changes in ({'home':'UNKNOWN'},{'home_score':True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                deduplicate_finals([{**self.result(),**changes}])
