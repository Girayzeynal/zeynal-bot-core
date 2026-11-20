"""Real PTB six-button handler, OFFLINE synthetic source and API double.

The archived fixture used to exercise the UI is already over; its genuine
source-review correctly abstains. A separate synthetic pre-tipoff reviewer
payload is injected ONLY for delivery/layout testing, never source admission.
"""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from hybrid_engine.europe_injury_public_sources import PublicEuroInjuryNewsHub
from tests.test_europe_premium_ui import EuropeanButtonTests
from tests.test_europe_public_sources import fake_http
from tests.test_europe_roster_evidence_wiring import CTX,TIME


class MultiSourceTelegramTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await EuropeanButtonTests.asyncSetUp(self)
    open=EuropeanButtonTests.open
    click=EuropeanButtonTests.click
    files=EuropeanButtonTests.files

    async def test_past_fixture_refuses_new_source_observation_on_real_ptb_route(self):
        report=await self.open("EUROLEAGUE")
        token=report["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[1]
        reviewer=self.app.bot_data["europe_data_review"]
        hub=PublicEuroInjuryNewsHub(clock=lambda:self.clock,requester=fake_http,enabled=True)
        reviewer.public_news_hub=hub
        before=self.files()
        with patch("hybrid_engine.models.HierarchicalStrength.predict",
                   side_effect=AssertionError("NO_BUTTON_RESIMULATION")):
            await self.click(token,"roster")
        entry=self.app.bot_data["premium_reports"][token]
        self.assertIn("Maç başladı",entry["sections"]["roster"])
        self.assertEqual(hub.public_status()["last_statuses"],[])
        self.assertEqual(before,self.files())

    async def test_actual_ptb_callback_renders_separately_tested_synthetic_source_receipts(self):
        report=await self.open("EUROLEAGUE")
        token=report["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[1]
        entry=self.app.bot_data["premium_reports"][token]
        before=self.files()
        reviewer=self.app.bot_data["europe_data_review"]
        hub=PublicEuroInjuryNewsHub(clock=lambda:TIME+60,requester=fake_http,enabled=True)
        reviewer.public_news_hub=hub
        reviewer.native_roster_getter=lambda url:dict(status="SOURCE_UNREACHABLE")
        self.app.bot_data["europe_public_injury_news_hub"]=hub
        # Exercise the REAL public-source reviewer on a separate synthetic
        # future fixture, then ONLY inject its text into the PTB handler.
        # Do not forge the archived fixture's original first-prediction clock.
        body,details=reviewer.roster(CTX)
        self.assertEqual(details["verified_player_records"],[])
        self.assertFalse(details["public_news_model_input"])
        recorded=dict(original_forecast_sha256=entry["europe_context"]["original_forecast_sha256"],
                      section="roster",observed_at_utc=self.clock,
                      valid_until_utc=self.clock+120,html=body,details=details,
                      status="SYNTHETIC_CALLBACK_RENDER_ONLY")
        with patch.object(reviewer,"review",return_value=recorded):
            with patch("hybrid_engine.models.HierarchicalStrength.predict",
                       side_effect=AssertionError("NO_BUTTON_RESIMULATION")):
                await self.click(token,"roster")
        value=self.app.bot_data["premium_reports"][token]["sections"]["roster"]
        for name in ("BASKETBALL_SPHERE","EUROHOOPS","BASKETLOGY",
                     "SOURCE_INDEX_OBSERVED_CANDIDATES_ONLY"):
            self.assertIn(name,value)
        self.assertTrue(self.api.edits)
        self.assertEqual(before,self.files())
        self.assertFalse(hub.public_status()["model_input"])
