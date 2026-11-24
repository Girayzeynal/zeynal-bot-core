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

    def test_legacy_verified_pregame_commit_is_descriptive_only_but_prior_for_future(self):
        legacy=self.row("old",index=0)
        legacy["prediction_generated_at_utc"]=None
        future=self.row("future",index=2)
        report=review(self.report([future,legacy]),asof_utc=self.now)
        self.assertEqual(report["first_forecasts"],2)
        self.assertEqual(report["matched_verified_finals"],2)
        self.assertEqual(report["first_forecasts_missing_generation_utc"],1)
        walk=report["walk_forward_shadow"][0]
        self.assertEqual(walk["descriptive_all_first_forecasts"]["n"],2)
        self.assertEqual(walk["original"]["n"],1)
        self.assertEqual(walk["exploratory_shadow"]["n"],1)
        self.assertEqual(walk["trace"][0]["fixture_id"],"future")
        self.assertEqual(walk["trace"][0]["prior_available_labels"],1)
        self.assertEqual(walk["excluded_shadow_targets_missing_generation"],1)
        self.assertFalse(report["calibration_applied_to_production"])

    def test_invalid_explicit_generation_clock_is_not_hidden_by_legacy_fallback(self):
        invalid=self.row("bad")
        invalid["prediction_generated_at_utc"]="not-a-time"
        result=review(self.report([invalid]),asof_utc=self.now)
        self.assertEqual(result["first_forecasts"],0)
        self.assertEqual(result["exclusions"]["INVALID_FIRST_PREMATCH_SNAPSHOT"],1)

    def test_ninety_nine_verified_games_do_not_wait_for_hundred(self):
        rows=[self.row("real-%03d" % i,generated=self.base+i*5000)
              for i in range(99)]
        report=review(self.report(rows),asof_utc=self.now)
        self.assertEqual(report["first_forecasts"],99)
        self.assertEqual(report["matched_verified_finals"],99)
        self.assertEqual(report["league_season_descriptives"][0]["metrics"]["n"],99)
        self.assertEqual(report["league_season_descriptives"][0]["metrics"]["total_mae"],20)
        self.assertEqual(report["walk_forward_shadow"][0]["exploratory_shadow"]["n"],99)
        self.assertFalse(report["historical_100_game_gate_required"])
        self.assertFalse(report["calibration_applied_to_production"])

    def test_android_isolated_launcher_invokes_readonly_audit_without_bot_or_git(self):
        import hashlib
        import json
        import os
        from pathlib import Path
        import subprocess
        import sys
        from tempfile import TemporaryDirectory
        from tests.test_ledger_reports import fixture as build_ledger
        launcher=Path(__file__).resolve().parents[1]/"scripts/run_isolated_test_bot.sh"
        with TemporaryDirectory() as tmp:
            home=Path(tmp)
            python_dir=home/"zeynal-hybrid-844/.venv/bin"
            python_dir.mkdir(parents=True)
            (python_dir/"python").symlink_to(sys.executable)
            db=home/"zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite"
            db.parent.mkdir(parents=True)
            build_ledger(db,settled=True,models=2)
            original=hashlib.sha256(db.read_bytes()).hexdigest()
            env=dict(os.environ,HOME=str(home))
            for mode in ("--first-forecast-audit","--first-forecast-audit-json"):
                outcome=subprocess.run(["bash",str(launcher),mode],env=env,
                                       capture_output=True,text=True,timeout=30)
                self.assertEqual(outcome.returncode,0,outcome.stderr)
                if mode.endswith("-json"):
                    payload=json.loads(outcome.stdout)
                    self.assertEqual(payload["first_forecasts"],1)
                    self.assertEqual(payload["matched_verified_finals"],1)
                else:
                    self.assertIn("Doğrulanmış sonuç: 1",outcome.stdout)
                    self.assertIn("SHADOW YOK",outcome.stdout)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),original)

    def test_android_launcher_missing_archive_fails_clean_without_creation(self):
        import os
        from pathlib import Path
        import subprocess
        import sys
        from tempfile import TemporaryDirectory
        launcher=Path(__file__).resolve().parents[1]/"scripts/run_isolated_test_bot.sh"
        with TemporaryDirectory() as tmp:
            home=Path(tmp)
            python_dir=home/"zeynal-hybrid-844/.venv/bin"
            python_dir.mkdir(parents=True)
            (python_dir/"python").symlink_to(sys.executable)
            env=dict(os.environ,HOME=str(home))
            out=subprocess.run(["bash",str(launcher),"--first-forecast-audit"],
                               env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(out.returncode,2)
            self.assertIn("FIRST_FORECAST_ARCHIVE_NOT_FOUND",out.stderr)
            self.assertFalse((home/"zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite").exists())

    def test_paired_shadow_diagnostics_are_fixture_matched(self):
        old=self.row("old",index=0,prediction=(110,110))
        newer=self.row("new",index=1,prediction=(110,110))
        out=review(self.report([newer,old]),asof_utc=self.now)
        diag=out["walk_forward_shadow"][0]["paired_shadow_diagnostics"]
        self.assertTrue(diag["paired_on_same_fixtures"])
        self.assertEqual(diag["n"],2)
        self.assertEqual((diag["improved"],diag["worsened"],diag["unchanged"]),(1,0,1))
        self.assertAlmostEqual(diag["average_delta"],-10/9)
        self.assertEqual(diag["best_improvements"][0]["fixture_id"],"new")
        self.assertIn("Eş maç karşılaştırması",render(out))
        self.assertFalse(diag["predictive_superiority_confirmed"])

    def test_shadow_can_worsen_even_with_correct_past_labels(self):
        old=self.row("old",index=0,prediction=(90,90))
        perfect=self.row("perfect",index=1,prediction=(100,100))
        report=review(self.report([old,perfect]),asof_utc=self.now)
        paired=report["walk_forward_shadow"][0]["paired_shadow_diagnostics"]
        self.assertEqual(paired["worsened"],1)
        self.assertEqual(paired["improved"],0)
        self.assertEqual(paired["unchanged"],1)
        self.assertEqual(paired["worst_regressions"][0]["fixture_id"],"perfect")
        self.assertGreater(paired["average_delta"],0)
        self.assertFalse(report["automatic_promotion"])

    def test_pending_fixtures_distinguish_not_started_missing_and_late_label(self):
        completed=self.row("missing-final",index=0,actual=None)
        future=self.row("future",index=3,generated=self.now-100,actual=None)
        late=self.row("late-label",index=4,label_available=self.now+400)
        out=review(self.report([completed,future,late]),asof_utc=self.now)
        self.assertEqual(out["first_forecasts"],3)
        self.assertEqual(out["pending"],3)
        self.assertEqual(out["matched_verified_finals"],0)
        reasons={f["fixture_id"]:f["reason"] for f in out["pending_fixtures"]}
        self.assertEqual(reasons,{
            "missing-final":"TIPOFF_PASSED_NATIVE_FINAL_NOT_VERIFIED",
            "future":"FIXTURE_NOT_STARTED_AT_ASOF",
            "late-label":"NATIVE_FINAL_LABEL_AFTER_ASOF",
        })
        self.assertIn("TIPOFF_PASSED_NATIVE_FINAL_NOT_VERIFIED",render(out))
        self.assertIn("ONE_SELECTED_EXISTING_SQLITE_LEDGER",out["report_scope"])

    def test_real_sqlite_commit_result_end_to_end_is_read_only(self):
        """Use actual native-authenticated SQLite fixture, not a trusted dict."""
        import hashlib
        import io
        import json
        from contextlib import redirect_stdout
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from ledger_reports import LedgerReports
        from tests.test_ledger_reports import fixture as build_ledger
        from hybrid_engine.first_forecast_walkforward import main
        with TemporaryDirectory() as tmp:
            db=Path(tmp)/"test.sqlite"
            build_ledger(db,settled=True,models=2)
            original=hashlib.sha256(db.read_bytes()).hexdigest()
            native=LedgerReports(db).read("NBA")
            report=review(native,asof_utc=self.now)
            self.assertEqual(report["first_forecasts"],1)
            self.assertEqual(report["matched_verified_finals"],1)
            self.assertEqual(report["first_forecasts_missing_generation_utc"],1)
            self.assertIsNone(report["first_prediction_utc"])
            self.assertIsNotNone(report["first_proven_snapshot_utc"])
            self.assertEqual(len(report["exact_fit_descriptives"]),1)
            self.assertEqual(report["walk_forward_shadow"][0]["predictions_with_prior"],0)
            self.assertEqual(report["walk_forward_shadow"][0]["exploratory_shadow"]["n"],0)
            self.assertEqual(report["walk_forward_shadow"][0]["comparison_status"],
                             "SHADOW_NOT_RUN_NO_VERIFIED_GENERATION_CLOCK")
            self.assertIn("SHADOW YOK", render(report))
            self.assertEqual(len(native["forecasts"]),2)
            output=io.StringIO()
            with redirect_stdout(output):
                main(["--ledger",str(db),"--league","NBA","--json"])
            cli=json.loads(output.getvalue())
            self.assertEqual(cli["first_forecasts"],1)
            self.assertEqual(cli["matched_verified_finals"],1)
            self.assertEqual(cli["source"],"LEDGER_REPORTS_NATIVE_AUTHENTICATED_FIRST_COMMIT")
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),original)

    def test_missing_sqlite_does_not_create_file(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from ledger_reports import LedgerReports
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"absent.sqlite"
            result=LedgerReports(path).read("NBA")
            with self.assertRaisesRegex(ValueError,"VERIFIED_READONLY"):
                review(result,asof_utc=self.now)
            self.assertFalse(path.exists())

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
