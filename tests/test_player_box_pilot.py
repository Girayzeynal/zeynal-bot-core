"""Offline real-shape player box research pilot, no production or providers."""
from copy import deepcopy
import time
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.player_box_pilot import verified_box_rows,fit_box_association,rotation,scenario,paired_holdout

BASE=1760000000

def fixture(i):
    tip=BASE+i*86400
    players=[]
    for team,side in (("1","home"),("2","away")):
        for j in range(8):
            players.append(dict(player_id=team+str(100+j),team_id=team,side=side,
                minutes_display="30:00",did_not_play=False,
                data_kind="POSTGAME_ACTUAL_NOT_PREMATCH_LINEUP"))
    src=dict(observed_at_utc=tip+7200,ingested_at_utc=tip+7210)
    box=dict(league="NBA",season="2026/2027",fixture_id=str(i),
        fixture_start_utc=tip,home_team_id="1",away_team_id="2",
        scope="FINAL_WITH_OT",regulation_eligible=True,
        teams=dict(home=dict(points=100+i%8),away=dict(points=99+i%6)),
        players=players,source=src,source_digest=digest(src))
    return dict(league="NBA",season="2026/2027",fixture_id=str(i),
        fixture_start_utc=tip,home_team_id="1",away_team_id="2",
        periods=dict(home=[25,25,25,25+i%8],away=[25,25,25,24+i%6]),
        observed_at_utc=tip+7200,ingested_at_utc=tip+7210,
        source_catalog_sha256="a"*64,box=box)


class HistoricalBoxPilotTests(TestCase):
    def setUp(self):
        self.cut=BASE+45*86400
        self.time=patch("time.time",return_value=self.cut);self.time.start()
        self.addCleanup(self.time.stop)
        self.cohort=[[fixture(i)] for i in range(40)]
    def test_real_postgame_training_can_fit_independently_of_pregame_minutes_archive(self):
        rows,excluded=verified_box_rows(self.cohort,self.cut)
        self.assertEqual(len(rows),40)
        model=fit_box_association(rows,self.cut)
        self.assertEqual(model["status"],"REAL_HISTORICAL_BOX_MODEL_FITTED_RESEARCH_ONLY")
        self.assertEqual(model["training_games"],40)
        self.assertEqual(len(model["players"]),16)
        self.assertFalse(model["causal_player_effect"])
        self.assertFalse(model["production_enabled"])
        self.assertFalse(model["confirmed_lineup"])
        target=dict(fixture_id="future",fixture_start_utc=self.cut+7200,
                    home_team_id="1",away_team_id="2")
        outcome=scenario(model,rows,target,self.cut)
        self.assertEqual(outcome["status"],"CONDITIONAL_HISTORICAL_PLAYER_SENSITIVITY_NOT_AN_INJURY_FORECAST")
        self.assertEqual(len(outcome["scenarios"]),2)
        self.assertTrue(all(v["verified_injured"] is False for v in outcome["scenarios"]))
        self.assertIsNotNone(rotation(rows,"1",self.cut))
    def test_cannot_train_on_future_box_or_backdate_source_observation(self):
        expanded=deepcopy(self.cohort)
        expanded.append([fixture(46)])
        r,_=verified_box_rows(expanded,self.cut)
        self.assertEqual(len(r),40)
        late=deepcopy(self.cohort)
        late[0][0]["box"]["source"]["ingested_at_utc"]=self.cut+1
        late[0][0]["box"]["source_digest"]=digest(late[0][0]["box"]["source"])
        valid,_=verified_box_rows(late,self.cut)
        self.assertEqual(len(valid),39)
        with self.assertRaises(ValueError):
            fit_box_association(valid+[dict(valid[0],available_at_utc=self.cut+1)],self.cut)
    def test_incomplete_player_minutes_excluded_not_silently_assumed(self):
        broken=deepcopy(self.cohort)
        broken[0][0]["box"]["players"][0]["minutes_display"]=None
        valid,rejected=verified_box_rows(broken,self.cut)
        self.assertEqual(len(valid),39)
        self.assertEqual(rejected["INVALID_PAST_PLAYER_MINUTES"],1)
    def test_matched_historical_holdout_requires_pregame_clock_and_no_backfilling(self):
        expanded=[[fixture(i)] for i in range(80)]
        r,_=verified_box_rows(expanded,self.cut)
        # The clock at self.cut excludes all future games, so no hidden score
        # can enter this holdout, whatever the requested exploratory mode.
        self.assertEqual(len(r),45)
        self.assertEqual(paired_holdout(r,now_utc=self.cut)["matched_test_games"],0)
        far=BASE+90*86400
        with patch("time.time",return_value=far):
            source,_=verified_box_rows(expanded,far)
            self.assertEqual(len(source),80)
            strict=paired_holdout(source,now_utc=far)
            assumed=paired_holdout(source,now_utc=far,assumed_availability=True)
            self.assertGreater(assumed["matched_test_games"],0)
            self.assertEqual(assumed["status"],"ASSUMED_AVAILABILITY_RESEARCH_ONLY")
            self.assertFalse(assumed["prospective_accuracy_evidence"])
            self.assertFalse(assumed["automatic_promotion"])
            self.assertTrue(assumed["model_selected_after_actuals"])
            self.assertAlmostEqual(assumed["total_mae_improvement"],
                assumed["control_total_mae"]-assumed["candidate_total_mae"],places=3)
            self.assertEqual(strict["evidence_class"],"VERIFIED_SOURCE_CLOCKS_RETROSPECTIVE_HOLDOUT")
            self.assertEqual(strict["total_games"],80)
            self.assertEqual(strict["matched_test_games"],assumed["matched_test_games"])

    def test_team_only_control_has_no_player_parameters(self):
        rows,_=verified_box_rows(self.cohort,self.cut)
        team=fit_box_association(rows,self.cut,include_players=False)
        self.assertEqual(team["players"],[])
        self.assertEqual(team["estimated_parameters"],2+2*len(team["teams"]))
        self.assertEqual(team["fit_kind"],"TEAM_ONLY_SAME_BOX_COHORT")
        with self.assertRaisesRegex(ValueError,"EXPLICIT_COHORT_CONTROL"):
            fit_box_association(rows,self.cut,include_players=1)

    def test_no_hypothetical_scenario_published_after_tipoff(self):
        rows,_=verified_box_rows(self.cohort,self.cut)
        model=fit_box_association(rows,self.cut)
        target=dict(fixture_id="future",fixture_start_utc=self.cut+900,home_team_id="1",away_team_id="2")
        self.assertEqual(scenario(model,rows,target,self.cut)["status"],"CLOSED_PREGAME_WINDOW")
        target["fixture_start_utc"]=self.cut+7200
        target["fixture_id"]=rows[0]["fixture_id"]
        with self.assertRaises(ValueError):scenario(model,rows,target,self.cut)
