"""Offline official PDF archive replay does not backfill player minute evidence."""
from collections import Counter
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.team_identity import digest
from hybrid_engine.official_report_link import import_link
from hybrid_engine.roster_pdf_audit import audit


URL='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-21_05_15PM.pdf'
BODY=b'%PDF-1.7\nFAKE_SYNTHETIC_NO_REAL_PLAYERS\n'
SHA=hashlib.sha256(BODY).hexdigest()
REPORT_AT=1795299300
ARCHIVED=REPORT_AT+100


def extraction(path,*,deadline):
    rows=[
        dict(game_date='11/21/2026',game_time='07:30 (ET)',
             matchup='POR@NYK',team='Portland Trail Blazers',
             player_name='Test One',status='Out',reason='SYNTHETIC'),
        dict(game_date='11/21/2026',game_time='07:30 (ET)',
             matchup='POR@NYK',team='New York Knicks',
             player_name='Test Two',status='Out',reason='SYNTHETIC'),
        dict(game_date='11/21/2026',game_time='10:00 (ET)',
             matchup='BOS@SAC',team='Boston Celtics',
             player_name='Test Three',status='Out',reason='SYNTHETIC'),
    ]
    return dict(status='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION',rows=rows,
                rows_sha256=digest(rows),source_pdf_sha256=SHA,
                report_titles=['InjuryReport:11/21/2605:15PM'])


def receipt(url,*,deadline):
    if url!=URL:raise AssertionError('UNEXPECTED_URL')
    return dict(url=url,status='RECEIVED',body=BODY,body_sha256=SHA,
                started_at_utc=ARCHIVED-1,observed_at_utc=ARCHIVED)


class HistoricalPdfAuditTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        result=import_link(URL,self.root,getter=receipt,extractor=extraction,
                           clock=lambda:ARCHIVED)
        self.assertEqual(result['status'],'EXPLICIT_OFFICIAL_LINK_ARCHIVED')

    def test_old_report_can_be_audited_without_reviving_pregame_evidence(self):
        report=audit(self.root,'POR@NYK','2026-11-21',
                     clock=lambda:ARCHIVED+3600,extractor=extraction)
        self.assertEqual(report['status'],'OFFLINE_PDF_MATCHUP_ROWS_OBSERVED')
        self.assertEqual(report['matchup_rows'],2)
        self.assertEqual(report['parsed_rows'],3)
        self.assertEqual(report['matchup_rows_by_team'],
                         {'New York Knicks':1,'Portland Trail Blazers':1})
        self.assertEqual(report['matchups_seen'],['BOS@SAC','POR@NYK'])
        self.assertEqual(report['network_requests_made'],0)
        self.assertFalse(report['source_fresh_for_new_pregame_packet'])
        self.assertFalse(report['new_forecast_created'])
        self.assertFalse(report['original_forecasts_changed'])
        self.assertFalse(report['player_model_activated'])
        self.assertEqual(report['pdf_sha256'],SHA)

    def test_wrong_date_and_wrong_pair_do_not_match_or_invent_athletes(self):
        for pair,date in [('POR@NYK','2026-11-22'),
                          ('NYK@POR','2026-11-21')]:
            with self.subTest(pair=pair,date=date):
                report=audit(self.root,pair,date,
                             clock=lambda:ARCHIVED+7200,extractor=extraction)
                self.assertEqual(report['status'],'OFFLINE_PDF_NO_MATCHING_ROWS')
                self.assertEqual(report['matchup_rows'],0)
                self.assertTrue(report['historical_document_only'])

    def test_mutated_archived_pdf_fails_before_extraction(self):
        pdf=self.root/('pdf-'+SHA+'.pdf')
        pdf.write_bytes(BODY+b'TAMPERED')
        with self.assertRaisesRegex(ValueError,'CONTENT_PIN_FAILED'):
            audit(self.root,'POR@NYK','2026-11-21',
                  clock=lambda:ARCHIVED+3600,extractor=extraction)

    def test_rejects_unscoped_pair_and_invalid_date_without_reading_archive(self):
        for pair,date in [('ANY','2026-11-21'),('POR@NYK','2026-11-XX')]:
            with self.subTest(pair=pair,date=date),self.assertRaises(ValueError):
                audit(self.root,pair,date,clock=lambda:ARCHIVED+3600,
                      extractor=extraction)

    def test_wrong_source_digest_from_parser_cannot_be_accepted(self):
        def bad(path,*,deadline):
            r=extraction(path,deadline=deadline);r['source_pdf_sha256']='0'*64
            return r
        with self.assertRaisesRegex(ValueError,'EXTRACTED_ROWS_PIN_FAILED'):
            audit(self.root,'POR@NYK','2026-11-21',
                  clock=lambda:ARCHIVED+3600,extractor=bad)
