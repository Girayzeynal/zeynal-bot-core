"""Boundary and causality regressions for read-only first-forecast shadow analysis."""
import copy
import time
import unittest

from hybrid_engine.first_forecast_walkforward import review, render, VERSION


class FirstForecastWalkForwardTests(unittest.TestCase):
    def setUp(self):
        # Fixed relative clock; all synthetic finals are already available.
        self.now = int(time.time())
        self.base = self.now - 10 * 86400

    def report(self, rows):
        return dict(status="VERIFIED_LIVE_REPORT", scope="REGULATION_ONLY",
                    query_read_only=True, research_backtests_included=False,
                    forecasts=rows)

    def row(self, ident="match-1", index=0, *, generated=None,
            prediction=(110.0, 110.0), actual=(100, 100),
            label_available=None, digest=None, version="ORIGINAL_V1",
            season="2026/2027"):
        generated = self.base + index*86400 if generated is None else generated
        tip = generated + 3600
        return dict(league="NBA", season=season, fixture_id=ident,
                    model_version=version, model_digest=digest or "a"*64,
                    prediction=list(prediction),
                    prediction_generated_at_utc=generated,
                    created_utc=generated+1, first_archived_at_utc=generated+2,
                    fixture_start_utc=tip, snapshot_sha256=("%064x" % (index+1)),
                    actual=list(actual) if actual is not None else None,
                    label_available_utc=(tip+3600 if label_available is None else label_available)
                    if actual is not None else None,
                    actual_periods={"home":[25,25,25,25], "away":[25,25,25,25]}
                    if actual is not None else None)

    def test_single_verified_first_forecast_reports_without_hundred_gate(self):
        one=self.row()
        result=review(self.report([one]),asof_utc=self.now)
        self.assertEqual(result["format"],VERSION)
        self.assertEqual(result["first_forecasts"],1)
        self.assertEqual(result["matched_verified_finals"],1)
        self.assertEqual(result["league_season_descriptives"][0]["metrics"]["total_mae"],20)
        self.assertFalse(result["historical_100_game_gate_required"])
        self.assertEqual(result["walk_forward_shadow"][0]["predictions_with_prior"],0)
        self.assertEqual(result["walk_forward_shadow"][0]["trace"][0]["adjustment"],[0,0])
        self.assertFalse(result["calibration_applied_to_production"])
        self.assertIn("100 maç şartı yok", render(result))

    def test_earliest_archive_wins_even_when_later_revised_model_has_smaller_error(self):
        first=self.row(prediction=(110,110))
        revised=self.row(prediction=(100,100),version="REVISED_V3",digest="b"*64)
        revised["created_utc"]+=100
        revised["prediction_generated_at_utc"]+=100
        revised["first_archived_at_utc"]+=100
        revised["snapshot_sha256"]="f"*64
        result=review(self.report([revised, first]),asof_utc=self.now)
        self.assertEqual(result["first_forecasts"],1)
        self.assertEqual(result["matched_verified_finals"],1)
        self.assertEqual(result["league_season_descriptives"][0]["metrics"]["total_mae"],20)
        self.assertEqual(result["walk_forward_shadow"][0]["trace"][0]["original_snapshot_sha256"],
                         first["snapshot_sha256"])

    def test_walk_forward_uses_only_labels_available_before_forecast(self):
        a=self.row("a",index=0)
        b=self.row("b",index=1)
        c=self.row("c",index=2)
        result=review(self.report([c,b,a]),asof_utc=self.now)
        trace=result["walk_forward_shadow"][0]["trace"]
        self.assertEqual([x["fixture_id"] for x in trace],["a","b","c"])
        self.assertEqual([x["prior_available_labels"] for x in trace],[0,1,2])
        self.assertAlmostEqual(trace[1]["prediction"][0],110-10/9)
        self.assertAlmostEqual(trace[2]["prediction"][0],108)
        self.assertLess(result["walk_forward_shadow"][0]["exploratory_shadow"]["total_mae"],
                        result["walk_forward_shadow"][0]["original"]["total_mae"])
        self.assertFalse(result["superiority_claim"])

    def test_delayed_label_never_leaks_into_later_pregame_model(self):
        a=self.row("a",index=0)
        a["label_available_utc"]=self.base+3*86400
        b=self.row("b",index=1)
        result=review(self.report([a,b]),asof_utc=self.now)
        tr=result["walk_forward_shadow"][0]["trace"]
        self.assertEqual([x["prior_available_labels"] for x in tr],[0,0])
        self.assertEqual(tr[1]["prediction"],b["prediction"])

    def test_later_label_at_asof_remains_pending_but_original_is_counted(self):
        a=self.row("a",index=0)
        a["label_available_utc"]=self.now+100
        result=review(self.report([a]),asof_utc=self.now)
        self.assertEqual(result["first_forecasts"],1)
        self.assertEqual(result["pending"],1)
        self.assertEqual(result["matched_verified_finals"],0)
        self.assertEqual(result["walk_forward_shadow"],[])

    def test_fitted_shas_have_separate_descriptives_but_shared_declared_strategy(self):
        a=self.row("a",index=0,digest="a"*64)
        b=self.row("b",index=1,digest="b"*64)
        result=review(self.report([a,b]),asof_utc=self.now)
        self.assertEqual(len(result["exact_fit_descriptives"]),2)
        self.assertEqual(len(result["walk_forward_shadow"]),1)
        w=result["walk_forward_shadow"][0]
        self.assertEqual(w["exact_fit_versions"],2)
        self.assertEqual(w["strategy_kind"],"CHRONOLOGICAL_MODEL_VERSION_NOT_SINGLE_FIT")
        self.assertFalse(result["superiority_claim"])

    def test_different_model_versions_or_seasons_never_share_bias_training(self):
        a=self.row("a",index=0,version="V1")
        b=self.row("b",index=1,version="V2")
        c=self.row("c",index=2,version="V1",season="2025/2026")
        result=review(self.report([a,b,c]),asof_utc=self.now)
        self.assertEqual(len(result["walk_forward_shadow"]),3)
        self.assertTrue(all(x["predictions_with_prior"]==0 for x in result["walk_forward_shadow"]))

    def test_same_time_different_source_pins_is_ambiguous_not_double_counted(self):
        a=self.row("a")
        b=copy.deepcopy(a);b["snapshot_sha256"]="f"*64
        result=review(self.report([a,b]),asof_utc=self.now)
        self.assertEqual(result["first_forecasts"],0)
        self.assertEqual(result["exclusions"]["AMBIGUOUS_SIMULTANEOUS_FIRST_FORECAST"],1)

    def test_regulation_and_timestamp_validation_fail_closed(self):
        row=self.row()
        bad=copy.deepcopy(row);bad["actual_periods"]["home"]=[26,25,25,25]
        with self.assertRaisesRegex(ValueError,"REGULATION"):
            review(self.report([bad]),asof_utc=self.now)
        bad=copy.deepcopy(row);bad["label_available_utc"]=bad["fixture_start_utc"]
        with self.assertRaisesRegex(ValueError,"FINAL_OR_CLOCK"):
            review(self.report([bad]),asof_utc=self.now)

    def test_future_prediction_and_invalid_native_source_are_not_accepted(self):
        row=self.row()
        broken=copy.deepcopy(row);broken["created_utc"]=broken["prediction_generated_at_utc"]-1
        result=review(self.report([row,broken]),asof_utc=self.now)
        self.assertEqual(result["first_forecasts"],1)
        self.assertEqual(result["exclusions"]["INVALID_FIRST_PREMATCH_SNAPSHOT"],1)
        bad=self.report([row]);bad["research_backtests_included"]=True
        with self.assertRaisesRegex(ValueError,"VERIFIED_READONLY"):
            review(bad,asof_utc=self.now)
        with self.assertRaisesRegex(ValueError,"VERIFIED_READONLY"):
            review(self.report([row]),asof_utc=self.now+86400)

    def test_conflicting_real_result_for_same_fixture_is_rejected(self):
        a=self.row()
        b=copy.deepcopy(a);b["actual"]=[101,100]
        b["actual_periods"]["home"]=[26,25,25,25]
        b["first_archived_at_utc"]+=10
        b["snapshot_sha256"]="f"*64
        with self.assertRaisesRegex(ValueError,"CONFLICTING_NATIVE_FINAL"):
            review(self.report([a,b]),asof_utc=self.now)


if __name__=="__main__":
    unittest.main()
