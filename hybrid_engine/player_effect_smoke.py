"""Offline executable synthetic smoke test of the REAL player Bayesian modules.

THIS IS NOT A LIVE GAME FORECAST. It trains on manufactured basketball games
inside a TemporaryDirectory and compares the same fitted model before/after
a manufactured two-source Out status. Never fits inside Telegram or writes
to production/original archives. Target times are synthetically backdated.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.boxes import publish_json


VERSION="NBA_SYNTHETIC_PLAYER_EFFECT_SMOKE_V1"


def execute():
    # Real production implementations; tests only supply MANUFACTURED inputs.
    from tests.test_player_shadow import PlayerShadowTests, case_for
    from hybrid_engine.player_minutes import projection
    from hybrid_engine.player_shadow import PreparedPlayerPair
    cls=PlayerShadowTests
    cls.setUpClass()
    try:
        with patch("time.time",return_value=cls.now):
            model=PreparedPlayerPair(cls.artifact,trusted_sha256=cls.artifact["sha256"])
            cut=cls().target()
            data=case_for(cls.cohort[70][0])
            no_injury=projection(**data)
            injured=deepcopy(data)
            home=injured["context"]["home"]["provider_id"]
            missing=injured["rosters"]["home"]["players"][0]
            injured["review"]["records"]=[
                dict(team_id=home,player_id=missing,status="Out",
                     source=src,status_updated_at_utc=cls.now-10)
                for src in ("ESPN","NBA_OFFICIAL_PDF")]
            out_projection=projection(**injured)
            team_control=model.predict(cut,no_injury)
            out_forecast=model.predict(cut,out_projection)
        base_m={r["player_id"]:r["expected_minutes"]
                for r in no_injury["payload"]["home"]}
        out_m={r["player_id"]:r["expected_minutes"]
               for r in out_projection["payload"]["home"]}
        if abs(sum(base_m.values())-240)>1e-6 or abs(sum(out_m.values())-240)>1e-6:
            raise ValueError("SMOKE_HOME_MINUTES_CONSERVATION_FAILED")
        if out_m[missing]!=0 or not base_m[missing]>0:
            raise ValueError("SMOKE_MISSING_PLAYER_NOT_EXCLUDED")
        if not any(out_m[p]>base_m[p] for p in out_m if p!=missing):
            raise ValueError("SMOKE_REPLACEMENTS_NOT_ALLOCATED")
        for v in (team_control,out_forecast):
            for f in v.values():
                if not math.isfinite(float(f.scores.sum())) or abs(
                        float(f.quarter_means.sum()-f.scores.sum()))>1e-6:
                    raise ValueError("SMOKE_SCORE_QMC_OR_QUARTERS_INCOHERENT")
        control_before=team_control["TEAM_BAYES"].scores.tolist()
        control_after=out_forecast["TEAM_BAYES"].scores.tolist()
        if any(abs(a-b)>1e-8 for a,b in zip(control_before,control_after)):
            raise ValueError("SMOKE_TEAM_CONTROL_CHANGED_WITH_ONLY_PLAYER_STATUS")
        scores_before=team_control["PLAYER_BAYES"].scores.tolist()
        scores_after=out_forecast["PLAYER_BAYES"].scores.tolist()
        delta=[float(b-a) for a,b in zip(scores_before,scores_after)]
        replacement=sorted(
            (dict(player_id=p,before_minutes=round(base_m[p],3),
                  after_minutes=round(out_m[p],3),
                  minute_change=round(out_m[p]-base_m[p],3))
             for p in base_m if p!=missing),
            key=lambda r:(-r["minute_change"],r["player_id"]))
        response=dict(
            format=VERSION,status="SYNTHETIC_PIPELINE_PASSED",
            input_classification="FULLY_MANUFACTURED_TEST_GAMES_AND_INJURY",
            evidence_is_real_game=False,player_effect_is_live=False,
            production_enabled=False,original_forecasts_changed=False,
            original_archive_accessed=False,network_requests_made=0,
            training_in_telegram=False,
            synthetic_fit_games=cls.audit["eligible_games"],
            synthetic_training_audit=cls.audit["status"],
            fitted_player_coefficients=len(model.candidate.players),
            simulated_injury=dict(side="home",player_id=missing,
                fake_ESPN_status="Out",fake_NBA_OFFICIAL_PDF_status="Out"),
            home_rotation_minutes_before=round(sum(base_m.values()),4),
            home_rotation_minutes_after=round(sum(out_m.values()),4),
            missing_player_minutes_before=round(base_m[missing],3),
            missing_player_minutes_after=round(out_m[missing],3),
            replacement_minutes_top4=replacement[:4],
            TEAM_BAYES_CONTROL=dict(home=round(control_before[0],3),
                away=round(control_before[1],3)),
            PLAYER_BAYES_BEFORE=dict(home=round(scores_before[0],3),
                away=round(scores_before[1],3)),
            PLAYER_BAYES_AFTER=dict(home=round(scores_after[0],3),
                away=round(scores_after[1],3)),
            PLAYER_BAYES_DELTA=dict(home=round(delta[0],3),
                away=round(delta[1],3)),
            score_sensitivity_observed=any(abs(d)>1e-7 for d in delta),
            synthetic_target_id=cut.target["fixture_id"],
            QMC_scenarios=10000,
            model_calibration_status="NOT_CALIBRATED",
            live_player_minutes_status="NOT_VERIFIED_BY_THIS_SMOKE_TEST",
            live_player_shadow_status="NOT_VERIFIED_BY_THIS_SMOKE_TEST")
        if not response["score_sensitivity_observed"]:
            response["status"]="SYNTHETIC_MINUTES_PASSED_SCORE_SENSITIVITY_NOT_IDENTIFIED"
        return response
    finally:
        cls.doClassCleanups()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    report=execute()
    output=Path(args.output).expanduser().absolute()
    # Explicit synthetic result store, not an original forecast or native
    # athlete evidence directory. Pre-existing files are not modified.
    if output.name!="player-effect-smoke.json" or output.is_symlink():
        raise ValueError("SYNTHETIC_REPORT_OUTPUT_ONLY")
    output.parent.mkdir(parents=True,exist_ok=True)
    wrapped=dict(payload=report,sha256=digest(report))
    publish_json(output,wrapped)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0 if report["status"]=="SYNTHETIC_PIPELINE_PASSED" else 3


if __name__=="__main__":
    raise SystemExit(main())
