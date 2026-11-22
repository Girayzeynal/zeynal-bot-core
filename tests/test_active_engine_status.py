"""Synthetic running-process and missing-source status for research modules."""
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from hybrid_engine.active_engine_status import describe


class EngineActivationTests(TestCase):
    def test_no_worker_means_not_active_not_fake_player_effect(self):
        with TemporaryDirectory() as root:
            with patch("hybrid_engine.player_shadow.readiness",
                       return_value=dict(status="BLOCKED_NO_PROSPECTIVE_PLAYER_MINUTES",
                                         prospective_minutes_games=0,prepared_artifacts=0,
                                         production_enabled=False)):
                x=describe({},root,now=1790000000)
        self.assertEqual(x["status"],"NO_RESEARCH_WORKER_INSTALLED")
        self.assertFalse(x["modes"]["player_minutes"]["valid_prospective_packet_confirmed"])
        self.assertFalse(x["modes"]["player_shadow"]["separately_trained_athlete_effects_active_in_main_score"])
        self.assertFalse(x["modes"]["adaptive_models"]["runtime_worker_installed"])
        self.assertTrue(x["does_not_generate_a_new_prediction"])

    def test_real_in_process_worker_attempts_not_same_as_production_score(self):
        worker=SimpleNamespace(sequence=2,last_report=dict(
            status="PARTIAL_ABSTAIN",completed_at_utc=1790000000,
            groups={"NBA":{"status":"ABSTAIN","native_training_games":54,
                           "native_box_games":34}},
            player_inputs=dict(status="BLOCKED",reason="FRESH_COMPLETE_ROSTER_REQUIRED"),
            player_capture=dict(status="ABSTAIN",reason="UNTRAINED")))
        cycle=SimpleNamespace(stages={"adaptive_v2":{"status":"COMPLETED"}})
        state=dict(adaptive_v2_worker=worker,research_cycle=cycle)
        with patch("hybrid_engine.player_shadow.readiness",
                   return_value=dict(status="BLOCKED_NO_PROSPECTIVE_PLAYER_MINUTES",
                                     prospective_minutes_games=0,prepared_artifacts=0,
                                     production_enabled=False)):
            x=describe(state,"/tmp/isolated",now=1790001000)
        self.assertEqual(x["status"],"RESEARCH_ACTIVATION_OBSERVED")
        self.assertEqual(x["modes"]["adaptive_models"]["job_sequence"],2)
        self.assertEqual(x["modes"]["adaptive_models"]["competition_groups"]["NBA"]["native_box_games"],34)
        self.assertEqual(x["modes"]["player_minutes"]["reason"],"FRESH_COMPLETE_ROSTER_REQUIRED")
        self.assertFalse(x["modes"]["player_minutes"]["valid_prospective_packet_confirmed"])
        self.assertFalse(x["scoring"]["main_model_uses_player_shadow_coefficients"])
        self.assertFalse(x["production_changed"])

    def test_valid_prospective_minutes_is_evidence_not_player_model_promotion(self):
        state=dict(adaptive_v2_worker=SimpleNamespace(
           sequence=1,last_report=dict(
             player_inputs={"status":"PROSPECTIVE_MINUTES_ARCHIVED"},
             player_capture={"status":"ARCHIVED"},
             groups={"NBA":{"status":"SCHEDULED_MODEL_AVAILABLE"}})))
        with patch("hybrid_engine.player_shadow.readiness",
                   return_value=dict(status="WAITING_FOR_OFFLINE_FIT",
                                     prospective_minutes_games=1,prepared_artifacts=0)):
            x=describe(state,"/tmp/isolated",now=1790001000)
        self.assertTrue(x["modes"]["player_minutes"]["valid_prospective_packet_confirmed"])
        self.assertEqual(x["modes"]["player_shadow"]["latest_player_bayes_candidate_status"],"ARCHIVED")
        self.assertFalse(x["scoring"]["main_model_uses_verified_player_minutes"])
        self.assertFalse(x["scoring"]["main_model_automatically_selects_adaptive_model"])


    def test_running_phase_and_real_minutes_are_visible_before_adaptive_model_finishes(self):
        worker=SimpleNamespace(sequence=1,progress=dict(
            phase="PREGAME_PLAYER_MINUTES_SOURCE",phase_at_utc=1790000990,
            started_at_utc=1790000980,player_input_status="RUNNING",
            source_scope=None,fixture_id="original-future"),last_report=None)
        cycle=SimpleNamespace(stages={"adaptive_v2":{"status":"RUNNING"}})
        with patch("hybrid_engine.player_shadow.readiness",
                   return_value=dict(status="BLOCKED_NO_PROSPECTIVE_PLAYER_MINUTES",
                                     prospective_minutes_games=0,prepared_artifacts=0)):
            x=describe(dict(adaptive_v2_worker=worker,research_cycle=cycle),
                       "/tmp/isolated",now=1790001000)
        self.assertTrue(x["modes"]["player_minutes"]["actual_research_collection_attempt"])
        self.assertEqual(x["modes"]["player_minutes"]["last_status"],"RUNNING")
        self.assertFalse(x["modes"]["player_minutes"]["valid_prospective_packet_confirmed"])
        self.assertEqual(x["modes"]["adaptive_models"]["live_phase"],"PREGAME_PLAYER_MINUTES_SOURCE")
        self.assertEqual(x["modes"]["adaptive_models"]["live_phase_elapsed_seconds"],10)
        self.assertFalse(x["scoring"]["main_model_uses_verified_player_minutes"])

    def test_live_phase_reports_blocker_before_adaptive_fit_finishes(self):
        worker=SimpleNamespace(sequence=1,progress=dict(
            phase="FETCH_MISSING_NATIVE_BOXSCORES",phase_at_utc=1790000970,
            started_at_utc=1790000950,player_input_status="BLOCKED",
            player_input_reason="CURRENT_ROSTER_SOURCE_REVIEW_REQUIRED",
            player_input_completed_at_utc=1790000975,
            player_input_corroboration=dict(
                missing_absence_count=1,official_stage="INDEX_FETCH",
                official_http_status=429,latest_report_verified=False,
                official_fixture_rows=0,examples=[dict(team="TestHome",
                    player_id="100",missing_sources=["NBA_OFFICIAL_PDF"])]),
            source_scope="NBA",fixture_id="original-future"),last_report=None)
        with patch("hybrid_engine.player_shadow.readiness",
                   return_value=dict(status="BLOCKED_NO_PROSPECTIVE_PLAYER_MINUTES",
                                     prospective_minutes_games=0,prepared_artifacts=0)):
            x=describe(dict(adaptive_v2_worker=worker),"/tmp/isolated",now=1790001000)
        self.assertEqual(x["modes"]["player_minutes"]["last_status"],"BLOCKED")
        self.assertEqual(x["modes"]["player_minutes"]["reason"],"CURRENT_ROSTER_SOURCE_REVIEW_REQUIRED")
        self.assertEqual(x["modes"]["player_minutes"]["source_attempt_completed_at_utc"],1790000975)
        corroboration=x["modes"]["player_minutes"]["absence_source_corroboration"]
        self.assertEqual(corroboration["missing_absence_count"],1)
        self.assertEqual(corroboration["examples"][0]["missing_sources"],["NBA_OFFICIAL_PDF"])
        self.assertEqual(corroboration["official_http_status"],429)
        self.assertFalse(x["modes"]["player_minutes"]["valid_prospective_packet_confirmed"])
        self.assertEqual(x["modes"]["adaptive_models"]["live_phase_source_scope"],"NBA")
        self.assertEqual(x["modes"]["adaptive_models"]["live_phase_elapsed_seconds"],30)
        self.assertEqual(x["modes"]["adaptive_models"]["latest_status"],
                         "NO_ADAPTIVE_RESEARCH_REPORT_OBSERVED")

    def test_negative_clock_or_invalid_state_rejected(self):
        with self.assertRaisesRegex(ValueError,"POSITIVE_CLOCK"):
            describe({},None,now=0)
        with self.assertRaisesRegex(ValueError,"APPLICATION_STATE"):
            describe(None,None,now=1790001000)
