"""Actual PTB six-button route, with an OFFLINE Telegram Bot API double.

No production token, real Telegram delivery or real provider HTTP is claimed.
"""
from unittest.mock import patch
from hybrid_engine.europe_injury_public_sources import PublicEuroInjuryNewsHub
from tests.test_europe_premium_ui import EuropeanButtonTests
from tests.test_europe_public_sources import fake_http


class MultiSourceTelegramTests(EuropeanButtonTests):
    async def test_real_ptb_roster_callback_renders_source_status_without_resimulation(self):
        report=await self.open("EUROLEAGUE")
        token=report["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[1]
        entry=self.app.bot_data["premium_reports"][token]
        self.assertIsNotNone(entry.get("europe_context"))
        before=self.files()
        reviewer=self.app.bot_data["europe_data_review"]
        hub=PublicEuroInjuryNewsHub(clock=lambda:self.clock,requester=fake_http,enabled=True)
        reviewer.public_news_hub=hub
        reviewer.native_roster_getter=lambda url:dict(status="SOURCE_UNREACHABLE")
        self.app.bot_data["europe_public_injury_news_hub"]=hub
        with patch("hybrid_engine.models.HierarchicalStrength.predict",
                   side_effect=AssertionError("NO_NEW_FORECAST_ON_ROSTER_BUTTON")):
            await self.click(token,"roster")
        entry=self.app.bot_data["premium_reports"][token]
        body=entry["sections"]["roster"]
        self.assertIn("BASKETBALL_SPHERE",body)
        self.assertIn("EUROHOOPS",body)
        self.assertIn("BASKETLOGY",body)
        self.assertIn("SOURCE_INDEX_OBSERVED_CANDIDATES_ONLY",body)
        self.assertIn("Maça bağlı doğrulanmış oyuncu durum kaydı elde edilemedi",body)
        self.assertTrue(self.api.edits)
        self.assertEqual(before,self.files())
        self.assertFalse(hub.public_status()["model_input"])
        self.assertEqual(len(hub.public_status()["last_statuses"]),len(hub.review(entry["europe_context"])["sources"]))
