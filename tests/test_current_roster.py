"""Manufactured roster cases, fixed source clocks; no real Telegram evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import time
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.current_roster import (CurrentRosterReview, context_for, PREFIX, season_index,
    bind_summary, espn_rows, roster_ids, nba_rows, latest_report, render_review, allowed_url, native_get,
    pdf_extract, TTL)
from hybrid_engine.telegram_premium_ui import page_view

NOW = int(datetime(2026, 11, 16, 16, tzinfo=timezone.utc).timestamp())
START = int(datetime(2026, 11, 17, 0, tzinfo=timezone.utc).timestamp())
PDF_URL = 'https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-16_10_00AM.pdf'
PDF = b'%PDF-1.7\nMANUFACTURED_TEST_ONLY'


def snapshot():
    return dict(league='NBA', season='2026/2027', fixture_id='synthetic-game', provider_fixture_ids=['401000001'],
        fixture_start_utc=START, prediction_generated_at_utc=NOW-3600, model_digest='a'*64,
        home=dict(provider_id='1', official_name='Test Home'), away=dict(provider_id='2', official_name='Test Away'),
        prediction=dict(home=100., away=90., total=190.), calibration_status='NOT_CALIBRATED')


def summary():
    teams = [dict(id=tid, homeAway=side, team=dict(id=tid, displayName=name, abbreviation=abbr))
             for tid, side, name, abbr in [('1','home','Test Home','HOM'), ('2','away','Test Away','AWY')]]
    return dict(header=dict(id='401000001', season=dict(year=2027), competitions=[dict(id='401000001',
        date='2026-11-17T00:00:00Z', competitors=teams,
        status=dict(type=dict(name='STATUS_SCHEDULED', completed=False)))]),
        injuries=[dict(team=dict(id='1', displayName='Test Home'), injuries=[]),
        dict(team=dict(id='2', displayName='Test Away'), injuries=[dict(status='Out', date='2026-11-16T14:00:00Z',
            athlete=dict(id='22', displayName='Test Player'), details=dict(type='Knee', side='Left'))])])


def extraction():
    rows = [dict(game_date='11/16/2026', game_time='07:00(ET)', matchup='AWY@HOM',
                 team='Test Away', player_name='Player, Test', status='Questionable', reason='Injury/Illness - Knee')]
    return dict(status='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION', rows=rows, rows_sha256=digest(rows),
                source_pdf_sha256=hashlib.sha256(PDF).hexdigest(), extraction_verified=False)


class FixtureSources:
    def __init__(self, now=NOW):
        self.now=now; self.calls=[]; self.document=summary(); self.fail=set(); self.bad_pin=False

    def __call__(self, url, *, deadline):
        self.calls.append(url)
        if url in self.fail: return dict(status='SOURCE_HTTP_ERROR', http_status=429, retry_after=600)
        if 'summary?' in url: body=json.dumps(self.document).encode()
        elif url==season_index('2026/2027'): body=('<html><a href="'+PDF_URL+'">Report</a></html>').encode()
        elif url==PDF_URL: body=PDF
        elif '/roster?' in url:
            tid=url.split('/teams/')[1].split('/')[0]
            body=json.dumps(dict(team=dict(id=tid, displayName='Test Home' if tid=='1' else 'Test Away'),
                season=dict(year=2027), athletes=[dict(id='22' if tid=='2' else '11', displayName='Test Player')])).encode()
        else: raise AssertionError('Unexpected fixture source '+url)
        return dict(url=url, body=body, status='RECEIVED', started_at_utc=self.now-1, observed_at_utc=self.now,
                    body_sha256='0'*64 if self.bad_pin else hashlib.sha256(body).hexdigest())


class RosterPureTests(TestCase):
    def setUp(self):
        self.context=context_for(snapshot()); self.teams=bind_summary(summary(), self.context, NOW)

    def test_context_has_original_snapshot_pin_but_never_copies_or_mutates_score(self):
        s=snapshot(); before=deepcopy(s); c=context_for(s)
        self.assertEqual(c['original_snapshot_sha256'], digest(s)); self.assertEqual(s,before)
        self.assertNotIn('prediction',c)

    def test_invalid_context_does_not_guess_provider_ids(self):
        for change in ({'provider_fixture_ids':['unsafe?token=x']}, {'prediction_generated_at_utc':START},
                       {'prediction_generated_at_utc':True}, {'league':'EUROLEAGUE'}):
            with self.subTest(change=change), self.assertRaises(ValueError): context_for(dict(snapshot(),**change))

    def test_source_url_allowlist_refuses_redirect_hosts_credentials_and_arbitrary_paths(self):
        self.assertTrue(allowed_url(PREFIX+'summary?event=401000001')); self.assertTrue(allowed_url(PDF_URL))
        for url in ('http://official.nba.com/x','https://evil.invalid/report.pdf',PDF_URL+'?x=1',
                    'https://official.nba.com.evil.invalid/nba-injury-report-2026-27-season/',
                    PREFIX+'summary?event=1&apiKey=secret'):
            with self.subTest(url=url): self.assertFalse(allowed_url(url))

    def test_invalid_season_is_not_silently_replaced_with_current_year(self):
        for season in ('2025/2027','2026','../../2026','2026/2026'):
            with self.assertRaises(ValueError): season_index(season)

    def test_report_discovery_uses_published_links_and_rejects_future_stale_or_fake_urls(self):
        text=(''.join('<a href="'+u+'">x</a>' for u in [PDF_URL,
            PDF_URL.replace('10_00AM','11_45PM'), PDF_URL.replace('2026-11-16','2026-11-15'),
            PDF_URL.replace('ak-static.cms.nba.com','evil.invalid')])).encode()
        self.assertEqual(latest_report(text,NOW,'2026/2027')['source_url'], PDF_URL)
        self.assertIsNone(latest_report(b'<a href="/made-up.pdf">x</a>',NOW,'2026/2027'))

    def test_summary_requires_exact_id_ordered_team_start_and_season(self):
        for key in ('id','date','season','team','side'):
            d=summary(); c=d['header']['competitions'][0]
            if key=='id': d['header']['id']='401000002'
            elif key=='date': c['date']='2026-11-17T00:10:00Z'
            elif key=='season': d['header']['season']['year']=2026
            elif key=='team': c['competitors'][0]['team']['id']='3'
            else: c['competitors'][0]['homeAway']='away'
            with self.subTest(key=key), self.assertRaises((ValueError,KeyError)): bind_summary(d,self.context,NOW)

    def test_live_completed_and_tipoff_boundary_fail_closed(self):
        for state in ('STATUS_IN_PROGRESS','STATUS_FINAL','STATUS_POSTPONED'):
            d=summary(); d['header']['competitions'][0]['status']['type']['name']=state
            with self.assertRaises(ValueError): bind_summary(d,self.context,NOW)
        with self.assertRaises(ValueError): bind_summary(summary(),self.context,START)

    def test_espn_athlete_active_flag_is_not_used_as_availability(self):
        d=summary(); item=d['injuries'][1]['injuries'][0]; item['athlete']['status']={'name':'Active'}
        rows,n=espn_rows(d,self.teams,NOW)
        self.assertEqual(rows[0]['status'],'Out'); self.assertEqual(n,0)
        self.assertFalse(rows[0]['independent_status_verified'])

    def test_unknown_status_and_future_publication_are_rejected_without_percentages(self):
        for field,value in [('status','Healthy Guess'),('date','2026-11-18T00:00:00Z')]:
            d=summary(); d['injuries'][1]['injuries'][0][field]=value
            rows,n=espn_rows(d,self.teams,NOW); self.assertEqual(rows,[]); self.assertEqual(n,1)

    def test_injury_team_conflict_and_duplicate_group_are_not_merged(self):
        d=summary(); d['injuries'][1]['team']['id']='3'
        with self.assertRaises(ValueError): espn_rows(d,self.teams,NOW)
        d=summary(); d['injuries']=[d['injuries'][1],deepcopy(d['injuries'][1])]
        with self.assertRaises(ValueError): espn_rows(d,self.teams,NOW)

    def test_roster_directory_requires_exact_name_team_and_season(self):
        d=dict(team=dict(id='2',displayName='Test Away'),season=dict(year=2027),
               athletes=[dict(id='22',displayName='Test Player')])
        ids=roster_ids(d,self.teams['away'],'2026/2027'); self.assertEqual(ids,{'testplayer':'22'})
        d['season']['year']=2026
        with self.assertRaises(ValueError): roster_ids(d,self.teams['away'],'2026/2027')

    def test_duplicate_names_and_ids_are_not_guessed(self):
        base=dict(team=dict(id='2',displayName='Test Away'),season=dict(year=2027))
        for athletes in ([dict(id='22',displayName='Test Player'),dict(id='23',displayName='Test Player')],
                         [dict(id='22',displayName='Test Player'),dict(id='22',displayName='Other Player')]):
            self.assertEqual(roster_ids(dict(base,athletes=athletes),self.teams['away'],'2026/2027'),{})

    def test_official_pdf_row_matches_date_pair_and_exact_roster_name_but_is_not_medically_verified(self):
        rows,n=nba_rows(extraction(),self.teams,{'2':{'testplayer':'22'}},self.context,NOW-3600)
        self.assertEqual(n,0); self.assertEqual(rows[0]['player_id'],'22')
        self.assertEqual(rows[0]['source_clock_precision'],'MERIDIEM_NOT_STATED')
        self.assertFalse(rows[0]['independent_status_verified'])

    def test_wrong_pdf_date_time_or_team_cannot_become_a_fixture_status(self):
        for key,value in [('game_date','11/17/2026'),('game_time','08:00(ET)'),
                          ('team','Other Team'),('matchup','HOM@AWY')]:
            e=extraction(); e['rows'][0][key]=value
            rows,_=nba_rows(e,self.teams,{},self.context,NOW-3600)
            self.assertEqual(rows,[])

    def test_missing_id_keeps_pdf_as_unverified_source_observation_not_invented_player(self):
        rows,_=nba_rows(extraction(),self.teams,{},self.context,NOW-3600)
        self.assertIsNone(rows[0]['player_id']); self.assertEqual(rows[0]['identity_status'],'PLAYER_ID_NOT_VERIFIED')


class RosterReviewTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.fake=FixtureSources(); self.context=context_for(snapshot())
        self.service=CurrentRosterReview(Path(self.tmp.name)/'roster', getter=self.fake,
            extractor=lambda path,deadline: extraction(), clock=lambda:self.fake.now)

    def test_current_review_has_two_sources_without_model_adjustment_or_old_input_claim(self):
        before=deepcopy(self.context); r=self.service.review(self.context)
        self.assertEqual(r['status'],'CURRENT_SOURCE_OBSERVATIONS'); self.assertEqual(len(r['records']),2)
        self.assertTrue(r['source_available_after_original_forecast']); self.assertFalse(r['forecast_changed'])
        self.assertFalse(r['model_adjustment_applied']); self.assertFalse(r['lineup_verified'])
        self.assertIsNone(r['confidence_index']); self.assertEqual(self.context,before)
        self.assertEqual(len(self.fake.calls),5)

    def test_same_review_is_cached_without_double_records_or_source_calls(self):
        first=self.service.review(self.context); files={p:p.read_bytes() for p in self.service.directory.iterdir()}
        r=self.service.review(self.context); self.assertEqual(r,first); self.assertEqual(len(self.fake.calls),5)
        self.assertEqual(files,{p:p.read_bytes() for p in self.service.directory.iterdir()})

    def test_after_cache_expiry_new_review_is_append_only(self):
        self.service.review(self.context); files={p:p.read_bytes() for p in self.service.directory.iterdir()}
        self.fake.now+=TTL
        self.service.review(self.context)
        self.assertTrue(all(p.read_bytes()==b for p,b in files.items()))
        self.assertEqual(len(list(self.service.directory.glob('review-*'))),2)

    def test_post_tipoff_performs_no_network_and_no_historical_backfill(self):
        self.fake.now=START; r=self.service.review(self.context)
        self.assertEqual(r['status'],'POST_TIPOFF_NO_CURRENT_BACKFILL'); self.assertEqual(self.fake.calls,[])
        self.assertEqual(r['records'],[])

    def test_tipoff_during_capture_discards_current_statuses(self):
        def late(path,deadline): self.fake.now=START; return extraction()
        self.service.extractor=late
        r=self.service.review(self.context)
        self.assertEqual(r['status'],'TIPOFF_DURING_REVIEW'); self.assertEqual(r['records'],[])

    def test_primary_unavailable_keeps_labelled_espn_observation_and_cooldown(self):
        self.fake.fail.add(season_index('2026/2027')); r=self.service.review(self.context)
        self.assertEqual(len(r['records']),1); self.assertEqual(r['records'][0]['source'],'ESPN')
        self.assertIn('OFFICIAL_REPORT_UNAVAILABLE_OR_UNVERIFIED',r['warnings'])
        self.service.cache.clear(); self.service.review(self.context)
        self.assertEqual(self.fake.calls.count(season_index('2026/2027')),1)

    def test_wrong_fixture_or_source_pin_fails_without_any_claimed_player_status(self):
        for failure in ('fixture','pin'):
            if failure=='fixture': self.fake.document['header']['id']='bad'
            else: self.fake.document=summary(); self.fake.bad_pin=True
            self.service.sources.clear(); r=self.service.review(self.context)
            self.assertEqual(r['status'],'SOURCE_OR_FIXTURE_REVIEW_FAILED'); self.assertEqual(r['records'],[])

    def test_missing_pdf_dependency_does_not_hide_espn_or_claim_nba_verification(self):
        self.service.extractor=lambda path,deadline:dict(status='PDF_DEPENDENCY_MISSING',rows=[])
        r=self.service.review(self.context); text=render_review(r)
        self.assertIn('ayrıştırıcısı kurulu değil',text); self.assertEqual(len(r['records']),1)

    def test_pdf_digest_mismatch_cannot_promote_extracted_rows(self):
        def tamper(path,deadline): return dict(extraction(),source_pdf_sha256='0'*64)
        self.service.extractor=tamper; r=self.service.review(self.context)
        self.assertEqual(len(r['records']),1); self.assertTrue(r['warnings'])

    def test_review_hash_and_original_snapshot_pin_are_recorded(self):
        r=self.service.review(self.context); p=next(self.service.directory.glob('review-*'))
        wrapped=json.loads(p.read_text()); self.assertEqual(digest(wrapped['payload']),wrapped['sha256'])
        self.assertEqual(wrapped['payload']['original_snapshot_sha256'],digest(snapshot()))
        self.assertNotIn('prediction',wrapped['payload'])

    def test_source_conflict_is_visible_and_never_adjudicated_as_high_confidence(self):
        r=self.service.review(self.context); text=render_review(r)
        self.assertIn('Kaynak durumları uyuşmuyor',text); self.assertIn('Oynamayacak',text)
        self.assertIn('Oynaması belirsiz',text); self.assertIn('modele uygulanmadı',text)
        self.assertIn('NOT_CALIBRATED',text); self.assertNotIn('%',text)

    def test_empty_source_list_never_means_no_injuries_or_suspensions(self):
        self.fake.document['injuries']=[]
        self.service.extractor=lambda path,deadline:dict(status='NO_VERIFIED_TABLE_ROWS',rows=[])
        r=self.service.review(self.context); text=render_review(r)
        self.assertIn('Boş liste',text); self.assertIn('ceza yokluğu kanıtı değildir',text)

    def test_suspension_is_only_labelled_when_source_explicitly_states_it(self):
        e=extraction(); e['rows'][0]['reason']='League Suspension'; e['rows_sha256']=digest(e['rows'])
        self.service.extractor=lambda path,deadline:e
        text=render_review(self.service.review(self.context))
        self.assertIn('Kaynakta ceza bildirimi var',text); self.assertIn('bağımsız uygunluk denetimi yapılmadı',text)

    def test_render_escapes_names_notes_and_preserves_source_sha_and_actual_clock(self):
        r=self.service.review(self.context); r['records'][0]['player_name']='<script>&'
        r['records'][0]['note']='<bad>'
        text=render_review(r); self.assertIn('&lt;script&gt;&amp;',text); self.assertIn('&lt;bad&gt;',text)
        self.assertIn('Kaynak SHA:',text); self.assertIn('Erişim:',text); self.assertIn('İlk tahminin girdisi değildir',text)

    def test_expired_cached_roster_pages_and_post_tipoff_are_explicit_archive_views(self):
        e=dict(summary='s',sections=dict(roster='r'),section_pages=dict(roster=['r']),
               roster_review_at_utc=NOW,tipoff_utc=START)
        text,_=page_view(e,'roster',0,now=NOW+300); self.assertIn('eskidi',text)
        text,_=page_view(e,'roster',0,now=START); self.assertIn('arşiv gözlemidir',text)

    def test_busy_collection_does_not_launch_another_request(self):
        self.service.lock.acquire()
        try: self.assertEqual(self.service.review(self.context)['status'],'REVIEW_BUSY')
        finally: self.service.lock.release()
        self.assertEqual(self.fake.calls,[])

    def test_archive_write_error_is_not_silently_promoted_to_valid_review(self):
        with patch('hybrid_engine.current_roster.publish_json',side_effect=OSError('disk synthetic')):
            r=self.service.review(self.context)
        self.assertEqual(r['status'],'SOURCE_OR_FIXTURE_REVIEW_FAILED'); self.assertEqual(r['records'],[])

    def test_native_transport_refuses_arbitrary_url_before_network(self):
        with patch('requests.get',side_effect=AssertionError('No network')) as get:
            with self.assertRaises(ValueError): native_get('https://evil.invalid',deadline=0)
            get.assert_not_called()

    def test_optional_pdf_module_absence_is_explicit_before_spawn(self):
        with patch('importlib.util.find_spec',return_value=None), patch('subprocess.run') as run:
            self.assertEqual(pdf_extract(Path('unused'),deadline=0)['status'],'PDF_DEPENDENCY_MISSING')
            run.assert_not_called()

    def test_pdf_subprocess_receives_no_provider_alias_or_unknown_secret_environment(self):
        with patch.dict(os.environ,{'API_BASKETBALL_KEY':'SYNTHETIC_SECRET','UNEXPECTED_PRIVATE_VALUE':'SYNTHETIC_ONLY'}),\
             patch('importlib.util.find_spec',return_value=object()),\
             patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=b'{"status":"NO_VERIFIED_TABLE_ROWS","rows":[]}')) as run:
            pdf_extract(Path('/tmp/synthetic.pdf'),deadline=time.monotonic()+10)
        env=run.call_args.kwargs['env']
        self.assertNotIn('API_BASKETBALL_KEY',env); self.assertNotIn('UNEXPECTED_PRIVATE_VALUE',env)
        self.assertEqual(env['OPENBLAS_NUM_THREADS'],'1')
