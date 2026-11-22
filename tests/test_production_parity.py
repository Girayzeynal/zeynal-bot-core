"""Fail-closed production command parity tests; no Bot API, disk or provider writes."""
import asyncio
import unittest
from types import SimpleNamespace

from hybrid_engine import production_parity as parity


class Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, value, **kwargs):
        self.sent.append(value)


def fixture(reader=None, args=None):
    message = Message()
    update = SimpleNamespace(effective_message=message)
    context = SimpleNamespace(args=args or [],
                              application=SimpleNamespace(bot_data={"ledger_reports": reader}))
    return update, context, message


class Reader:
    def __init__(self, status="ARCHIVE_UNAVAILABLE"):
        self.status = status
        self.calls = []

    def read(self, league, fixture=None):
        self.calls.append((league, fixture))
        return {"status": self.status, "forecasts": [], "groups": []}


class ProductionParityTests(unittest.TestCase):
    def test_all_result_fail_closed_for_missing_archive(self):
        reader = Reader()
        update, context, msg = fixture(reader, ["all"])
        asyncio.run(parity.results_command(update, context))
        self.assertIn("doğrulanmış", msg.sent[0].lower())
        self.assertEqual(reader.calls, [("NBA", None)])
        self.assertNotIn("FINAL 0", msg.sent[0])

    def test_predictions_missing_never_claims_archive(self):
        update, context, msg = fixture(Reader(), ["EUROCUP", "1"])
        asyncio.run(parity.predictions_command(update, context))
        self.assertIn("okunamadı", msg.sent[0])
        self.assertNotIn("TAHMİN", msg.sent[0])

    def test_accuracy_all_does_not_fabricate_percent(self):
        update, context, msg = fixture(Reader(), ["all"])
        asyncio.run(parity.accuracy_command(update, context))
        self.assertIn("uydurulmadı", msg.sent[0])
        self.assertNotIn("100%", msg.sent[0])

    def test_sources_does_not_claim_player_status(self):
        update, context, msg = fixture()
        asyncio.run(parity.sources_command(update, context))
        self.assertIn("82", "".join(msg.sent))
        self.assertIn("DEĞİLDİR", "".join(msg.sent))

    def test_models_usage_check_prevents_reader(self):
        update, context, msg = fixture(Reader(), ["NBA"])
        asyncio.run(parity.models_command(update, context))
        self.assertIn("Kullanım:", msg.sent[0])

    def test_empty_verified_production_archive_has_production_label(self):
        reader = Reader(status="VERIFIED_LIVE_REPORT")
        update, context, msg = fixture(reader, ["all"])
        asyncio.run(parity.results_command(update, context))
        self.assertIn("Doğrulanmış üretim arşivi", "".join(msg.sent))
        self.assertNotIn("İzole test arşivi", "".join(msg.sent))
        self.assertEqual([league for league, _ in reader.calls], list(parity.LEAGUES))

    def test_isolated_test_bot_has_no_duplicate_production_handler(self):
        from unittest.mock import patch
        class App:
            def __init__(self): self.handlers = []
            def add_handler(self, handler): self.handlers.append(handler)
        with patch.dict("os.environ", {
            "ZEYNAL_TEST_BOT_TOKEN": "dedicated-test-token",
            "TELEGRAM_BOT_TOKEN": "dedicated-test-token"}):
            app=App()
            parity.install(app)
        self.assertEqual(app.handlers, [])

    def test_live_integration_command_is_readonly_and_admits_missing_data(self):
        update, context, msg = fixture(Reader(), ["integrations"])
        asyncio.run(parity.runtime_command(update, context))
        import json
        report=json.loads("".join(msg.sent))
        self.assertEqual(report["format"],"THREE_LEAGUE_REAL_PROCESS_INTEGRATION_DIAGNOSTIC_V1")
        self.assertEqual(report["league_counts"],{"NBA":30,"EUROLEAGUE":20,"EUROCUP":32})
        self.assertEqual(report["observed_official_news_pilots"],6)
        self.assertEqual(report["unverified_official_news_sites"],76)
        self.assertFalse(report["independently_verified_player_coach_effects_in_numeric_forecast"])
        self.assertFalse(report["genuine_telegram_response_delivery_verified"])
        self.assertTrue(report["no_new_forecast_created"])
        self.assertFalse(report["original_archive_reader_configured"] is False)

    def test_test_integrations_never_masquerades_as_runtime_analysis(self):
        update, context, msg = fixture(args=["integrations"])
        asyncio.run(parity.runtime_command(update, context))
        import json
        report=json.loads("".join(msg.sent))
        self.assertFalse(report["original_archive_reader_configured"])
        self.assertEqual(report["analysis_service"],"SERVICE_LOADED_ANALYSIS_NOT_OBSERVED")
        self.assertFalse(report["active_confirmed_transfer_news_pipeline"])

    def test_news_command_reads_sources_without_issued_fixture_or_model(self):
        from unittest.mock import patch
        update,ctx,msg=fixture(args=[
            "EUROLEAGUE","Zalgiris","Kaunas","vs",
            "Panathinaikos","AKTOR","Athens"])
        observation=dict(status="CURRENT_TEAM_NEWS_NOT_FIXTURE_VERIFIED",
            official_club_matches=["euroleague_zalgiris",
                                  "euroleague_panathinaikos_athens"],
            sources=[dict(source="EUROHOOPS",status="SOURCE_INDEX_OBSERVED_CANDIDATES_ONLY")],
            player_status_verified=False,model_input=False)
        with patch("hybrid_engine.europe_injury_public_sources.review_current_team_news",
                   return_value=observation) as news:
            asyncio.run(parity.injurynews_command(update,ctx))
        news.assert_called_once()
        self.assertIn("2 / 2","".join(msg.sent))
        self.assertIn("MAÇ", "".join(msg.sent).upper())
        self.assertFalse(observation["model_input"])
        self.assertNotIn("final_scores",ctx.application.bot_data)

    def test_news_invalid_command_does_not_call_provider(self):
        update,ctx,msg=fixture(args=["EUROLEAGUE","Athens"])
        asyncio.run(parity.injurynews_command(update,ctx))
        self.assertIn("Kullanım:",msg.sent[0])

    def test_registration_is_side_effect_free(self):
        class App:
            def __init__(self): self.handlers = []
            def add_handler(self, handler): self.handlers.append(handler)
        app=App()
        parity.install(app)
        commands={cmd for h in app.handlers for cmd in h.commands}
        self.assertEqual(commands, {"features","models","predictions","results","sources","sourceplayers","injurynews","test"})


if __name__ == "__main__":
    unittest.main()
