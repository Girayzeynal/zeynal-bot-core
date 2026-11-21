"""Synthetic regression: protect positive original records in negative-only audit.

No synthetic score here is ever treated as measured live accuracy.
"""
import json
from pathlib import Path
import tempfile
import unittest

from core.team_identity import digest
from hybrid_engine.negative_error_audit import analyze, report_file


def case(fid, predicted, actual):
    return dict(fixture_id=fid, snapshot_sha256=(fid * 64)[:64],
        prediction_total=predicted, regulation_total=actual,
        signed_total_error=predicted-actual,
        provider_fixture_ids=[fid], home="Home", away="Away",
        input_profile_status="FROZEN_INPUTS_VERIFIED",
        input_profile=dict(fit_age_seconds=86400, training_games=110,
                           history=dict(home=dict(new_games_since_fit=3),
                                        away=dict(new_games_since_fit=2))),
        period_total_errors=[-1, -2, -3, -4] if predicted<actual else None,
        findings=["MEASURED_PACE_NOT_A_MODEL_INPUT"])


def document():
    cases=[case("a",100,110),case("b",120,100),case("c",80,80)]
    p=dict(format="PHASE92_READ_ONLY_QUALITY_REPORT_V1",
           error_review=dict(format="FROZEN_FORECAST_ERROR_REVIEW_V1",
           groups=[dict(cohort=dict(league="NBA",season="2026/2027",
                                   model_version="TEST",model_digest="fitted"),
                        n=3,day_clusters=2,cases=cases,
                        matched_input_baseline=dict(pairs=[dict(
                            fixture_id="a",snapshot_sha256="a"*64,
                            frozen_model_error=-10,
                            retrospective_baseline_error=-8)]))]))
    return dict(payload=p,sha256=digest(p))


class NegativeErrorAuditTests(unittest.TestCase):
    def test_negative_only_protects_positive_and_does_not_mutate_input(self):
        data=document()
        original=json.dumps(data,sort_keys=True)
        result=analyze(data)
        self.assertEqual(json.dumps(data,sort_keys=True),original)
        group=result["cohorts"][0]
        self.assertEqual((group["negative_count"],group["positive_untouched_count"],
                          group["zero_count"]), (1,1,1))
        self.assertEqual(group["most_negative_cases"][0]["fixture_id"],"a")
        self.assertEqual(group["negative_mae"],10)
        self.assertEqual(group["negative_quarter_mae"],[1,2,3,4])
        self.assertEqual(group["negative_matched_reference"]["pairs"],1)
        self.assertEqual(group["negative_matched_reference"]["retrospective_reference_mae"],8)
        self.assertEqual(group["most_negative_cases"][0]["new_games_since_fit_by_side"],
                         dict(home=3,away=2))
        self.assertFalse(group["positive_cases_modified"])
        self.assertFalse(result["original_forecasts_changed"])

    def test_readonly_file_and_wrong_hash_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"quality-test.json"
            raw=json.dumps(document(),sort_keys=True).encode()
            path.write_bytes(raw)
            self.assertTrue(report_file(path)["report_bytes_unchanged"])
            self.assertEqual(path.read_bytes(),raw)
            wrong=document()
            wrong["payload"]["error_review"]["groups"][0]["cases"][0]["signed_total_error"]=-99
            path.write_text(json.dumps(wrong))
            with self.assertRaisesRegex(ValueError,"PIN_MISMATCH"):
                report_file(path)

    def test_sign_discrepancy_fails_closed(self):
        wrong=document()
        c=wrong["payload"]["error_review"]["groups"][0]["cases"][0]
        c["signed_total_error"]=10
        wrong["sha256"]=digest(wrong["payload"])
        with self.assertRaisesRegex(ValueError,"SIGN_IDENTITY_CONFLICT"):
            analyze(wrong)

    def test_no_negative_case_is_a_supported_result(self):
        d=document()
        group=d["payload"]["error_review"]["groups"][0]
        group["cases"]=[case("b",120,100)]
        group["n"]=1
        group["matched_input_baseline"]["pairs"]=[]
        d["sha256"]=digest(d["payload"])
        out=analyze(d)["cohorts"][0]
        self.assertEqual(out["negative_count"],0)
        self.assertIsNone(out["negative_mae"])
        self.assertEqual(out["positive_untouched_count"],1)


if __name__=="__main__":
    unittest.main()
