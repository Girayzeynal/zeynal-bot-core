"""Strict first-party NBA.com injury index fallback after official.nba.com 403.

Synthetic fixtures; no external network, no actual player medical inference.
"""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from hybrid_engine.current_roster import (
    CurrentRosterReview, NBA_COM_INJURY_INDEX, season_index,
    allowed_url, context_for, review_diagnostics,
)
from tests import test_current_roster as f


class OfficialNBAComDirectoryTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.base=f.FixtureSources()
        self.calls=[]
        self.context=context_for(f.snapshot())
        self.primary_code=403
        self.mirror_code=200
        self.html=('<html><main><a href="'+f.PDF_URL+'">Official NBA PDF</a></main></html>').encode()

    def get(self,url,*,deadline):
        self.calls.append(url)
        if url==season_index("2026/2027"):
            return dict(status="SOURCE_HTTP_ERROR",
                        http_status=self.primary_code,retry_after=300)
        if url==NBA_COM_INJURY_INDEX:
            if self.mirror_code!=200:
                return dict(status="SOURCE_HTTP_ERROR",
                            http_status=self.mirror_code,retry_after=300)
            return dict(url=url,status="RECEIVED",body=self.html,
                        started_at_utc=f.NOW-1,observed_at_utc=f.NOW,
                        body_sha256=hashlib.sha256(self.html).hexdigest())
        return self.base(url,deadline=deadline)

    def review(self):
        return CurrentRosterReview(self.root/"reviews",getter=self.get,
                                   extractor=lambda path,deadline:f.extraction(),
                                   clock=lambda:f.NOW).review(self.context)

    def test_403_uses_official_nba_com_pdf_index_with_same_pdf_and_audited_denial(self):
        result=self.review()
        self.assertTrue(allowed_url(NBA_COM_INJURY_INDEX))
        self.assertEqual(result["official_discovery_mode"],"LIVE_NBA_COM_OFFICIAL_INDEX")
        self.assertTrue(result["latest_report_verified"])
        self.assertEqual(result["index_failure"]["http_status"],403)
        self.assertEqual(result["official_report"]["source_url"],f.PDF_URL)
        self.assertIn(NBA_COM_INJURY_INDEX,self.calls)
        self.assertIn(f.PDF_URL,self.calls)
        self.assertIn(NBA_COM_INJURY_INDEX,
                      review_diagnostics(result)["successful_source_urls"])
        self.assertFalse(result["model_adjustment_applied"])
        self.assertFalse(result["lineup_verified"])
        self.assertFalse(result["forecast_changed"])

    def test_other_primary_denials_do_not_trigger_alternate_page(self):
        for http in (401,404,429,500):
            with self.subTest(http=http):
                self.calls.clear()
                self.primary_code=http
                result=self.review()
                self.assertNotIn(NBA_COM_INJURY_INDEX,self.calls)
                self.assertNotIn("LIVE_NBA_COM_OFFICIAL_INDEX",
                                [result.get("official_discovery_mode")])
                self.assertEqual(result["official_http_status"],http)

    def test_mirror_denied_or_links_missing_does_not_create_fake_official_data(self):
        self.mirror_code=403
        result=self.review()
        self.assertEqual(result["official_http_status"],403)
        self.assertNotIn(f.PDF_URL,self.calls)
        self.assertFalse(result.get("latest_report_verified",False))
        self.assertEqual(result["index_failure"]["http_status"],403)
        self.assertEqual(result["alternate_index_failure"]["http_status"],403)
        self.mirror_code=200
        self.html=b'<html><a href="https://evil.invalid/Report.pdf">bad</a></html>'
        result=self.review()
        self.assertFalse(result["latest_report_verified"])
        self.assertNotIn(f.PDF_URL,self.calls)
        self.assertEqual(result["official_code"],"NO_RECENT_PUBLISHED_REPORT")

    def test_security_allowlist_excludes_tampered_official_index(self):
        for url in (NBA_COM_INJURY_INDEX+"?key=secret",
                    NBA_COM_INJURY_INDEX+"/",
                    NBA_COM_INJURY_INDEX.replace("www.nba.com","nba.com.evil.invalid"),
                    NBA_COM_INJURY_INDEX.replace("https:","http:")):
            with self.subTest(url=url):
                self.assertFalse(allowed_url(url))
