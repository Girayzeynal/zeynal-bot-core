"""Render-only Telegram button reports survive the isolated poller restart."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hybrid_engine.premium_report_cache import DiskBackedReports
from hybrid_engine.telegram_premium_ui import cache_report,page_view


class DiskBackedPremiumReportsTests(unittest.TestCase):
    TOKEN="a"*12

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cache=DiskBackedReports(self.root,42)

    def report(self):
        return dict(chat_id=42,summary="<b>GÜNCEL ADAY 224.93</b>",
            sections=dict(audit="<b>V1 SAĞLIK KARTI</b>\nV3 AYRI",
                period="<b>1Q</b> 28.06 - 28.92",
                ranges="<b>P25-P75</b> 213-237",
                market="<b>ÜST 222.5</b>",roster="<b>KADRO</b>"),
            section_pages=dict(audit=["<b>V1 SAĞLIK KARTI</b>\nV3 AYRI"],
                period=["<b>1Q</b> 28.06 - 28.92"],
                ranges=["<b>P25-P75</b> 213-237"],
                market=["<b>ÜST 222.5</b>"],roster=["<b>KADRO</b>"]),
            tipoff_utc=1795550000,quote_valid_until_utc=1795341000,
            current_assessment_panels=True,
            current_assessment_valid_until_utc=1795341600)

    def test_rendered_sections_recovered_only_as_archival(self):
        cache_report(self.cache,self.TOKEN,self.report())
        restarted=DiskBackedReports(self.root,42)
        record=restarted.get(self.TOKEN)
        self.assertIsNotNone(record)
        self.assertTrue(record["restored_archive_session"])
        self.assertEqual(record["sections"]["period"],"<b>1Q</b> 28.06 - 28.92")
        body,count=page_view(record,"audit",0,now=1795341100)
        self.assertEqual(count,1)
        self.assertIn("YENİDEN BAŞLATMADAN KORUNMUŞ RAPOR",body)
        self.assertIn("V1 SAĞLIK KARTI",body)
        self.assertIn("V3 AYRI",body)
        market,_=page_view(record,"market",0,now=1795341100)
        self.assertIn("ARŞİV PİYASA GÖZLEMİ",market)
        self.assertIn("ÜST 222.5",market)

    def test_final_rebound_sections_overwrite_first_forecast_disk_snapshot(self):
        first=self.report()
        cache_report(self.cache,self.TOKEN,first)
        first["sections"]["period"]="<b>GÜNCEL 1Q 56.98</b>"
        first["section_pages"]["period"]=["<b>GÜNCEL 1Q 56.98</b>"]
        cache_report(self.cache,self.TOKEN,first)
        recovered=DiskBackedReports(self.root,42).get(self.TOKEN)
        self.assertIn("GÜNCEL 1Q 56.98",recovered["sections"]["period"])
        self.assertNotIn("28.06 - 28.92",recovered["sections"]["period"])

    def test_explicit_deletion_revokes_saved_session_but_restart_recovers_intact_one(self):
        cache_report(self.cache,self.TOKEN,self.report())
        self.assertIsNotNone(DiskBackedReports(self.root,42).get(self.TOKEN))
        del self.cache[self.TOKEN]
        self.assertFalse((self.root/(self.TOKEN+".json")).exists())
        self.assertIsNone(DiskBackedReports(self.root,42).get(self.TOKEN))

    def test_cache_eviction_removes_saved_page_not_just_ram_entry(self):
        other="b"*12
        cache_report(self.cache,self.TOKEN,self.report(),max_count=1)
        cache_report(self.cache,other,self.report(),max_count=1)
        self.assertIsNone(DiskBackedReports(self.root,42).get(self.TOKEN))
        self.assertIsNotNone(DiskBackedReports(self.root,42).get(other))
        self.cache.clear()
        self.assertIsNone(DiskBackedReports(self.root,42).get(other))

    def test_different_authorized_chat_cannot_recover_rendered_session(self):
        cache_report(self.cache,self.TOKEN,self.report())
        self.assertIsNone(DiskBackedReports(self.root,43).get(self.TOKEN))
        with self.assertRaises(ValueError):
            self.cache["b"*12]=dict(self.report(),chat_id=43)

    def test_missing_token_and_tampered_json_fail_closed(self):
        self.assertIsNone(DiskBackedReports(self.root,42).get("f"*12))
        self.assertIsNone(self.cache.get("../outside"))
        cache_report(self.cache,self.TOKEN,self.report())
        (self.root/(self.TOKEN+".json")).write_text('{"chat_id": 42}',encoding="utf-8")
        self.assertIsNone(DiskBackedReports(self.root,42).get(self.TOKEN))

    def test_old_recovered_report_cannot_claim_freshness(self):
        with patch("hybrid_engine.premium_report_cache.time.time",return_value=10000000):
            cache_report(self.cache,self.TOKEN,self.report())
        with patch("hybrid_engine.premium_report_cache.time.time",return_value=10000000+7*86400+1):
            self.assertIsNone(DiskBackedReports(self.root,42).get(self.TOKEN))

    def test_no_credentials_or_live_reviewer_context_persisted(self):
        report=self.report()
        report["roster_context"]=dict(secret="not-persisted")
        report["research_market_cards"]=[dict(token="private-source")]
        cache_report(self.cache,self.TOKEN,report)
        raw=(self.root/(self.TOKEN+".json")).read_text(encoding="utf-8")
        self.assertNotIn("not-persisted",raw)
        self.assertNotIn("private-source",raw)
        restored=DiskBackedReports(self.root,42).get(self.TOKEN)
        self.assertNotIn("roster_context",restored)
        self.assertNotIn("research_market_cards",restored)


if __name__=="__main__":
    unittest.main()
