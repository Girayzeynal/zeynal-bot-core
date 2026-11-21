"""Synthetic invariants for negative-only P95 sensitivity; not live accuracy tests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from core.team_identity import digest
from hybrid_engine.negative_tail_sensitivity import analyze, analyze_file


def make_doc():
    def case(fid, forecast, actual, band=None):
        result=dict(fixture_id=fid,snapshot_sha256=fid*64,league="NBA",
                    season="2026/2027",model_version="MODEL",
                    model_digest="fixed",prediction=[forecast/2,forecast/2],
                    actual=[actual/2,actual/2],label_available_utc=10000)
        result["intervals"]=band
        return result
    band=dict(status="RAW_MODEL_QUANTILES_NOT_CALIBRATED",
              scope="REGULATION_ONLY",scenarios=10000,
              markets=dict(TOTAL=dict(p50=100,p90=112,p95=120)))
    forecasts=[
        case("a",100,126,copy.deepcopy(band)),
        case("b",100,121,copy.deepcopy(band)),
        # Deliberately malformed positive intervals must never be inspected.
        case("c",120,100,dict(status="POSITIVE_PROTECTED")),
    ]
    cases=[dict(fixture_id=r["fixture_id"],snapshot_sha256=r["snapshot_sha256"],
                signed_total_error=sum(r["prediction"])-sum(r["actual"]),
                prediction_total=sum(r["prediction"]),regulation_total=sum(r["actual"]),
                provider_fixture_ids=[r["fixture_id"]],
                home="Home",away="Away") for r in forecasts]
    payload=dict(format="PHASE92_READ_ONLY_QUALITY_REPORT_V1",
                 archive_audit=dict(performance_status="READ_ONLY_NATIVE_VERIFIED",
                                    performance=dict(status="VERIFIED_LIVE_REPORT",
                                                     forecasts=forecasts)),
                 error_review=dict(format="FROZEN_FORECAST_ERROR_REVIEW_V1",
                                   groups=[dict(cohort=dict(league="NBA",
                                        season="2026/2027",model_version="MODEL",
                                        model_digest="fixed"),n=3,cases=cases)]))
    return dict(payload=payload,sha256=digest(payload))


class NegativeTailSensitivityTests(unittest.TestCase):
    def test_positive_records_never_interpreted_or_changed(self):
        data=make_doc()
        saved=json.dumps(data,sort_keys=True)
        out=analyze(data)
        self.assertEqual(json.dumps(data,sort_keys=True),saved)
        group=out["cohort_results"][0]
        self.assertEqual((group["negative_count"],group["protected_positive_count"],
                          group["missing_negative_interval_count"]),(2,1,0))
        self.assertEqual(group["original_p95_exceedances"],2)
        self.assertEqual([s["number_above_boundary"]
                          for s in group["sensitivity_summary"]],[2,1,1])
        self.assertEqual(len(group["original_p95_exceedance_cases"]),2)
        self.assertFalse(out["original_forecasts_modified"])
        self.assertFalse(out["positive_originals_modified"])
        self.assertTrue(out["not_a_new_simulation"])
        self.assertTrue(out["not_a_model_calibration"])

    def test_missing_negative_band_explicit_not_hidden(self):
        data=make_doc()
        data["payload"]["archive_audit"]["performance"]["forecasts"][0]["intervals"]=None
        data["sha256"]=digest(data["payload"])
        group=analyze(data)["cohort_results"][0]
        self.assertEqual(group["negative_count"],2)
        self.assertEqual(group["missing_negative_interval_count"],1)
        self.assertEqual(group["original_p95_exceedances"],1)

    def test_score_mismatch_and_quantile_inversion_rejected(self):
        data=make_doc()
        data["payload"]["error_review"]["groups"][0]["cases"][0]["signed_total_error"]=-1
        data["sha256"]=digest(data["payload"])
        with self.assertRaisesRegex(ValueError,"SIGN_CONFLICT"):
            analyze(data)
        data=make_doc()
        data["payload"]["archive_audit"]["performance"]["forecasts"][0]["intervals"]["markets"]["TOTAL"]["p95"]=110
        data["sha256"]=digest(data["payload"])
        with self.assertRaisesRegex(ValueError,"QUANTILE_ORDER"):
            analyze(data)

    def test_report_hash_and_file_read_only(self):
        data=make_doc()
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/"quality-fixture.json"
            before=json.dumps(data,sort_keys=True).encode()
            f.write_bytes(before)
            out=analyze_file(f)
            self.assertTrue(out["report_bytes_unchanged"])
            self.assertEqual(before,f.read_bytes())
            data["payload"]["archive_audit"]["performance"]["forecasts"][0]["prediction"]=[0,0]
            f.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,"SOURCE_PIN_FAILED"):
                analyze_file(f)


if __name__=="__main__":
    unittest.main()
