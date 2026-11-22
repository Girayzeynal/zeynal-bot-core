"""Offline tests of bounded public official NBA CDN retrieval after dual 403.

Every source and document in this file is manufactured; never live medical
information, a retrospective player forecast, or proof of any source uptime.
"""
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import time
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from hybrid_engine.current_roster import (
    CurrentRosterReview,NBA_COM_INJURY_INDEX,season_index,context_for)
from tests.test_current_roster import (
    snapshot,summary,extraction,FixtureSources,PDF,NOW)

CURRENT=int(datetime(2026,11,16,16,5,tzinfo=timezone.utc).timestamp())
READY_URL='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-16_10_45AM.pdf'
PENDING_URL='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-16_11_00AM.pdf'


class PublicDocumentDouble:
    def __init__(self,second_status=403,pdf_status=200):
        self.now=CURRENT;self.calls=[]
        self.original=FixtureSources(now=self.now)
        self.second_status=second_status
        self.pdf_status=pdf_status
    def __call__(self,url,*,deadline):
        self.calls.append(url)
        if url==season_index('2026/2027'):
            return dict(status='SOURCE_HTTP_ERROR',http_status=403,retry_after=300)
        if url==NBA_COM_INJURY_INDEX:
            return dict(status='SOURCE_HTTP_ERROR',http_status=self.second_status,retry_after=300)
        if url==PENDING_URL:
            return dict(status='SOURCE_HTTP_ERROR',http_status=404,retry_after=300)
        if url==READY_URL and self.pdf_status!=200:
            return dict(status='SOURCE_HTTP_ERROR',http_status=self.pdf_status,retry_after=300)
        if url==READY_URL:
            return dict(url=url,status='RECEIVED',body=PDF,
                body_sha256=hashlib.sha256(PDF).hexdigest(),
                started_at_utc=self.now-1,observed_at_utc=self.now)
        return self.original(url,deadline=deadline)


def extracted(*,correct_title=True):
    d=extraction()
    d['report_titles']=['InjuryReport:11/16/26'+
        ('10:45AM' if correct_title else '10:30AM')]
    return d


class AutomaticOfficialCDNFallbackTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.ctx=context_for(snapshot())
    def review(self,provider,extractor=None,*,fallback=True):
        service=CurrentRosterReview(self.root/'roster',
            getter=provider,extractor=extractor or
            (lambda path,deadline: extracted()),
            clock=lambda:provider.now,report_archive=self.root/'reports',
            bounded_public_pdf_fallback=fallback)
        return service.review(self.ctx)

    def test_fresh_exact_title_and_fixture_match_are_observed_only_not_first_forecast_input(self):
        provider=PublicDocumentDouble()
        result=self.review(provider)
        self.assertEqual(provider.calls.count(PENDING_URL),1)
        self.assertEqual(provider.calls.count(READY_URL),1)
        self.assertEqual(result['official_discovery_mode'],'BOUNDED_PUBLIC_OFFICIAL_CDN')
        self.assertFalse(result['latest_report_verified'])
        self.assertTrue(result['official_pdf_clock_verified'])
        self.assertEqual(result['public_cdn_candidates_maximum'],2)
        self.assertEqual(result['official_report']['source_url'],READY_URL)
        self.assertEqual(result['status'],'CURRENT_SOURCE_OBSERVATIONS')
        self.assertTrue(any(r['source']=='NBA_OFFICIAL_PDF' for r in result['records']))
        self.assertFalse(result['forecast_changed'])
        self.assertFalse(result['model_adjustment_applied'])
        self.assertLessEqual(result['valid_until_utc'],
                             result['official_report']['report_timestamp_utc']+1800)
        self.assertTrue(list((self.root/'roster').glob('pdf-*.pdf')))

    def test_403_on_both_indexes_is_required(self):
        provider=PublicDocumentDouble(second_status=429)
        result=self.review(provider)
        self.assertNotIn(READY_URL,provider.calls)
        self.assertNotIn(PENDING_URL,provider.calls)
        self.assertFalse(any(r['source']=='NBA_OFFICIAL_PDF' for r in result['records']))
        self.assertEqual(result['alternate_index_failure']['http_status'],429)

    def test_refuse_failed_cdn_without_making_up_an_official_status(self):
        provider=PublicDocumentDouble(pdf_status=404)
        result=self.review(provider)
        self.assertEqual(provider.calls.count(READY_URL),1)
        self.assertFalse(any(r['source']=='NBA_OFFICIAL_PDF' for r in result['records']))
        self.assertEqual(result['index_failure']['http_status'],403)
        self.assertIn('OFFICIAL_REPORT_UNAVAILABLE_OR_UNVERIFIED',result['warnings'])

    def test_wrong_header_clock_blocks_official_rows(self):
        provider=PublicDocumentDouble()
        result=self.review(provider,lambda path,deadline:extracted(correct_title=False))
        self.assertTrue(result['warnings'])
        self.assertFalse(any(r['source']=='NBA_OFFICIAL_PDF' for r in result['records']))
        self.assertEqual(result['official_code'],'EXPLICIT_REPORT_TITLE_CLOCK_MISMATCH')

    def test_direct_cdn_is_disabled_unless_explicitly_opted_in(self):
        provider=PublicDocumentDouble()
        result=self.review(provider,fallback=False)
        self.assertNotIn(PENDING_URL,provider.calls)
        self.assertNotIn(READY_URL,provider.calls)
        self.assertFalse(any(r['source']=='NBA_OFFICIAL_PDF' for r in result['records']))

    def test_et_midnight_uses_previous_day_correctly(self):
        provider=PublicDocumentDouble()
        provider.now=int(datetime(2026,11,22,5,2,tzinfo=timezone.utc).timestamp())
        current='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-22_12_00AM.pdf'
        previous='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-21_11_45PM.pdf'
        def capture(url,*,deadline):
            provider.calls.append(url)
            return dict(status='SOURCE_HTTP_ERROR',http_status=404,retry_after=300)
        service=CurrentRosterReview(self.root/'rollover',getter=capture,
            clock=lambda:provider.now,bounded_public_pdf_fallback=True)
        ref,pdf=service._public_pdf_after_two_403s(time.monotonic()+5)
        self.assertIsNone(ref);self.assertIsNone(pdf)
        self.assertEqual(provider.calls,[current,previous])

    def test_403_on_public_cdn_stops_before_second_candidate(self):
        provider=PublicDocumentDouble()
        def deny(url,*,deadline):
            provider.calls.append(url)
            return dict(status='SOURCE_HTTP_ERROR',http_status=403,retry_after=300)
        service=CurrentRosterReview(self.root/'stop',getter=deny,
            clock=lambda:provider.now,bounded_public_pdf_fallback=True)
        ref,pdf=service._public_pdf_after_two_403s(time.monotonic()+5)
        self.assertIsNone(ref);self.assertIsNone(pdf)
        self.assertEqual(provider.calls,[PENDING_URL])
