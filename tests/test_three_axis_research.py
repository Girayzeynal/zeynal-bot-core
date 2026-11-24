"""Research-only NBA three-axis regression: no model promotion or archive writes."""
from copy import deepcopy
import time
from unittest import TestCase

import numpy as np

from hybrid_engine.distributions import periods_for_scores
from hybrid_engine.three_axis_research import (
    stochastic_quarters_from_frozen_scores,conditional_bias_comparison,player_input_gate,
    quarter_comparison,_point_metrics,margin_preserving_comparison,_history_from_cut)


def verified_ledger(n=10,*,future_label_at=None):
    now=int(time.time())
    base=now-(n+5)*86400
    rows=[]
    for i in range(n):
        generated=base+i*86400+1000
        tip=generated+3600
        label=tip+5400
        if i==future_label_at:
            label=now-15
        # A synthetic +10 point systematic V1 home-team scoring bias.
        actual=[100,110]
        row=dict(league="NBA",season="2026/2027",fixture_id="fixture-%02d"%i,
            model_version="ELITE_HYBRID_NBA_BAYES_QMC_RESEARCH_V1",
            model_digest="d"*64,snapshot_sha256=("%064x"%(i+1)),
            prediction=[110.,110.],actual=actual,
            predicted_quarters=[[28.6,26.4],[27.5,28.6],[28.6,26.4],[25.3,28.6]],
            actual_periods=dict(home=[25,25,25,25],away=[28,27,28,27]),
            home="Home A",away="Away B",
            created_utc=generated+5,first_archived_at_utc=generated+8,
            prediction_generated_at_utc=generated,
            fixture_start_utc=tip,label_available_utc=label)
        rows.append(row)
    return dict(status="VERIFIED_LIVE_REPORT",scope="REGULATION_ONLY",
                query_read_only=True,research_backtests_included=False,
                forecasts=rows),now


class NBATriAxisResearchTests(TestCase):
    def test_conditional_bias_only_uses_already_available_labels(self):
        ledger,now=verified_ledger(10)
        immutable=deepcopy(ledger)
        result=conditional_bias_comparison(ledger,asof_utc=now)
        self.assertEqual(ledger,immutable)
        self.assertEqual(result["matched_verified_finals"],10)
        cohort=result["cohorts"][0]
        self.assertEqual(cohort["n"],10)
        self.assertLess(cohort["conditional_mae"],cohort["original_mae"])
        self.assertEqual(cohort["trace"][0]["adjustment"],[0.,0.])
        self.assertEqual(cohort["trace"][2]["home_team_history"],2)
        self.assertEqual(cohort["trace"][2]["adjustment"],[0.,0.])
        self.assertLess(cohort["trace"][3]["adjustment"][0],0.)
        for entry in cohort["trace"]:
            if entry["latest_prior_label_utc"] is not None:
                self.assertLess(entry["latest_prior_label_utc"],entry["generated_at_utc"])
            self.assertNotIn(entry["fixture_id"],entry["prior_fixture_ids"])
            self.assertLessEqual(abs(entry["adjustment"][0]),8.)
            self.assertLessEqual(abs(entry["adjustment"][1]),8.)
        self.assertFalse(result["automatic_promotion"])
        self.assertFalse(result["production_enabled"])

    def test_late_label_cannot_train_earlier_forecast(self):
        ledger,now=verified_ledger(10,future_label_at=0)
        result=conditional_bias_comparison(ledger,asof_utc=now)
        rows=result["cohorts"][0]["trace"]
        # Synthetic first game has a valid eventual result, but its label
        # was only available near now, long after later predictions.
        for r in rows[1:]:
            self.assertNotIn("fixture-00",r["prior_fixture_ids"])

    def test_reject_unverified_input_and_future_asof(self):
        ledger,now=verified_ledger()
        with self.assertRaises(ValueError):
            conditional_bias_comparison(dict(ledger,status="NOT_VERIFIED"),asof_utc=now)
        with self.assertRaises(ValueError):
            conditional_bias_comparison(ledger,asof_utc=now+3600)

    def test_dirichlet_uses_native_preforecast_labels_and_preserves_full_scores(self):
        rng=np.random.default_rng(9823)
        scores=np.stack((rng.integers(91,131,2000),rng.integers(87,133,2000)),axis=1).astype(np.int32)
        weights=np.array([[.26,.24],[.25,.26],[.26,.24],[.23,.26]])
        ledger,_=verified_ledger(10)
        for i,r in enumerate(ledger["forecasts"]):
            k=(i%5-2)*5
            r["actual_periods"]["home"]=[25+k,25-k,25,25]
            r["actual_periods"]["away"]=[28+k,27-k,28,27]
        target=ledger["forecasts"][-1]["snapshot_sha256"]
        original=periods_for_scores(scores,weights)
        candidate,meta=stochastic_quarters_from_frozen_scores(
            scores,ledger,target_sha256=target,seed=901)
        again,_=stochastic_quarters_from_frozen_scores(
            scores,ledger,target_sha256=target,seed=901)
        self.assertTrue(np.array_equal(candidate,again))
        self.assertTrue(np.array_equal(candidate.sum(axis=1),scores))
        self.assertTrue(np.array_equal(original.sum(axis=1),scores))
        self.assertEqual(meta["history"]["home"]["past_games"],9)
        self.assertEqual(meta["history"]["away"]["past_games"],9)
        self.assertTrue(meta["source_history_cutoff_verified"])
        self.assertNotIn("fixture-09",meta["history"]["home"]["native_fixture_ids"])
        self.assertLess(meta["history"]["home"]["latest_label_available_utc"],
                        ledger["forecasts"][-1]["prediction_generated_at_utc"])
        # Large controlled synthetic case demonstrates that per-quarter random
        # factors reduce the dependence built into deterministic apportionment.
        corr0=float(np.corrcoef(original[:,:,0].T)[0,1])
        corr1=float(np.corrcoef(candidate[:,:,0].T)[0,1])
        self.assertLess(corr1,corr0-.15)
        self.assertFalse(meta["uncertainty_calibrated"])
        self.assertFalse(meta["production_enabled"])
        tainted=deepcopy(ledger)
        tainted['forecasts'][-1]['predicted_quarters'][0][0]+=2
        with self.assertRaisesRegex(ValueError,'ORIGINAL_SNAPSHOT_MEANS'):
            stochastic_quarters_from_frozen_scores(scores,tainted,
                target_sha256=target)

    def test_insufficient_or_future_quarter_evidence_abstains(self):
        from hybrid_engine.data import Abstain
        scores=np.full((30,2),100,dtype=np.int32)
        weights=np.ones((4,2))
        ledger,_=verified_ledger(10)
        with self.assertRaises(Abstain):
            stochastic_quarters_from_frozen_scores(scores,ledger,
                target_sha256=ledger["forecasts"][4]["snapshot_sha256"])
        with self.assertRaises(ValueError):
            stochastic_quarters_from_frozen_scores(scores,ledger,
                target_sha256=ledger["forecasts"][-1]["snapshot_sha256"],
                concentration=0)
        ledger["forecasts"][0]["label_available_utc"]=int(time.time())-10
        _,meta=stochastic_quarters_from_frozen_scores(scores,ledger,
            target_sha256=ledger["forecasts"][-1]["snapshot_sha256"])
        self.assertNotIn("fixture-00",meta["history"]["home"]["native_fixture_ids"])
        ledger["forecasts"][0]["label_available_utc"]=ledger["forecasts"][0]["fixture_start_utc"]+5400
        ledger["forecasts"][0]["first_archived_at_utc"]=ledger["forecasts"][0]["fixture_start_utc"]+1
        with self.assertRaises(ValueError):
            stochastic_quarters_from_frozen_scores(scores,ledger,
                target_sha256=ledger["forecasts"][-1]["snapshot_sha256"])

    def test_player_gate_does_not_invent_minutes_or_score_effect(self):
        output=player_input_gate(None,asof_utc=int(time.time()),fixture={"fixture_id":"A"})
        self.assertEqual(output["status"],"BLOCKED_NO_VERIFIED_PREMATCH_MINUTES")
        self.assertFalse(output["player_effect_applied"])
        with self.assertRaises(ValueError):
            player_input_gate({"payload":{},"sha256":"not-a-proof"},
                              asof_utc=int(time.time()),fixture={"fixture_id":"A"})

    def test_paired_quarter_audit_is_readonly_and_target_result_not_used_as_input(self):
        ledger,now=verified_ledger(10)
        immutable=deepcopy(ledger)
        result=quarter_comparison(ledger,asof_utc=now,scenarios=1024)
        self.assertEqual(ledger,immutable)
        self.assertEqual(result["verified_finals"],10)
        self.assertEqual(result["paired_n"],4)
        self.assertEqual(result["excluded"]["SIX_VERIFIED_PAST_QUARTER_GAMES_PER_SIDE_REQUIRED"],6)
        self.assertEqual(set(result["cohorts"][0]["metrics"]),{"1Q","2Q","3Q","4Q","1H","2H"})
        self.assertFalse(result["actual_target_scores_used_as_inputs"])
        self.assertFalse(result["production_enabled"])
        for item in result["trace"]:
            self.assertEqual(item["fixed_predicted_scores"],[110,110])
            for m in item["markets"].values():
                self.assertGreaterEqual(m["candidate_crps"],0.)
        last=result["trace"][-1]
        altered=deepcopy(ledger)
        altered["forecasts"][-1]["actual"]=[120,110]
        altered["forecasts"][-1]["actual_periods"]["home"]=[30,30,30,30]
        replay=quarter_comparison(altered,asof_utc=now,scenarios=1024)["trace"][-1]
        self.assertEqual(last["history"],replay["history"])
        self.assertEqual(last["fixed_predicted_scores"],replay["fixed_predicted_scores"])
        self.assertNotEqual(last["markets"],replay["markets"])

    def test_score_components_do_not_hide_team_and_margin_errors(self):
        rows=[dict(forecast_before=[120,90],forecast_candidate=[110,100],
                   regulation_actual=[100,110])]
        m=_point_metrics(rows)
        self.assertEqual(m["total"]["original_mae"],0.)
        self.assertEqual(m["margin"]["original_mae"],40.)
        self.assertEqual(m["margin"]["candidate_mae"],20.)
        self.assertEqual(m["home"]["original_bias"],20.)
        self.assertEqual(m["away"]["original_bias"],-20.)
        self.assertIsNone(_point_metrics([]))

    def test_common_mode_candidate_does_not_worsen_margin_by_changing_it(self):
        row=dict(forecast_before=[120.,90.],forecast_candidate=[112.,91.],
                 adjustment=[-8.,1.],regulation_actual=[100.,110.])
        result=margin_preserving_comparison([row])
        self.assertTrue(result["margin_preserved"])
        self.assertEqual(result["score_components"]["margin"]["original_mae"],
                         result["score_components"]["margin"]["candidate_mae"])
        self.assertFalse(result["production_enabled"])

    def test_original_feature_history_removes_dependency_on_forecast_count(self):
        from unittest.mock import patch
        from hybrid_engine.data import STRICT
        ledger,now=verified_ledger(1)
        target=ledger["forecasts"][0]
        clock=target["prediction_generated_at_utc"]
        history=[]
        for i in range(8):
            ts=clock-(i+1)*86400
            history.append(dict(fixture_id="native-"+str(i),league="NBA",season=target["season"],
                home_team_id="1",away_team_id="2",fixture_start_utc=ts-9000,
                observed_at_utc=ts-1,ingested_at_utc=ts,
                periods={"home":[24,25,26,25],"away":[25,26,27,26]}))
        cut=dict(target=dict(fixture_id=target["fixture_id"],league="NBA",season=target["season"],
            fixture_start_utc=target["fixture_start_utc"],home_team_id="1",away_team_id="2"),
            cutoff_utc=clock-1,evaluation_class=STRICT,history=history,
            features={side:{"recent_game_ids":[r["fixture_id"] for r in history]}
                      for side in ("home","away")})
        with patch("hybrid_engine.data.available_at",side_effect=lambda r,mode:r["ingested_at_utc"]):
            report=quarter_comparison(ledger,asof_utc=now,scenarios=1024,cut_loader=lambda r:cut)
            self.assertEqual(report["paired_n"],1)
            self.assertEqual(report["history_source"],"ORIGINAL_FROZEN_FEATURE_CUT")
            self.assertEqual(report["trace"][0]["history"]["home"]["past_games"],8)
            tainted=deepcopy(cut)
            tainted["history"][0]["ingested_at_utc"]=clock+1
            with self.assertRaisesRegex(ValueError,"QUARTER_FROZEN_HISTORY_CLOCK"):
                _history_from_cut(tainted,target,"home")
            denied=quarter_comparison(ledger,asof_utc=now,scenarios=1024,cut_loader=lambda r:tainted)
            self.assertEqual(denied["paired_n"],0)
            self.assertEqual(sum(denied["excluded"].values()),1)
