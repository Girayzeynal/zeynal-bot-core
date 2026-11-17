"""Continuation layout, explicit failure stages and read-only source diagnostics."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import sys

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.current_roster import (CurrentRosterReview,context_for,season_index,
    review_diagnostics,inspect_review)
from hybrid_engine.nba_injury_pdf_parser import extract_nba_injury_rows,HEADERS
from tests import test_current_roster as f

ANCHORS=[23.1,119.6,200.,264.2,425.,585.7,666.1]
TITLE='InjuryReport:11/16/2608:30PM'


def line(y,values):
    return [dict(text=v,x0=x,top=y) for x,v in zip(ANCHORS,values) if v]


def coordinate_page(first=False,title=TITLE,width=841.95,extra=None):
    words=[dict(text=title,x0=500.,top=40.)] if title else []
    if first: words+=line(100,['GameDate','GameTime','Matchup','Team','PlayerName','CurrentStatus','Reason'])
    words+=extra or []
    return SimpleNamespace(width=width,height=595.35,extract_words=lambda:words,extract_tables=lambda:[])


def parse(pages):
    class PDF:
        def __enter__(self): return self
        def __exit__(self,*args): pass
    pdf=PDF(); pdf.pages=pages
    fake=SimpleNamespace(open=lambda stream:pdf)
    data=b'%PDF-1.7 SYNTHETIC'
    with patch.dict(sys.modules,{'pdfplumber':fake}):
        return extract_nba_injury_rows(data,expected_sha256=hashlib.sha256(data).hexdigest())


class ContinuedReportTests(TestCase):
    def first(self):
        return coordinate_page(True,extra=line(130,['11/16/2026','09:00(ET)','PHX@DEN','PhoenixSuns','Williams,Mark','Out','Shoulder']))

    def test_headerless_continuation_uses_same_title_geometry_and_preserves_wrapped_status(self):
        second=coordinate_page(extra=line(120,['','','','DenverNuggets','Strawther,Julian','Out','']))
        r=parse([self.first(),second]); self.assertEqual(len(r['rows']),2)
        self.assertEqual(r['rows'][1]['matchup'],'PHX@DEN'); self.assertEqual(r['rows'][1]['reason'],'')
        self.assertTrue(r['rows'][1]['reason_fragment']); self.assertFalse(r['extraction_verified'])

    def test_changed_title_is_not_inherited_as_the_previous_report(self):
        with self.assertRaisesRegex(ValueError,'CONTINUATION_LAYOUT'):
            parse([self.first(),coordinate_page(title=TITLE+'CHANGED')])

    def test_changed_geometry_cannot_reuse_old_column_positions(self):
        with self.assertRaisesRegex(ValueError,'CONTINUATION_LAYOUT'):
            parse([self.first(),coordinate_page(width=600)])

    def test_headerless_page_without_report_title_is_not_silently_skipped(self):
        second=coordinate_page(title=None,extra=line(120,['','','','DenverNuggets','Example,Player','Out','Knee']))
        with self.assertRaisesRegex(ValueError,'CONTINUATION_LAYOUT'): parse([self.first(),second])

    def test_new_matchup_without_team_does_not_carry_old_matchup_into_next_row(self):
        second=coordinate_page(extra=line(120,['','','AAA@BBB','','Unknown,One','Out','Knee'])+
            line(145,['','','','OtherTeam','Unknown,Two','Out','Knee']))
        rows=parse([self.first(),second])['rows']
        self.assertEqual([r['player_name'] for r in rows],['Williams,Mark'])

    def test_new_time_without_matchup_does_not_inherit_old_game(self):
        second=coordinate_page(extra=line(120,['','10:00(ET)','','','Unknown,One','Out','Knee']))
        self.assertEqual(len(parse([self.first(),second])['rows']),1)

    def test_mixed_detected_table_and_coordinate_body_does_not_drop_later_rows(self):
        first=self.first()
        first.extract_tables=lambda:[[list(HEADERS),['11/16/2026','09:00(ET)','PHX@DEN','PhoenixSuns','Williams,Mark','Out','Complete table reason']]]
        second=coordinate_page(extra=line(120,['','','','DenverNuggets','Strawther,Julian','Out','Knee']))
        rows=parse([first,second])['rows']
        self.assertEqual(len(rows),2); self.assertEqual(rows[0]['reason'],'Complete table reason')

    def test_disagreement_between_extraction_methods_fails_closed(self):
        first=self.first()
        first.extract_tables=lambda:[[list(HEADERS),['11/16/2026','09:00(ET)','PHX@DEN','PhoenixSuns','Williams,Mark','Available','Knee']]]
        with self.assertRaisesRegex(ValueError,'STATUS_CONFLICT'): parse([first])


class RosterDiagnosticTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=Path(tmp.name)
        self.fake=f.FixtureSources(); self.service=CurrentRosterReview(self.root/'review',getter=self.fake,
            extractor=lambda path,deadline:f.extraction(),clock=lambda:self.fake.now)
        self.context=context_for(f.snapshot())

    def test_index_failure_reports_stage_and_native_http_status(self):
        self.fake.fail.add(season_index('2026/2027')); r=self.service.review(self.context)
        self.assertEqual(r['official_stage'],'INDEX_FETCH'); self.assertEqual(r['official_http_status'],429)
        self.assertEqual(r['official_code'],'ROSTER_SOURCE_UNAVAILABLE')
        self.assertEqual(len(r['records']),1)

    def test_pdf_failure_is_distinguished_from_index_failure(self):
        self.fake.fail.add(f.PDF_URL); r=self.service.review(self.context)
        self.assertEqual(r['official_stage'],'PDF_FETCH'); self.assertEqual(r['official_http_status'],429)
        self.assertIsNone(r.get('official_extraction_status'))

    def test_parser_timeout_does_not_expose_exception_contents(self):
        self.service.extractor=lambda *a,**k:(_ for _ in ()).throw(TimeoutError('SECRET_DO_NOT_LOG'))
        r=self.service.review(self.context)
        self.assertEqual(r['official_stage'],'PDF_EXTRACTION')
        self.assertEqual(r['official_code'],'OFFICIAL_SOURCE_OR_PARSE_TIMEOUT')
        self.assertNotIn('SECRET_DO_NOT_LOG',json.dumps(r))

    def test_missing_dependency_is_explicit_and_not_guessed_from_none(self):
        self.service.extractor=lambda *a,**k:dict(status='PDF_DEPENDENCY_MISSING',rows=[])
        r=self.service.review(self.context)
        self.assertEqual(r['official_code'],'PDF_DEPENDENCY_MISSING')
        self.assertEqual(r['official_stage'],'PDF_EXTRACTION')

    def test_parsed_but_unmatched_report_is_explicit(self):
        e=f.extraction(); e['rows'][0]['matchup']='AAA@BBB'; e['rows_sha256']=digest(e['rows'])
        self.service.extractor=lambda *a,**k:e
        r=self.service.review(self.context)
        self.assertEqual(r['official_parsed_rows'],1); self.assertEqual(r['official_fixture_rows'],0)
        self.assertEqual(r['official_code'],'NO_MATCHING_OFFICIAL_ROWS')

    def test_diagnostics_name_missing_source_without_fabricating_confidence(self):
        r=self.service.review(self.context); d=review_diagnostics(r)
        self.assertEqual(d['missing_absence_count'],1)
        self.assertEqual(d['missing_absence_corroboration'][0]['missing_sources'],['NBA_OFFICIAL_PDF'])
        self.assertIsNone(d['confidence_index']); self.assertTrue(d['diagnostic_only'])

    def test_multiple_unmapped_names_are_not_merged_under_none_id(self):
        r=dict(records=[dict(team_id='1',player_id=None,player_name=n,source='NBA_OFFICIAL_PDF',status='Out')
                        for n in ('Unknown,One','Unknown,Two')])
        self.assertEqual(review_diagnostics(r)['missing_absence_count'],2)

    def test_read_only_inspection_preserves_old_review_and_reports_unknown_old_failure_stage(self):
        r=self.service.review(self.context)
        r.pop('official_stage',None); r['warnings']=['OFFICIAL_REPORT_UNAVAILABLE_OR_UNVERIFIED']
        directory=self.root/'legacy'; directory.mkdir()
        publish_json(directory/('review-'+digest(r)+'.json'),dict(payload=r,sha256=digest(r)))
        before={p:p.read_bytes() for p in directory.iterdir()}
        with patch('hybrid_engine.current_roster.native_get',side_effect=AssertionError('NO_NETWORK')):
            d=inspect_review(directory,'401000001')
        self.assertEqual(d['status'],'READ_ONLY_ARCHIVED_ROSTER_DIAGNOSTIC')
        self.assertTrue(d['legacy_failure_stage_unknown']); self.assertEqual(d['api_requests_made'],0)
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_missing_inspection_archive_is_not_created(self):
        path=self.root/'missing'; d=inspect_review(path,'401000001')
        self.assertEqual(d['status'],'ARCHIVE_UNAVAILABLE'); self.assertFalse(path.exists())

    def test_rehashed_filename_mismatch_cannot_be_shown_as_valid_inspection(self):
        r=self.service.review(self.context); p=next((self.root/'review').glob('review-*'))
        w=json.loads(p.read_text());w['payload']['warnings']=['CHANGED'];w['sha256']=digest(w['payload'])
        p.write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'INSPECTION_PIN'): inspect_review(self.root/'review','401000001')
