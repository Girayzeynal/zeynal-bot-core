"""Synthetic source contracts and isolated SQLite copies, never production data."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import hashlib
import io
import json
import sqlite3
from contextlib import redirect_stdout

from prediction_ledger import PredictionLedger, PredictionRecord, OutcomeRecord
from season_archive_inventory import archive_catalog, validate_catalog, _hash
from season_ledger_audit import audit_ledger_fixtures
from calibration_safety_gate import evaluate, main

NOW = int(datetime(2026, 11, 11, 16, tzinfo=timezone.utc).timestamp())
START = int(datetime(2026, 10, 25, 23, tzinfo=timezone.utc).timestamp())


def nba(pid='401000123'):
    status = {'type': {'state': 'post', 'completed': True, 'name': 'STATUS_FINAL'}}
    teams = []
    for side, tid, parts in [('home', '1', [25, 30, 30, 30]), ('away', '2', [25, 28, 28, 28])]:
        teams.append(dict(homeAway=side, team={'id': tid}, score=str(sum(parts)),
                          linescores=[{'value': v} for v in parts]))
    return dict(id=pid, date='2026-10-25T23:00:00Z', season={'year': 2027, 'type': 2},
                status=deepcopy(status), competitions=[dict(id=pid, status=status, competitors=teams)])


def euro():
    g = dict(identifier='E2026_1', gameCode=1, season=dict(code='E2026', competitionCode='E', year=2026, alias='2026-27'),
             phaseType={'code': 'RS'}, utcDate='2026-10-25T23:00:00Z', played=True,
             confirmedDate=True, confirmedHour=True, gameStatus='Confirmed')
    for side, team, parts in [('local', 'HOM', [20, 22, 20, 23]), ('road', 'AWY', [19, 20, 20, 21])]:
        g[side] = dict(club={'code': team, 'isVirtual': False}, score=sum(parts),
                       partials={**{f'partials{i+1}': v for i, v in enumerate(parts)}, 'extraPeriods': {}})
    return g


class SourceCatalogTests(TestCase):
    def setUp(self):
        timer = patch('time.time', return_value=NOW)
        timer.start(); self.addCleanup(timer.stop)

    def catalog(self, raw=None, provider='ESPN', **kw):
        options = dict(provider=provider, observed_at_utc=NOW-1, ingested_at_utc=NOW)
        options.update(kw)
        return archive_catalog({'events': [nba()]} if raw is None else raw, **options)

    def test_nba_catalog_retrospective_periods_and_proof_limits(self):
        bundle = self.catalog(); p = validate_catalog(bundle, trusted_sha256=bundle['sha256'])
        self.assertEqual(p['completed_fixtures'], 1)
        self.assertEqual(p['completed_with_periods'], 1)
        self.assertEqual(p['fixtures'][0]['final_scores'], [115, 109])
        self.assertFalse(p['season_archive_complete']); self.assertFalse(p['point_in_time_training_eligible'])
        self.assertEqual(p['source_permission'], 'NOT_ESTABLISHED')
        self.assertEqual(p['prospective_predictions_created'], 0)

    def test_euroleague_catalog_keeps_future_games_separate_from_results(self):
        game = euro(); future = deepcopy(game)
        future.update(identifier='E2026_2', gameCode=2, played=False, utcDate='2027-01-01T18:00:00Z')
        for side in ('local', 'road'): future[side]['score'] = 0
        p = self.catalog({'total': 2, 'data': [game, future]}, 'EUROLEAGUE_LIVE')['payload']
        self.assertEqual(p['independent_fixtures'], 2); self.assertEqual(p['completed_fixtures'], 1)
        self.assertEqual(sum(g['final_scores'] is None for g in p['fixtures']), 1)

    def test_duplicate_and_alias_provider_ids_never_inflate_fixture_count(self):
        a, b = nba(), nba('401000124')
        p = self.catalog({'events': [a, a, b]})['payload']
        self.assertEqual(p['raw_records'], 3); self.assertEqual(p['independent_fixtures'], 1)
        self.assertEqual(p['fixtures'][0]['provider_fixture_ids'], ['401000123', '401000124'])

    def test_conflicting_alias_result_or_same_team_start_is_refused(self):
        for change in ('score', 'team', 'provider_id'):
            a, b = nba(), nba('401000124')
            if change == 'score':
                team = b['competitions'][0]['competitors'][0]
                team['score'] = '116'; team['linescores'][0]['value'] += 1
            elif change == 'team': b['competitions'][0]['competitors'][1]['team']['id'] = '3'
            else: b['id'] = '401000123'; b['competitions'][0]['id'] = '401000123'; b['date'] = '2026-10-26T23:00:00Z'
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'conflict'):
                self.catalog({'events': [a, b]})

    def test_season_phase_and_eurocup_substitution_are_refused(self):
        for key, value in [('year', 2026), ('type', 1), ('type', True)]:
            g = nba(); g['season'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): self.catalog({'events': [g]})
        g = euro(); g['season']['code'] = 'U2026'
        with self.assertRaisesRegex(ValueError, 'euroleague_season_identity'):
            self.catalog({'data': [g], 'total': 1}, 'EUROLEAGUE_LIVE')

    def test_incomplete_page_and_rehashed_derived_scores_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'incomplete_catalog_page'):
            self.catalog({'data': [euro()], 'total': 380}, 'EUROLEAGUE_LIVE')
        bundle = self.catalog(); bundle['payload']['fixtures'][0]['final_scores'][0] += 1
        bundle['sha256'] = _hash(bundle['payload'])
        with self.assertRaisesRegex(ValueError, 'archive_cannot_replay'):
            validate_catalog(bundle, trusted_sha256=bundle['sha256'])
        with self.assertRaisesRegex(ValueError, 'trusted_archive_pin_mismatch'):
            validate_catalog(self.catalog(), trusted_sha256='0'*64)

    def test_source_clocks_and_timezone_are_not_backfilled(self):
        for kw in [dict(observed_at_utc=NOW+1), dict(ingested_at_utc=NOW+1), dict(observed_at_utc=True)]:
            with self.subTest(kw=kw), self.assertRaises(ValueError): self.catalog(**kw)
        g = nba(); g['date'] = '2026-10-25T23:00:00'
        with self.assertRaisesRegex(ValueError, 'explicit_utc_required'): self.catalog({'events': [g]})

    def test_overtime_tie_and_quarter_arithmetic_are_checked(self):
        g = nba(); h, a = g['competitions'][0]['competitors']
        h['linescores'] = [{'value': 25} for _ in range(4)] + [{'value': 12}]; h['score'] = '112'
        a['linescores'] = [{'value': 25} for _ in range(4)] + [{'value': 9}]; a['score'] = '109'
        p = self.catalog({'events': [g]})['payload']['fixtures'][0]
        self.assertEqual(sum(p['periods']['home'][:4]), 100); self.assertEqual(p['final_scores'], [112, 109])
        h['linescores'][0]['value'] = 26; h['score'] = '113'
        with self.assertRaisesRegex(ValueError, 'overtime_without_preceding_tie'): self.catalog({'events': [g]})

    def test_false_final_or_conflicting_status_or_bad_period_is_refused(self):
        for kind in ('status', 'quarter', 'played'):
            g = nba()
            if kind == 'status': g['status']['type']['completed'] = False
            elif kind == 'quarter': g['competitions'][0]['competitors'][0]['linescores'][0]['value'] = True
            else: g['competitions'][0]['status']['type']['state'] = 'in'; g['status']['type']['state'] = 'in'
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.catalog({'events': [g]})

    def test_missing_periods_are_reported_without_inventing_quarters(self):
        g = nba()
        for team in g['competitions'][0]['competitors']: del team['linescores']
        p = self.catalog({'events': [g]})['payload']
        self.assertEqual(p['completed_fixtures'], 1); self.assertEqual(p['completed_with_periods'], 0)
        self.assertIsNone(p['fixtures'][0]['periods'])

    def test_nonfinal_name_or_conflicting_quarter_display_cannot_pass_as_final(self):
        g = nba(); g['competitions'][0]['status']['type']['name'] = 'STATUS_CANCELED'
        with self.assertRaisesRegex(ValueError, 'explicit_nba_final_required'):
            self.catalog({'events': [g]})
        g = nba(); g['competitions'][0]['competitors'][0]['linescores'][0]['displayValue'] = '99'
        with self.assertRaisesRegex(ValueError, 'contradictory_period_score'):
            self.catalog({'events': [g]})

    def test_european_future_finals_or_broken_period_totals_are_refused(self):
        for kind in ('future', 'quarter'):
            g = euro()
            if kind == 'future': g['utcDate'] = '2027-01-01T18:00:00Z'
            else: g['local']['partials']['partials1'] += 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.catalog({'total': 1, 'data': [g]}, 'EUROLEAGUE_LIVE')


class LedgerFixtureAuditTests(TestCase):
    def setUp(self):
        timer = patch('time.time', return_value=NOW)
        timer.start(); self.addCleanup(timer.stop)
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'ledger ?#.sqlite'
        self.ledger = PredictionLedger(str(self.path))
        self.add_fixture()

    def add_fixture(self, fid='one', pid='401000123', league='NBA', provider='ESPN', actual=(115, 109)):
        self.ledger.record_prediction_version(PredictionRecord(fid, league, START-100, 110, 100, .6))
        self.ledger.record_fixture_start(league, fid, START)
        self.ledger.record_fixture_provenance(league, fid, provider, pid, START)
        self.ledger.record_outcome(OutcomeRecord(fid, league, START+10000, *actual))

    def catalog(self):
        return archive_catalog({'events': [nba(), nba('401000124')]}, provider='ESPN', observed_at_utc=NOW-1, ingested_at_utc=NOW)

    def audit(self, catalog=True, **kw):
        options = {}
        if catalog:
            source = self.catalog(); options.update(catalog=source, trusted_catalog_sha256=source['sha256'])
        options.update(kw)
        return audit_ledger_fixtures(str(self.path), **options)

    def test_two_hundred_versions_remain_one_independent_fixture_and_no_training(self):
        for _ in range(199): self.ledger.record_prediction_version(PredictionRecord('one', 'NBA', START-100, 111, 101, .7))
        before = self.path.read_bytes(); paths = set(Path(self.tmp.name).iterdir())
        r = self.audit()
        self.assertEqual(r['candidate_prediction_versions'], 200)
        self.assertEqual(r['source_matched_independent_fixtures'], 1)
        self.assertEqual(r['verified_prematch_fixtures'], 0); self.assertIsNone(r['metrics'])
        self.assertFalse(r['automatic_model_update_permitted'])
        self.assertEqual(self.path.read_bytes(), before); self.assertEqual(set(Path(self.tmp.name).iterdir()), paths)

    def test_multiple_provider_aliases_for_same_game_do_not_inflate_matched_samples(self):
        self.add_fixture('alias', '401000124')
        r = self.audit()
        self.assertEqual(r['independent_candidate_fixtures'], 2)
        self.assertEqual(r['source_matched_independent_fixtures'], 1)

    def test_conflicting_alias_score_quarantines_the_whole_source_fixture(self):
        self.add_fixture('alias', '401000124', actual=(116, 109))
        r = self.audit()
        self.assertEqual(r['source_matched_independent_fixtures'], 0)
        self.assertEqual(r['exclusions']['source_score_or_scope_conflict'], 1)

    def test_missing_catalog_never_assigns_a_season_or_verified_count(self):
        r = self.audit(False)
        self.assertEqual(r['independent_candidate_fixtures'], 1)
        self.assertIsNone(r['source_matched_independent_fixtures']); self.assertIsNone(r['season_start_year'])
        self.assertEqual(r['season_assignment'], 'UNAVAILABLE_IN_LEDGER')

    def test_euroleague_requires_its_own_provider_not_espn(self):
        self.add_fixture('wrong-euro', '401000125', league='EuroLeague')
        r = self.audit(False, league='EuroLeague')
        self.assertEqual(r['independent_candidate_fixtures'], 0)
        self.assertEqual(r['exclusions']['unsupported_provider_or_identity'], 1)
        source = archive_catalog({'total': 1, 'data': [euro()]}, provider='EUROLEAGUE_LIVE', observed_at_utc=NOW-1, ingested_at_utc=NOW)
        self.add_fixture('correct-euro', 'E2026_1', league='EuroLeague', provider='EUROLEAGUE_LIVE', actual=(85, 80))
        r = audit_ledger_fixtures(str(self.path), 'EuroLeague', catalog=source, trusted_catalog_sha256=source['sha256'])
        self.assertEqual(r['source_matched_independent_fixtures'], 1)

    def test_tipoff_boundary_future_results_invalid_probability_and_scope_are_excluded(self):
        for change, expected in [('tipoff', 'invalid_chronology_or_start'), ('future', 'invalid_chronology_or_start'),
                                 ('probability', 'invalid_score_or_probability'), ('scope', 'scope_mismatch')]:
            with sqlite3.connect(self.path) as db:
                db.execute('UPDATE prediction_versions SET prediction_ts_utc=?,home_win_probability=?,scope=?', (START-100,.6,'FINAL_WITH_OT'))
                db.execute('UPDATE outcomes SET result_ts_utc=?', (START+10000,))
                if change == 'tipoff': db.execute('UPDATE prediction_versions SET prediction_ts_utc=?', (START,))
                if change == 'future': db.execute('UPDATE outcomes SET result_ts_utc=?', (NOW+1,))
                if change == 'probability': db.execute('UPDATE prediction_versions SET home_win_probability=2')
                if change == 'scope': db.execute("UPDATE prediction_versions SET scope='REGULATION_ONLY'")
            r = self.audit()
            with self.subTest(change=change):
                self.assertEqual(r['source_matched_independent_fixtures'], 0)
                self.assertEqual(r['exclusions'][expected], 1)

    def test_regulation_cannot_match_overtime_inclusive_score(self):
        source = self.catalog()
        g = source['payload']['raw']['events'][0]
        for team, extra in zip(g['competitions'][0]['competitors'], (12, 9)):
            team['linescores'] = [{'value': 25}]*4 + [{'value': extra}]; team['score'] = str(100+extra)
        source = archive_catalog({'events': [g]}, provider='ESPN', observed_at_utc=NOW-1, ingested_at_utc=NOW)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE prediction_versions SET scope='REGULATION_ONLY'")
            db.execute("UPDATE outcomes SET scope='REGULATION_ONLY',actual_home=112,actual_away=109")
        r = audit_ledger_fixtures(str(self.path), catalog=source, trusted_catalog_sha256=source['sha256'])
        self.assertEqual(r['source_matched_independent_fixtures'], 0)
        with sqlite3.connect(self.path) as db: db.execute('UPDATE outcomes SET actual_home=100,actual_away=100')
        r = audit_ledger_fixtures(str(self.path), catalog=source, trusted_catalog_sha256=source['sha256'])
        self.assertEqual(r['source_matched_independent_fixtures'], 1)

    def test_missing_malformed_and_missing_column_files_fail_closed(self):
        missing = Path(self.tmp.name)/'not-created.sqlite'
        self.assertEqual(audit_ledger_fixtures(str(missing))['reason'], 'ledger_not_found'); self.assertFalse(missing.exists())
        bad = Path(self.tmp.name)/'bad.sqlite'; bad.write_bytes(b'not sqlite')
        self.assertEqual(audit_ledger_fixtures(str(bad))['status'], 'blocked')
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TABLE fixture_starts'); db.execute('CREATE TABLE fixture_starts (league TEXT,fixture_id TEXT)')
        self.assertEqual(self.audit()['reason'], 'missing_columns')

    def test_production_path_and_symlink_are_never_opened(self):
        link = Path(self.tmp.name)/'alias.sqlite'; link.symlink_to(self.path)
        with patch('sqlite3.connect', side_effect=AssertionError('DO NOT OPEN')):
            self.assertEqual(audit_ledger_fixtures('/data/prediction_ledger.sqlite')['reason'], 'production_path_refused_use_local_snapshot')
            self.assertEqual(audit_ledger_fixtures(str(link))['reason'], 'symlink_ledger_refused')

    def test_active_wal_and_wal_mode_without_sidecars_require_a_safe_snapshot(self):
        writer = sqlite3.connect(self.path)
        try:
            writer.execute('PRAGMA journal_mode=WAL'); writer.execute('BEGIN IMMEDIATE')
            writer.execute('UPDATE predictions SET expected_home=0')
            before = self.path.read_bytes()
            self.assertEqual(self.audit()['reason'], 'static_snapshot_required')
            self.assertEqual(self.path.read_bytes(), before)
            writer.rollback()
            writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            # A main-file-only WAL copy must be refused even without sidecars.
            bare = Path(self.tmp.name)/'bare-wal.sqlite'
            bare.write_bytes(self.path.read_bytes())
            self.assertEqual(audit_ledger_fixtures(str(bare))['reason'], 'static_sqlite_snapshot_required')
        finally:
            writer.close()

    def test_gate_validates_thresholds_and_never_unlocks_from_candidate_counts(self):
        source = self.catalog()
        with patch('calibration_safety_gate.audit_ledger_fixtures', return_value={'status': 'audited', 'source_matched_independent_fixtures': 200}):
            r = evaluate(str(self.path))
        self.assertTrue(r['leagues']['NBA']['candidate_sample_threshold_met'])
        self.assertFalse(r['automatic_model_update_permitted'])
        for value in (True, 2.0, float('nan'), '100', 1):
            with self.subTest(value=value), self.assertRaises(ValueError): evaluate(str(self.path), minimum_fixtures=value)
        for leagues in ((), ('NBA', 'NBA'), ('NBA', 'EuroCup'), 'NBA', ({},)):
            with self.subTest(leagues=leagues), self.assertRaises(ValueError): evaluate(str(self.path), leagues=leagues)

    def test_cli_has_explicit_blocked_status_and_missing_pin_cannot_read_archive(self):
        output = io.StringIO()
        with redirect_stdout(output): code = main([str(self.path)])
        self.assertEqual(code, 1); self.assertFalse(json.loads(output.getvalue())['automatic_model_update_permitted'])
        with redirect_stdout(io.StringIO()): code = main([str(self.path), '--nba-catalog', '/data/raw.json'])
        self.assertEqual(code, 2)

    def test_ambiguous_join_rows_never_multiply_or_authorize_a_sample(self):
        with sqlite3.connect(self.path) as db:
            db.execute('ALTER TABLE outcomes RENAME TO old_outcomes')
            db.execute('CREATE TABLE outcomes AS SELECT * FROM old_outcomes')
            db.execute('INSERT INTO outcomes SELECT * FROM old_outcomes')
        r = self.audit()
        self.assertEqual(r['independent_candidate_fixtures'], 0)
        self.assertEqual(r['exclusions']['missing_or_ambiguous_join'], 1)

    def test_changed_snapshot_hash_returns_no_partial_counts(self):
        from types import SimpleNamespace
        values = [SimpleNamespace(hexdigest=lambda: 'a'*64), SimpleNamespace(hexdigest=lambda: 'b'*64)]
        with patch('season_ledger_audit.hashlib.sha256', side_effect=values):
            result = self.audit(False)
        self.assertEqual(result['reason'], 'ledger_changed_during_audit')
        self.assertIsNone(result['counts']); self.assertIsNone(result['verified_prematch_fixtures'])

    def test_conflicting_provider_id_rows_are_quarantined_without_join_cartesian_product(self):
        self.add_fixture('other', '401000124', actual=(116, 109))
        with sqlite3.connect(self.path) as db:
            db.execute('ALTER TABLE fixture_provenance RENAME TO old_provenance')
            db.execute('CREATE TABLE fixture_provenance AS SELECT * FROM old_provenance')
            db.execute("UPDATE fixture_provenance SET provider_fixture_id='401000123'")
        r = self.audit()
        self.assertEqual(r['conflicting_provider_fixture_ids'], 1)
        self.assertEqual(r['independent_candidate_fixtures'], 0)
        self.assertEqual(r['source_matched_independent_fixtures'], 0)

    def test_cli_reads_replayed_pinned_catalog_and_rejects_wrong_pin(self):
        source = self.catalog(); p = Path(self.tmp.name)/'catalog.json'
        p.write_text(json.dumps(source))
        args = [str(self.path), '--nba-catalog', str(p), '--nba-catalog-sha256', source['sha256']]
        output = io.StringIO()
        with redirect_stdout(output): code = main(args)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['leagues']['NBA']['audit']['source_matched_independent_fixtures'], 1)
        args[-1] = '0'*64
        with redirect_stdout(io.StringIO()): self.assertEqual(main(args), 2)
