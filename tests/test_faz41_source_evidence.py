import copy
import unittest

from faz41_source_evidence import seal_source_claim, validate_source_claim, compare_claims


def claim(**updates):
    fields = dict(league="EUROLEAGUE", fixture_id="E2026_1", provider="official",
                  source_url="https://example.org/game/1", data_type="OFFICIAL_STAT",
                  evidence_level="OFFICIAL", usage_status="PERMITTED",
                  published_at_utc=10, observed_at_utc=11, ingested_at_utc=12,
                  claim_key="home_score", claim_value=82)
    fields.update(updates)
    return seal_source_claim(**fields)


class SourceEvidenceTests(unittest.TestCase):
    def validate(self, sealed=None, **updates):
        params = dict(league="EUROLEAGUE", fixture_id="E2026_1", prediction_utc=20)
        params.update(updates)
        return validate_source_claim(claim() if sealed is None else sealed, **params)

    def test_valid_official_evidence(self):
        self.assertEqual(self.validate()["claim_value"], 82)

    def test_future_ingestion_rejected(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.validate(claim(ingested_at_utc=21))

    def test_fixture_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "fixture mismatch"):
            self.validate(fixture_id="E2026_2")

    def test_league_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "fixture mismatch"):
            self.validate(league="NBA")

    def test_tampering_rejected(self):
        item = copy.deepcopy(claim())
        item["payload"]["claim_value"] = 99
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.validate(item)

    def test_unlicensed_claim_rejected(self):
        with self.assertRaisesRegex(ValueError, "permission"):
            self.validate(claim(usage_status="UNKNOWN"))

    def test_non_https_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            claim(source_url="http://example.org")

    def test_time_order_rejected(self):
        with self.assertRaisesRegex(ValueError, "Non-monotonic"):
            claim(published_at_utc=13)

    def test_opinion_cannot_masquerade_as_official(self):
        with self.assertRaisesRegex(ValueError, "commentary"):
            claim(data_type="ANALYST_OPINION", evidence_level="OFFICIAL")

    def test_provider_conflict_reported(self):
        rows = compare_claims([claim(), claim(provider="other", claim_value=83)],
                              league="EUROLEAGUE", fixture_id="E2026_1",
                              prediction_utc=20)
        self.assertEqual(rows[0]["status"], "CONFLICT")

    def test_same_provider_is_not_independent_confirmation(self):
        rows = compare_claims([claim(), claim()],
                              league="EUROLEAGUE", fixture_id="E2026_1",
                              prediction_utc=20)
        self.assertEqual(rows[0]["status"], "SINGLE_SOURCE")

    def test_two_providers_agree(self):
        rows = compare_claims([claim(), claim(provider="second")],
                              league="EUROLEAGUE", fixture_id="E2026_1",
                              prediction_utc=20)
        self.assertEqual(rows[0]["status"], "MULTI_SOURCE_AGREEMENT")


if __name__ == "__main__":
    unittest.main()
