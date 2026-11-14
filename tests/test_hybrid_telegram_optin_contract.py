"""Static safety contracts for the opt-in research route.

These checks do not replace integration tests with a prepared Bayesian artifact.
"""
import ast
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class HybridTelegramOptInContracts(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'main.py').read_text()
        cls.tree = ast.parse(cls.source)

    def test_default_off_and_explicit_enable(self):
        self.assertIn("os.getenv('ZEYNAL_HYBRID_NBA_RESEARCH','0')=='1'", self.source)
        self.assertIn("app.bot_data['verified_analysis_service']=production_service()", self.source)

    def test_research_requires_pinned_prepared_model(self):
        self.assertIn("os.environ['ZEYNAL_HYBRID_PREPARED_PATH']", self.source)
        self.assertIn("os.environ['ZEYNAL_HYBRID_PREPARED_SHA256']", self.source)
        self.assertIn('PreparedBayes(prepared_path,trusted_sha256=prepared_sha)', self.source)

    def test_no_production_volume_research_directory(self):
        self.assertIn("os.path.realpath(research_dir)=='/data'", self.source)
        self.assertIn("os.path.realpath(research_dir).startswith('/data/')", self.source)

    def test_no_silent_faz13_fallback_on_hybrid_failure(self):
        self.assertIn("await hybrid_service.analyze(league,date_str,home,away)", self.source)
        self.assertIn("Hibrit araştırma analizi kullanılamıyor; FAZ13 sonucu üretilmedi.", self.source)
        self.assertIn("await update.message.reply_text(part,parse_mode='HTML'", self.source)
        self.assertNotIn("await reply_analysis(update,context,report,hybrid_service)", self.source)

    def test_telegram_displays_uncalibrated_research_warning(self):
        self.assertIn('ARAŞTIRMA MODU — ÜRETİM TAHMİNİ DEĞİL — KALİBRE EDİLMEDİ', self.source)
        self.assertIn("await update.message.reply_text(part,parse_mode='HTML'", self.source)
        self.assertNotIn('await reply_analysis(update,context,report,hybrid_service)', self.source)

    def test_hybrid_research_engine_not_promoted(self):
        engine = (ROOT / 'hybrid_engine/live_nba.py').read_text()
        self.assertIn('production=False', engine)
        self.assertIn("calibration_status='NOT_CALIBRATED'", engine)
