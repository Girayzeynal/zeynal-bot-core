"""Actual public PDF replay, not new predictions or Telegram delivery."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.team_identity import digest
from hybrid_engine.current_roster import CurrentRosterReview,review_diagnostics

PACKET=Path(__file__).resolve().parents[1]/'docs/evidence/roster-phase931-denver-native-20261117.tar.gz'
PIN='b86111bc6ce429c02accaf11677fa885cb14978286ffd3aac13ea965b824a84f'


def native_case():
    body=PACKET.read_bytes()
    if hashlib.sha256(body).hexdigest()!=PIN: raise ValueError('DENVER_PACKET_PIN')
    files={}
    with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as tar:
        for member in tar.getmembers():
            if not member.isfile() or member.name not in ('manifest.json','case.json') or member.name in files or member.size>8*1024*1024:
                raise ValueError('DENVER_PACKET_MEMBER')
            files[member.name]=tar.extractfile(member).read()
    manifest=json.loads(files['manifest.json'])
    if hashlib.sha256(files['case.json']).hexdigest()!=manifest['files']['case.json']:
        raise ValueError('DENVER_CASE_PIN')
    return manifest,json.loads(files['case.json'])


class DenverNativeRosterTests(TestCase):
    def test_packet_preserves_original_incomplete_review_and_creates_no_forecasts(self):
        manifest,c=native_case(); original=c['captured_v1_review']
        self.assertEqual(digest(original['payload']),original['sha256'])
        self.assertEqual(c['v1_extracted_rows'],8); self.assertEqual(c['v2_extracted_rows'],112)
        self.assertEqual(c['forecasts_created'],0); self.assertEqual(c['prospective_minutes_created'],0)
        self.assertFalse(c['actual_telegram_delivery_verified'])
        self.assertIsNone(manifest['original_snapshot_sha256'])
        self.assertIsNone(c['context']['prediction_generated_at_utc'])

    def test_native_source_bytes_and_access_clocks_are_pinned(self):
        _,c=native_case()
        for r in c['receipts']:
            body=bytes.fromhex(r['body_hex'])
            self.assertEqual(hashlib.sha256(body).hexdigest(),r['body_sha256'])
            self.assertLessEqual(r['started_at_utc'],r['observed_at_utc'])
            self.assertLessEqual(r['observed_at_utc'],c['captured_v1_review']['payload']['observed_at_utc'])

    def test_worker_recovers_later_page_players_but_keeps_corroboration_blocks(self):
        _,c=native_case(); before=digest(c)
        receipts={r['url']:r for r in c['receipts']}
        def getter(url,*,deadline):
            r=deepcopy(receipts[url]); r['body']=bytes.fromhex(r.pop('body_hex')); return r
        now=c['captured_v1_review']['payload']['observed_at_utc']
        with TemporaryDirectory() as tmp:
            review=CurrentRosterReview(tmp,getter=getter,clock=lambda:now).review(c['context'])
        self.assertEqual(review['status'],'CURRENT_SOURCE_OBSERVATIONS')
        self.assertFalse(review['model_adjustment_applied']); self.assertEqual(digest(c),before)
        if importlib.util.find_spec('pdfplumber') is None:
            self.assertEqual(review['official_extraction_status'],'PDF_DEPENDENCY_MISSING')
            return
        self.assertEqual(review['official_parsed_rows'],112)
        self.assertEqual(review['official_fixture_rows'],7)
        rows=[r for r in review['records'] if r['source']=='NBA_OFFICIAL_PDF']
        self.assertEqual({(r['player_name'],r['status']) for r in rows},
            {('Dunn,Ryan','Available'),('Timme,Drew','Out'),('Williams,Mark','Out'),
             ('HolmesII,DaRon','Out'),('Nembhard,Ryan','Out'),('Strawther,Julian','Out'),('Whitmore,Cam','Out')})
        d=review_diagnostics(review)
        self.assertEqual(d['missing_absence_count'],4)
        self.assertTrue(all(r['missing_sources']==['ESPN'] for r in d['missing_absence_corroboration']))
        self.assertIsNone(d['confidence_index'])

    def test_native_pdf_title_and_fresh_clock_bind_explicit_403_fallback(self):
        from hybrid_engine.official_report_link import import_link
        from hybrid_engine.current_roster import season_index
        _,c=native_case(); receipts={r['url']:r for r in c['receipts']}
        now=c['captured_v1_review']['payload']['observed_at_utc']
        url=next(u for u in receipts if u.endswith('.pdf'))
        def getter(url,*,deadline):
            if url==season_index(c['context']['season']):
                return dict(status='SOURCE_HTTP_ERROR',http_status=403,retry_after=300)
            r=deepcopy(receipts[url]); r['body']=bytes.fromhex(r.pop('body_hex')); return r
        with TemporaryDirectory() as tmp:
            links=Path(tmp)/'links'
            if importlib.util.find_spec('pdfplumber') is None:
                with self.assertRaisesRegex(ValueError,'PARSER_UNAVAILABLE'):
                    import_link(url,links,getter=getter,clock=lambda:now)
                self.assertEqual(list(links.glob('link-*')),[])
                return
            imported=import_link(url,links,getter=getter,clock=lambda:now)
            self.assertFalse(imported['latest_report_verified'])
            review=CurrentRosterReview(Path(tmp)/'review',getter=getter,clock=lambda:now,
                                       report_archive=links).review(c['context'])
            self.assertEqual(review['official_fixture_rows'],7)
            self.assertEqual(review['official_discovery_mode'],'EXPLICIT_OFFICIAL_CDN_LINK')
            self.assertFalse(review['latest_report_verified'])
            self.assertEqual(review_diagnostics(review)['missing_absence_count'],4)
