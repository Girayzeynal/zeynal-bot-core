"""No original user files accessed; all records synthetic."""
import copy
import unittest
from team_dynamics_evidence import digest
from team_dynamics_native_census import brief,profile,historical_player_box_coverage
from test_team_dynamics_evidence import rows


def records():
    cut=dict(target=dict(league='NBA',season='2026/2027',fixture_id='future',fixture_start_utc=1800005000,
                 home_team_id='TEAM-A',away_team_id='TEAM-B'),cutoff_utc=1800000000,
             evaluation_class='PIT_PROVEN_BACKTEST',history=[])
    for r in rows():
        d=copy.deepcopy(r)
        d['observed_at_utc']=d['available_at_utc']-1
        d['ingested_at_utc']=d['available_at_utc']
        del d['available_at_utc']
        cut['history'].append(d)
    snap=dict(league='NBA',season='2026/2027',fixture_id='future',
              fixture_start_utc=1800005000,feature_cutoff_utc=1800000000,
              prediction_generated_at_utc=1800000100,
              home=dict(provider_id='TEAM-A'),away=dict(provider_id='TEAM-B'),
              input_asset=dict(sha256=digest(cut)))
    record=dict(snapshot_sha256=digest(snap))
    return snap,record,cut


class NativeReadOnlyIntegrationTests(unittest.TestCase):
    def test_sha_pinned_original_cut_uses_each_team_own_periods(self):
        snapshot,record,cut=records()
        original=copy.deepcopy(cut)
        report=profile(snapshot,record,cut)
        self.assertEqual(cut,original)
        self.assertEqual(report['evidence_basis'],'SHA_PINNED_ORIGINAL_CUT_AUDITED_SOURCE_RECEIPTS')
        simple=brief(report)
        self.assertEqual(simple['home']['n'],3)
        self.assertEqual(simple['away']['n'],3)
        self.assertNotEqual(simple['home']['observed_scoring_quarter_means'],
                            simple['away']['observed_scoring_quarter_means'])
        self.assertFalse(simple['home']['player_injury_coach_context_verified'])

    def test_original_historical_player_box_coverage_is_not_current_roster(self):
        p,r,c=records()
        original=copy.deepcopy(c)
        for side in ('home','away'):
            tid=('TEAM-A' if side=='home' else 'TEAM-B')
            if 'features' not in c:
                c['features']={}
            c['features'][side]=dict(team_id=tid,n_games=3,boxes=[])
        historical=c['history'][0]
        box=dict(fixture_id=historical['fixture_id'],
                 players=[dict(team_id='TEAM-A',player_id='p1',
                               minutes_display='24',points=10,
                               data_kind='POSTGAME_ACTUAL_NOT_PREMATCH_LINEUP')])
        c['features']['home']['boxes'].append([historical,box,'home','away'])
        stats=historical_player_box_coverage(c)
        self.assertEqual(stats['home']['historical_box_games_with_player_rows'],1)
        self.assertEqual(stats['home']['historical_player_rows_with_displayed_minutes'],1)
        self.assertEqual(stats['away']['historical_box_games_with_player_rows'],0)
        self.assertFalse(stats['home']['confirms_current_active_roster'])
        self.assertFalse(stats['home']['fitted_player_effects'])
        self.assertFalse(stats['home']['proves_future_minutes_or_injury'])
        self.assertEqual(original['history'],c['history'])

    def test_historical_player_box_duplicate_or_wrong_team_refused(self):
        p,r,c=records()
        h=c['history'][0]
        c['features']={
          'home':dict(team_id='TEAM-A',n_games=3,
                      boxes=[[h,dict(fixture_id=h['fixture_id'],
                                     players=[dict(team_id='TEAM-A',player_id='p1'),
                                              dict(team_id='TEAM-A',player_id='p1')]),
                              'home','away']]),
          'away':dict(team_id='TEAM-B',n_games=3,boxes=[])}
        with self.assertRaisesRegex(ValueError,'PLAYER_ID_CONFLICT'):
            historical_player_box_coverage(c)
        c['features']['home']['boxes'][0][1]['players'].pop()
        c['features']['home']['boxes'][0][2]='away'
        c['features']['home']['boxes'][0][3]='home'
        with self.assertRaisesRegex(ValueError,'BOX_HISTORICAL_IDENTITY'):
            historical_player_box_coverage(c)

    def test_original_snapshot_sha_mismatch_refused(self):
        p,r,c=records();r['snapshot_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'QUALITY_SNAPSHOT_PIN'):
            profile(p,r,c)

    def test_original_asset_tampering_refused(self):
        p,r,c=records();c['history'][0]['periods']['home'][0]+=1
        with self.assertRaisesRegex(ValueError,'INPUT_ASSET_PIN'):
            profile(p,r,c)

    def test_reject_hist_after_original_cut(self):
        p,r,c=records()
        c['history'][0]['ingested_at_utc']=p['prediction_generated_at_utc']+5
        p['input_asset']['sha256']=digest(c);r['snapshot_sha256']=digest(p)
        with self.assertRaisesRegex(ValueError,'HISTORICAL_ARRIVAL_AFTER'):
            profile(p,r,c)

    def test_target_fixture_mismatch_refused(self):
        p,r,c=records();c['target']['fixture_id']='wrong';p['input_asset']['sha256']=digest(c);r['snapshot_sha256']=digest(p)
        with self.assertRaisesRegex(ValueError,'CUT_IDENTITY_CLOCK'):
            profile(p,r,c)

if __name__=='__main__':unittest.main()
