"""Synthetic team histories, never real NBA game facts."""
import copy
import unittest
from team_dynamics_evidence import build, digest


def request():
    return dict(league='NBA',season='2026/2027',fixture_id='future',
                home_team_id='TEAM-A',away_team_id='TEAM-B',
                decision_utc=1800000000,tipoff_utc=1800005000)


def r(fid,start,home,away,period_h,period_a,available=None):
    return dict(league='NBA',season='2026/2027',fixture_id=fid,
                fixture_start_utc=start,home_team_id=home,away_team_id=away,
                source_catalog_sha256='f'*64,available_at_utc=available or start+1000,
                periods={'home':list(period_h),'away':list(period_a)})


def rows():
    return [
        r('1',1790000000,'TEAM-A','TEAM-C',[19,38,33,29],[30,24,20,27]),
        r('2',1790050000,'TEAM-D','TEAM-B',[27,30,29,26],[33,18,20,22]),
        r('3',1790100000,'TEAM-B','TEAM-E',[36,21,18,24],[25,28,20,20]),
        r('4',1790150000,'TEAM-C','TEAM-A',[28,32,30,29],[21,35,36,30]),
        r('5',1790200000,'TEAM-A','TEAM-B',[19,33,32,25],[38,21,22,29]),
    ]


class TeamEvidenceTests(unittest.TestCase):
    def test_each_team_quarter_pattern_differs_without_common_curve(self):
        x=build(request(),rows())
        a=x['target_home']['all_games']['per_quarter_for']
        b=x['target_away']['all_games']['per_quarter_for']
        self.assertLess(a[0]['mean'],a[1]['mean'])
        self.assertGreater(b[0]['mean'],b[1]['mean'])
        self.assertNotEqual([v['mean'] for v in a],[v['mean'] for v in b])
        self.assertTrue(x['no_universal_quarter_curve'])
        self.assertFalse(x['betting_direction_generated'])
        self.assertFalse(x['model_fitted'])

    def test_home_away_context_kept_separate(self):
        x=build(request(),rows())
        a=x['target_home']
        self.assertEqual(a['by_venue']['home']['n'],2)
        self.assertEqual(a['by_venue']['away']['n'],1)
        self.assertEqual(x['target_away']['by_venue']['home']['n'],1)
        self.assertEqual(x['target_away']['by_venue']['away']['n'],2)
        self.assertEqual(x['original_head_to_head_count'],1)

    def test_derived_records_are_observations_not_predictions(self):
        source=rows(); original=copy.deepcopy(source)
        x=build(request(),source)
        self.assertEqual(source,original)
        self.assertEqual(x['num_native_history_fixtures'],5)
        self.assertEqual(x['target_home']['observations'],3)
        self.assertFalse(x['lineup_or_injury_impact_calculated'])
        self.assertFalse(x['independent_pregame_player_coach_context_available'])
        self.assertEqual(x['evidence_basis'],'DECLARED_NORMALIZED_NATIVE_RECORDS')

    def test_reorder_has_stable_hash(self):
        x=build(request(),rows())
        self.assertEqual(x['inputs_sha256'],build(request(),rows()[::-1])['inputs_sha256'])

    def test_after_decision_and_target_label_rejected(self):
        future=r('after',1800000010,'TEAM-A','TEAM-C',[30]*4,[20]*4,1800002000)
        with self.assertRaisesRegex(ValueError,'POSTDECISION'):
            build(request(),rows()+[future])
        target=r('future',1790000000,'TEAM-A','TEAM-B',[30]*4,[20]*4)
        with self.assertRaisesRegex(ValueError,'POSTDECISION'):
            build(request(),rows()+[target])

    def test_duplicate_fixture_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_FIXTURE'):
            build(request(),rows()+[rows()[0]])

    def test_league_or_season_mix_rejected(self):
        s=rows();s[1]['season']='2025/2026'
        with self.assertRaisesRegex(ValueError,'SEASON_LEAGUE'):
            build(request(),s)

    def test_period_full_plus_overtime_regulation_only(self):
        s=rows();s[0]['periods']['home'].append(12);s[0]['periods']['away'].append(8)
        x=build(request(),s)
        a=x['target_home']['chronological_games'][0]['for_quarters']
        self.assertEqual(len(a),4)
        self.assertEqual(sum(a),sum([19,38,33,29]))

    def test_missing_periods_rejected_not_filled(self):
        s=rows();s[0]['periods']=None
        with self.assertRaisesRegex(ValueError,'COMPLETE_PERIODS'):
            build(request(),s)

    def test_both_sides_keep_actual_opponent_attribution(self):
        x=build(request(),rows())
        a=x['target_home']['by_opponent']
        self.assertEqual(a['TEAM-B']['n'],1)
        self.assertEqual(x['target_away']['by_opponent']['TEAM-A']['n'],1)

    def test_sparsity_is_visible_and_not_fixed_by_averaging(self):
        x=build(request(),[])
        self.assertEqual(x['target_home']['all_games']['n'],0)
        self.assertIsNone(x['target_home']['all_games']['per_quarter_for'])
        self.assertFalse(x['confidence_calibrated'])

    def test_target_clock_and_history_ids_guarded(self):
        q=request();q['tipoff_utc']=q['decision_utc']
        with self.assertRaisesRegex(ValueError,'PREGAME_CLOCK'):
            build(q,rows())
        s=rows();s[0]['source_catalog_sha256']='fake'
        with self.assertRaisesRegex(ValueError,'CATALOG_PIN'):
            build(request(),s)

if __name__=='__main__':unittest.main()
