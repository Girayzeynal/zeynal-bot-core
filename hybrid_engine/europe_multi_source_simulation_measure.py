"""Offline synthetic-only QMC sensitivity measurement for all three leagues.

Uses existing trained-player HierarchicalStrength+10k RQMC paths, NOT a
text-news-to-points formula. Fixture and injury sources are synthetic.
The output CANNOT establish real-world accuracy or calibrate a live model.
"""
import argparse
import json
import math
from pathlib import Path

from core.team_identity import digest
from hybrid_engine.official_club_rotation_scenarios import compare_verified_rotation


def benchmark():
    from tests.test_official_club_rotation_scenarios import scenario,_pins
    rows=[]
    for league in ("NBA","EUROLEAGUE","EUROCUP"):
        model,cut,feature,when=scenario(league)
        report=compare_verified_rotation(
            model,cut,feature,
            trusted_feature_sha256=digest(feature),
            trusted_source_pins=_pins(feature),
            prediction_utc=when)
        actual=sum(cut.target["final_scores"])
        before=report["baseline"]["total"]
        after=report["adjusted"]["total"]
        if not report["scenarios"]==10000:
            raise ValueError("QMC_10000_REQUIRED")
        if not (math.isfinite(before) and math.isfinite(after) and math.isfinite(actual)):
            raise ValueError("FINITE_MEASUREMENTS_REQUIRED")
        rows.append(dict(league=league,
            synthetic_fixture_id=cut.target["fixture_id"],
            actual_synthetic_final_total=actual,
            baseline_projected_total=round(before,4),
            adjusted_projected_total=round(after,4),
            delta_projected_total=round(report["deltas"]["total"],4),
            baseline_abs_total_error=round(abs(before-actual),4),
            adjusted_abs_total_error=round(abs(after-actual),4),
            abs_error_improvement=round(abs(before-actual)-abs(after-actual),4),
            qmc_paths=report["scenarios"],method=report["method"],
            verified_real_injury_reports=0))
    return dict(format="ZEYNAL_SYNTHETIC_PLAYER_ROTATION_QMC_MEASUREMENT_V1",
        status="SYNTHETIC_ONLY_NO_REAL_WORLD_ACCURACY_CLAIM",
        leagues=[r["league"] for r in rows],
        results=rows,real_match_count=0,real_source_player_status_verified=False,
        real_injury_adjusted_mae=None,real_injury_adjusted_rmse=None,
        calibration_status="NOT_CALIBRATED",production_changed=False,
        historical_forecasts_changed=False,source_api_calls=0)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    result=benchmark()
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
