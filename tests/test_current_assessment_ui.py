"""Two-clock user display: original and published current score remain distinct."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch

from hybrid_engine.current_assessment_ui import two_clock_text,install_dual_clock_display

NOW=1795339800


class DualClockTextTests(unittest.TestCase):
    def setUp(self):
        self.ctx=dict(league="NBA",fixture_id="x",fixture_start_utc=NOW+10800,
            prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        self.candidate=dict(candidate=dict(home=108.,away=110.,total=218.),
            prediction_generated_at_utc=NOW-60,
            source_available_max_utc=NOW-70,
            parameter_fit_cutoff_utc=NOW-3600)
    def test_new_research_score_shows_both_clocks_and_delta_without_fake_player_integration(self):
        a=SimpleNamespace(latest=Mock(return_value=self.candidate))
        text=two_clock_text(self.ctx,a,now=NOW)
        self.assertIn("GÜNCEL AYRI ARAŞTIRMA SKORU",text)
        self.assertIn("Toplam 218.00",text)
        self.assertIn("İlk skor: 105.00 – 115.00",text)
        self.assertIn("-2.00 sayı",text)
        self.assertIn("DAHİL EDİLMEDİ",text)
        self.assertIn("NOT_CALIBRATED",text)
        self.assertTrue(self.candidate["candidate"]["total"]==218.)
    def test_missing_or_stale_candidate_does_not_claim_an_updated_score(self):
        a=SimpleNamespace(latest=Mock(return_value=None))
        text=two_clock_text(self.ctx,a,now=NOW)
        self.assertIn("HENÜZ YAYIMLANMADI",text)
        self.assertIn("İlk skor: 105.00",text)
        a.latest.return_value=self.candidate
        self.candidate["prediction_generated_at_utc"]=NOW-4000
        aged=two_clock_text(self.ctx,a,now=NOW)
        self.assertIn("ARŞİV",aged)
        self.assertNotIn("GÜNCEL AYRI ARAŞTIRMA SKORU",aged)


class DualClockDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_does_not_modify_source_or_fit_in_telegram_handler(self):
        ctx=dict(league="NBA",fixture_id="x",fixture_start_utc=NOW+10800,
            prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        response=dict(status="ANALYSIS_OK",snapshot=ctx,html="FIRST",html_parts=["FIRST"],new_record=False)
        base=SimpleNamespace(analyze=AsyncMock(return_value=response),ledger=object())
        a=SimpleNamespace(latest=Mock(return_value=None))
        state=dict(verified_analysis_service=base)
        install_dual_clock_display(state,a)
        with patch("hybrid_engine.current_assessment_ui.time.time",return_value=NOW):
            out=await state["verified_analysis_service"].analyze("NBA","date","home","away")
        self.assertIn("HENÜZ YAYIMLANMADI",out["html"])
        self.assertIn("FIRST",out["html"])
        self.assertIs(response["snapshot"],out["snapshot"])
        self.assertEqual(response["html"],"FIRST")
        a.latest.assert_called_once_with(ctx)
    async def test_no_augmentation_of_non_analysis_results(self):
        response=dict(status="ABSTAIN",html="No verified fixture")
        base=SimpleNamespace(analyze=AsyncMock(return_value=response))
        a=SimpleNamespace(latest=Mock())
        state=dict(verified_analysis_service=base)
        install_dual_clock_display(state,a)
        out=await state["verified_analysis_service"].analyze("NBA","bad")
        self.assertIs(out,response)
        a.latest.assert_not_called()
