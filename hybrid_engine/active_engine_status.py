"""Real process runtime inventory: three research engines and score isolation.

No network, training, command execution, external credentials, prediction
or original ledger mutation. Module availability != active research run !=
verified numerical input to the main Telegram score.
"""
from pathlib import Path
import time

VERSION="ACTUAL_NBA_PLAYER_ADAPTIVE_ENGINE_RUNTIME_V1"


def describe(state, root, *, now=None):
    if not isinstance(state,dict):
        raise ValueError("ENGINE_RUNTIME_APPLICATION_STATE_REQUIRED")
    if now is None:now=int(time.time())
    if type(now) is not int or now<=0:
        raise ValueError("ENGINE_RUNTIME_POSITIVE_CLOCK_REQUIRED")
    worker=state.get("adaptive_v2_worker")
    cycle=state.get("research_cycle")
    report=state.get("last_adaptive_v2_poll")
    if not isinstance(report,dict):
        report=getattr(worker,"last_report",None)
    if not isinstance(report,dict):report={}
    stages=(getattr(cycle,"stages",{}) or {}) if cycle is not None else {}
    if not isinstance(stages,dict):stages={}
    adaptive_status=stages.get("adaptive_v2",{}) or {}
    last_check=report.get("completed_at_utc") or report.get("evaluated_at_utc")
    player_inputs=report.get("player_inputs") if isinstance(report.get("player_inputs"),dict) else {}
    player_capture=report.get("player_capture") if isinstance(report.get("player_capture"),dict) else {}
    research_paths=state.get("research_protocol_directories")
    if not isinstance(research_paths,dict):research_paths={}
    # Reveal no device filesystem paths; only the deterministic protocol IDs.
    protocol_ids={k:Path(v).name for k,v in research_paths.items()
                  if k in ("adaptive_v2","nba_v3","current_assessment")
                  and isinstance(v,str) and v}
    progress=getattr(worker,"progress",{}) if worker is not None else {}
    if not isinstance(progress,dict):progress={}
    phase=progress.get("phase","NOT_STARTED")
    phase_at=progress.get("phase_at_utc")
    input_status=progress.get("player_input_status") or player_inputs.get("status") or "NO_PREGAME_MINUTES_ATTEMPT_OBSERVED"
    attempted=input_status not in ("NO_ATTEMPT_OBSERVED","NO_PREGAME_MINUTES_ATTEMPT_OBSERVED","NO_ELIGIBLE_NBA_OR_PRETIPOFF_SNAPSHOT")
    # Read only the already created research store; this is not a source request.
    shadow=dict(status="READINESS_UNAVAILABLE",prospective_minutes_games=None,
                prepared_artifacts=None,production_enabled=False)
    if root is not None:
        folder=Path(root).expanduser().absolute()/"player-shadow"
        try:
            from hybrid_engine.player_shadow import readiness
            shadow=readiness(folder)
        except (ValueError,KeyError,TypeError,OSError):
            shadow["status"]="LOCAL_PLAYER_SHADOW_EVIDENCE_UNAVAILABLE"
    teams={}
    for league in ("NBA","EUROLEAGUE","EUROCUP"):
        value=report.get("groups",{}).get(league,{}) if isinstance(report.get("groups"),dict) else {}
        teams[league]=dict(status=value.get("status","NOT_OBSERVED"),
                           native_history_games=value.get("native_training_games"),
                           native_box_games=value.get("native_box_games"))
    return dict(
        format=VERSION,examined_at_utc=now,
        separate_research_protocol_ids=protocol_ids,
        modes=dict(player_minutes=dict(
                       code_loaded=worker is not None,
                       actual_research_collection_attempt=attempted,
                       last_status=input_status,
                       reason=progress.get("player_input_reason") or player_inputs.get("reason"),
                       source_attempt_completed_at_utc=progress.get("player_input_completed_at_utc"),
                       valid_prospective_packet_confirmed=input_status in
                        ("PROSPECTIVE_MINUTES_ARCHIVED","EXISTING_MINUTES_REPLAY")),
                   player_shadow=dict(code_importable=True,
                       background_witness_stage=(stages.get("player_shadow") or {}).get("status","NOT_OBSERVED"),
                       last_background_witness_status=(state.get("last_player_shadow_poll") or {}).get("status","NO_WITNESS_ATTEMPT_OBSERVED"),
                       readiness=shadow.get("status"),
                       observed_prospective_minutes_games=shadow.get("prospective_minutes_games"),
                       prepared_model_artifacts=shadow.get("prepared_artifacts"),
                       latest_player_bayes_candidate_status=player_capture.get("status","NO_PLAYER_BAYES_FORECAST_OBSERVED"),
                       separately_trained_athlete_effects_active_in_main_score=False),
                   adaptive_models=dict(
                       runtime_worker_installed=worker is not None,
                       research_cycle_installed=cycle is not None,
                       background_stage=adaptive_status.get("status","NOT_OBSERVED"),
                       job_sequence=getattr(worker,"sequence",None),
                       live_phase=phase,
                       live_phase_started_at_utc=phase_at,
                       live_phase_elapsed_seconds=max(0,now-phase_at) if type(phase_at) is int else None,
                       live_phase_source_scope=progress.get("source_scope"),
                       live_fixture_id=progress.get("fixture_id"),
                       original_scan_counts=progress.get("original_scan_counts"),
                       original_scan_position=progress.get("original_scan_position"),
                       original_scan_total=progress.get("original_scan_total"),
                       eligible_future_originals=progress.get("eligible_future_fixtures"),
                       eligible_nba_future_originals=progress.get("eligible_nba_fixtures"),
                       admission_position=progress.get("admission_position"),
                       admission_completed=progress.get("admission_done"),
                       admission_skipped_after_cutoff=progress.get("admission_skipped_after_cutoff"),
                       admission_total=progress.get("admission_total"),
                       latest_status=report.get("status","NO_ADAPTIVE_RESEARCH_REPORT_OBSERVED"),
                       last_failure_code=report.get("reason"),
                       last_failure_phase=report.get("failed_phase"),
                       last_error_type=report.get("error_type"),
                       last_check_utc=last_check,
                       competition_groups=teams)),
        scoring=dict(main_model_uses_verified_player_minutes=False,
                     main_model_uses_player_shadow_coefficients=False,
                     main_model_automatically_selects_adaptive_model=False,
                     match_specific_coach_effect_verified=False,
                     numeric_player_boost_invented=False),
        status="RESEARCH_ACTIVATION_OBSERVED" if (
            worker is not None and bool(getattr(worker,"sequence",0))) else
            "RESEARCH_WORKER_INSTALLED_NOT_YET_OBSERVED" if worker is not None else
            "NO_RESEARCH_WORKER_INSTALLED",
        source_missing_is_not_healthy_roster=True,
        does_not_generate_a_new_prediction=True,
        original_forecasts_changed=False,production_changed=False)
