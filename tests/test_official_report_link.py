"""Explicit official PDF publication links are opt-in, fresh and source-bound."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.current_roster import CurrentRosterReview,context_for,season_index,render_review,review_diagnostics
from hybrid_engine.official_report_link import import_link,select_link,assert_report_title,reference,MAX_AGE
from tests import test_current_roster as f

NOW=f.NOW
URL='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-16_10_45AM.pdf'
PDF=b'%PDF-1.7\nEXPLICIT_SOURCE_LINK_SYNTHETIC'


def extract(path,*,deadline):
    e=f.extraction(); e['source_pdf_sha256']=hashlib.sha256(PDF).hexdigest()
    e['report_titles']=['InjuryReport:11/16/2610:45AM']
    return e


def receipt(url=URL):
    return dict(url=url,status='RECEIVED',body=PDF,body_sha256=hashlib.sha256(PDF).hexdigest(),
        started_at_utc=NOW-1,observed_at_utc=NOW)


class ExplicitOfficialLinkTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=Path(tmp.name)
        timer=patch('time.time',return_value=NOW); timer.start(); self.addCleanup(timer.stop)
        self.directory=self.root/'links'

    def import_one(self,**kw):
        return import_link(URL,self.directory,getter=kw.pop('getter',lambda *a,**k:receipt()),
            extractor=kw.pop('extractor',extract),clock=kw.pop('clock',lambda:NOW),**kw)

    def test_fresh_link_imports_without_latest_or_prediction_claim(self):
        r=self.import_one(); self.assertEqual(r['status'],'EXPLICIT_OFFICIAL_LINK_ARCHIVED')
        self.assertFalse(r['latest_report_verified']); self.assertFalse(r['forecast_created'])
        p,pin=select_link(self.directory,'2026/2027',NOW)
        self.assertEqual(p['url'],URL); self.assertEqual(pin,r['entry_sha256'])

    def test_title_matches_filename_clock_and_requires_a_single_report(self):
        ref=reference(URL,NOW)
        for titles in ([],['Not an official title'],['InjuryReport:11/16/2610:30AM'],
                       ['InjuryReport:11/16/2610:45AM','InjuryReport:11/16/2611:00AM']):
            with self.subTest(titles=titles),self.assertRaises(ValueError):
                assert_report_title(dict(report_titles=titles),ref)

    def test_guessed_future_stale_foreign_redirect_and_query_urls_are_refused(self):
        for url in (URL.replace('10_45AM','11_30AM'),URL.replace('10_45AM','08_00AM'),
                    URL.replace('ak-static.cms.nba.com','evil.invalid'),URL+'?token=secret',URL.replace('https:','http:')):
            calls=[]
            with self.subTest(url=url),self.assertRaises(ValueError):
                import_link(url,self.directory,getter=lambda *a,**k:calls.append(a),clock=lambda:NOW)
            self.assertEqual(calls,[])

    def test_non_200_or_redirect_status_cannot_be_imported(self):
        for status in ('SOURCE_HTTP_ERROR','SOURCE_UNAVAILABLE'):
            with self.assertRaisesRegex(ValueError,'SOURCE_UNAVAILABLE'):
                self.import_one(getter=lambda *a,**k:dict(status=status,http_status=302))
        self.assertFalse(self.directory.exists())

    def test_receipt_pin_clock_and_body_type_are_validated(self):
        for kind in ('pin','future','url','signature'):
            r=receipt()
            if kind=='pin': r['body_sha256']='0'*64
            elif kind=='future': r['observed_at_utc']=NOW+1
            elif kind=='url': r['url']=URL+'?changed=1'
            else: r['body']=b'NOT A PDF';r['body_sha256']=hashlib.sha256(r['body']).hexdigest()
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                self.import_one(getter=lambda *a,**k:r)

    def test_parser_missing_or_wrong_pdf_pin_never_publishes_link(self):
        with self.assertRaisesRegex(ValueError,'PARSER_UNAVAILABLE'):
            self.import_one(extractor=lambda *a,**k:dict(status='PDF_DEPENDENCY_MISSING'))
        with self.assertRaisesRegex(ValueError,'EXTRACTION_PIN'):
            self.import_one(extractor=lambda *a,**k:dict(extract(*a,**k),source_pdf_sha256='0'*64))
        self.assertEqual(list(self.directory.glob('link-*')),[])

    def test_duplicate_import_keeps_first_archive_bytes_and_time(self):
        first=self.import_one(); before={p:p.read_bytes() for p in self.directory.iterdir()}
        again=self.import_one(clock=lambda:NOW+20)
        self.assertEqual(again['status'],'EXISTING_EXPLICIT_LINK')
        self.assertEqual(again['first_archived_at_utc'],first['first_archived_at_utc'])
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_expired_and_other_season_links_are_not_selected(self):
        self.import_one()
        self.assertIsNone(select_link(self.directory,'2025/2026',NOW))
        self.assertIsNone(select_link(self.directory,'2024/2025',NOW))
        self.assertIsNone(select_link(self.directory,'2026/2027',NOW+MAX_AGE+1))

    def test_rehashed_future_archive_clock_and_bad_filename_are_refused(self):
        self.import_one(); p=next(self.directory.glob('link-*')); w=json.loads(p.read_text())
        w['payload']['first_archived_at_utc']=NOW+1;w['sha256']=digest(w['payload']);p.write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'ENTRY_CLOCK'): select_link(self.directory,'2026/2027',NOW)

    def test_no_registry_is_read_only_and_does_not_create_directory(self):
        self.assertIsNone(select_link(self.directory,'2026/2027',NOW)); self.assertFalse(self.directory.exists())

    def test_revised_content_uses_later_explicit_archive_and_rejects_same_time_conflict(self):
        from hybrid_engine.boxes import publish_json
        self.import_one(); original=select_link(self.directory,'2026/2027',NOW)[0]
        changed=dict(original,pdf_sha256='0'*64,received_at_utc=NOW+5,first_archived_at_utc=NOW+5)
        path=self.directory/('link-'+digest(dict(url=URL,pdf_sha256=changed['pdf_sha256']))+'.json')
        publish_json(path,dict(payload=changed,sha256=digest(changed)))
        self.assertEqual(select_link(self.directory,'2026/2027',NOW+5)[0]['pdf_sha256'],'0'*64)
        conflicting=dict(changed,pdf_sha256='1'*64)
        path=self.directory/('link-'+digest(dict(url=URL,pdf_sha256=conflicting['pdf_sha256']))+'.json')
        publish_json(path,dict(payload=conflicting,sha256=digest(conflicting)))
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_CONTENT'): select_link(self.directory,'2026/2027',NOW+5)

    def test_cli_failure_has_nonzero_status_and_redacts_exception_text(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from hybrid_engine.official_report_link import main
        output=StringIO()
        with patch('sys.argv',['link','--url',URL,'--directory',str(self.directory)]),patch(
                'hybrid_engine.official_report_link.import_link',side_effect=ValueError('SECRET_DO_NOT_SHOW')):
            with redirect_stdout(output): result=main()
        self.assertEqual(result,2); self.assertNotIn('SECRET_DO_NOT_SHOW',output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'],'BLOCKED')


class Explicit403FallbackTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=Path(tmp.name)
        self.links=self.root/'official-links'
        self.fake=f.FixtureSources(); self.context=context_for(f.snapshot())
        import_link(URL,self.links,getter=lambda *a,**k:receipt(),extractor=extract,clock=lambda:NOW)
        self.index_failures=0; self.pdf_override=False

    def getter(self,url,*,deadline):
        if url==season_index('2026/2027'):
            self.index_failures+=1
            return dict(status='SOURCE_HTTP_ERROR',http_status=self.http,retry_after=300)
        if url==URL:
            if self.pdf_override: return dict(receipt(),body_sha256='0'*64)
            return receipt()
        return self.fake(url,deadline=deadline)

    def service(self,http=403,archive=True,extractor=extract):
        self.http=http
        return CurrentRosterReview(self.root/'reviews',getter=self.getter,extractor=extractor,
            clock=lambda:self.fake.now,report_archive=self.links if archive else None)

    def test_exact_403_can_use_explicit_pdf_but_retains_index_failure_and_no_latest_claim(self):
        r=self.service().review(self.context)
        self.assertEqual(r['official_discovery_mode'],'EXPLICIT_OFFICIAL_CDN_LINK')
        self.assertFalse(r['latest_report_verified']); self.assertEqual(r['index_failure']['http_status'],403)
        self.assertEqual(r['official_fixture_rows'],1)
        self.assertIn('En güncel rapor olduğu doğrulanmadı',render_review(r))
        self.assertEqual(review_diagnostics(r)['index_failure']['http_status'],403)

    def test_fallback_is_disabled_without_explicit_registry(self):
        r=self.service(archive=False).review(self.context)
        self.assertEqual(len(r['records']),1); self.assertNotIn('official_discovery_mode',r)

    def test_other_http_codes_do_not_activate_403_fallback(self):
        for status in (401,404,429,500):
            r=self.service(http=status).review(self.context)
            self.assertNotIn('official_discovery_mode',r)
            self.assertEqual(r['official_http_status'],status)

    def test_stale_link_does_not_refresh_its_clock_or_bypass_denial(self):
        self.fake.now=NOW+MAX_AGE+1
        r=self.service().review(self.context)
        self.assertNotIn('official_discovery_mode',r)
        self.assertEqual(r['official_http_status'],403)

    def test_pdf_body_pin_cannot_be_changed_after_import(self):
        self.pdf_override=True; r=self.service().review(self.context)
        self.assertEqual(r['official_stage'],'PDF_FETCH'); self.assertEqual(len(r['records']),1)

    def test_wrong_pdf_title_cannot_create_official_observations(self):
        def wrong(*a,**k): return dict(extract(*a,**k),report_titles=['InjuryReport:11/16/2610:30AM'])
        r=self.service(extractor=wrong).review(self.context)
        self.assertEqual(r['official_code'],'EXPLICIT_REPORT_TITLE_CLOCK_MISMATCH')
        self.assertEqual(len(r['records']),1)

    def test_source_cooldown_is_respected_across_new_reviews(self):
        service=self.service(); service.review(self.context); service.cache.clear(); service.review(self.context)
        self.assertEqual(self.index_failures,1)

    def test_post_tipoff_still_performs_no_source_work(self):
        service=self.service(); self.fake.now=f.START
        r=service.review(self.context)
        self.assertEqual(r['status'],'POST_TIPOFF_NO_CURRENT_BACKFILL'); self.assertEqual(self.index_failures,0)

    def test_live_index_also_rejects_a_parseable_wrong_publication_clock(self):
        def wrong(path,*,deadline):
            e=f.extraction(); e['report_titles']=['InjuryReport:11/16/2609:45AM']; return e
        service=CurrentRosterReview(self.root/'live-index',getter=self.fake,extractor=wrong,clock=lambda:NOW)
        r=service.review(self.context)
        self.assertEqual(r['official_code'],'EXPLICIT_REPORT_TITLE_CLOCK_MISMATCH')
        self.assertEqual(len(r['records']),1)

    def test_cached_review_expires_at_report_age_limit_not_five_minutes_later(self):
        self.http=403; self.fake.now=NOW+899
        def fresh_get(url,*,deadline):
            r=self.getter(url,deadline=deadline)
            if url==URL: r.update(started_at_utc=self.fake.now-1,observed_at_utc=self.fake.now)
            return r
        service=CurrentRosterReview(self.root/'boundary',getter=fresh_get,extractor=extract,
            clock=lambda:self.fake.now,report_archive=self.links)
        first=service.review(self.context)
        self.assertEqual(first['valid_until_utc'],NOW+900)
        self.fake.now+=2
        later=service.review(self.context)
        self.assertNotIn('official_discovery_mode',later)
        self.assertEqual(len(later['records']),1)
