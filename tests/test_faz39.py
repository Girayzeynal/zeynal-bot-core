"""All positive captures here are synthetic; no claimed real NBA performance."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import threading
import unittest
from unittest.mock import AsyncMock, patch

import faz39
from faz25 import exclusive
from faz34 import cut_proofs
from faz37 import ClockGuard, ClockDiscontinuity
from prediction_inputs import digest
from tests import test_faz33 as fixtures


def proof(body, url, observed):
    text = body if isinstance(body, str) else json.dumps(body)
    return dict(source_url=url, body=text, response_sha256=hashlib.sha256(text.encode()).hexdigest(),
                http_status=200, request_started_utc=observed - .1, observed_utc=observed,
                elapsed_seconds=.1)


def utc_proof(now):
    return proof(dict(dateTime=datetime.fromtimestamp(now, timezone.utc).isoformat(), timeZone='UTC'),
                 faz39.UTC_URL, now)


def synthetic_ready(fx, *, cut=None, horizon='T24H'):
    cut = fixtures.BASE if cut is None else cut
    raw = fixtures.event(cut + faz39.HORIZONS[horizon])
    target = fixtures.parse_scheduled(raw, fx.store.team_ids)
    source = dict(branch='feature/faz39-synthetic-test', sha='a' * 40)
    observed = cut - 8
    directory = dict(sports=[dict(leagues=[dict(teams=[dict(team=dict(id=k, abbreviation=v['abbr'],
        displayName=v['name'])) for k, v in fx.runner.directory.items()])])])
    day = datetime.fromtimestamp(target['start_ts_utc'], faz39.ZoneInfo('America/New_York')).date()
    game = dict(gameId='0022600999', gameStatus=1, seasonYear='2026-27', seasonType='Regular Season',
        gameTimeUtc=datetime.fromtimestamp(target['start_ts_utc'], timezone.utc).isoformat(),
        homeTeam=dict(teamTricode=fx.runner.directory[target['home_team_id']]['abbr']),
        awayTeam=dict(teamTricode=fx.runner.directory[target['away_team_id']]['abbr']))
    html = '<script id="__NEXT_DATA__">' + json.dumps(dict(props=dict(pageProps=dict(games=[game])))) + '</script>'
    run = dict(id=123, run_number=1, head_sha=source['sha'], head_branch=source['branch'],
        path='.github/workflows/python-tests.yml', event='push', status='completed', conclusion='success')
    proofs = dict(
        directory=proof(directory, faz39.ESPN_BASE + '/teams', observed),
        schedule=proof(dict(header=raw), faz39.ESPN_BASE + '/summary?event=' + target['provider_fixture_id'], observed),
        official=proof(html, 'https://www.nba.com/games?date=' + day.isoformat(), observed),
        ref=proof(dict(object=dict(sha=source['sha'])), faz39.GITHUB + '/git/ref/heads/' + source['branch'], observed),
        runs=proof(dict(workflow_runs=[run]), faz39.GITHUB + '/actions/runs?head_sha=' + source['sha'] + '&per_page=100', observed),
        jobs=proof(dict(jobs=[dict(name=k, head_sha=source['sha'], run_id=123, status='completed', conclusion='success')
            for k in ('unit-tests', 'docker-build')]), faz39.GITHUB + '/actions/runs/123/jobs?per_page=100', observed),
        utc=utc_proof(observed))
    rows = fx.store.select(cut - 7, 'PROSPECTIVE', 2027)
    return dict(schema_version=1, mode='SYNTHETIC_TEST', config_sha256='0' * 64,
        source=source, fixture=target, horizon=horizon, ready_utc=cut - 7, proofs=proofs,
        directory=deepcopy(fx.runner.directory), team_ids=sorted(fx.store.team_ids),
        history_rows=rows, history_sha256=digest(rows))


def replace_json(p, key, change):
    old = p['proofs'][key]; body = json.loads(old['body']); change(body)
    p['proofs'][key] = proof(body, old['source_url'], old['observed_utc'])


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx = fixtures.CutTests(); await self.fx.asyncSetUp()
        self.addCleanup(self.fx.folder.cleanup); self.addCleanup(self.fx.time_patch.stop)
        self.addCleanup(self.fx.sleep_patch.stop); self.fx._cleanups.clear()
        self.p = synthetic_ready(self.fx)
        self.fx.clock.now = fixtures.BASE - 6
        self.store = faz39.ReadyStore(self.fx.ledger)

    def gate(self, ready=None):
        p = ready or self.p
        guard = ClockGuard(wall=self.fx.clock.time, monotonic=lambda: self.fx.clock.now + 100000)
        return faz39.CaptureGate(p, digest(p), utc_proof(self.fx.clock.now),
                                lambda: p['source'], clock_guard=guard)

    def runner(self):
        self.store.put(self.p)
        gate = self.gate()
        ledger = faz39.EvidenceLedger(self.fx.ledger.path, 'SYNTHETIC_TEST', gate)
        return faz39.ArmedRunner(ledger, gate)

    def assert_no_cut(self, ledger=None):
        ledger = ledger or self.fx.ledger
        with ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM faz33_cuts').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM faz33_fixtures').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    async def test_ready_is_immutable_and_duplicate_put_is_idempotent(self):
        sha = self.store.put(self.p); self.assertEqual(self.store.put(self.p), sha)
        self.assertEqual(self.store.get(sha), self.p)
        with self.fx.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM faz39_ready').fetchone()[0], 1)
            for sql in ('DELETE FROM faz39_ready', "UPDATE faz39_ready SET payload='{}'",
                        "INSERT OR REPLACE INTO faz39_ready SELECT * FROM faz39_ready"):
                with self.assertRaises(sqlite3.IntegrityError): db.execute(sql)
        self.assert_no_cut()

    async def test_complete_network_free_atomic_capture_audits_as_synthetic(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        with patch.object(faz39.PublicSources, 'fetch', new_callable=AsyncMock) as network:
            result = await faz39.capture_armed(runner)
        network.assert_not_awaited()
        self.assertEqual(result['status'], 'RECORDED')
        self.assertEqual(result['new_prospective_cuts'], 0)
        self.assertEqual(result['new_synthetic_cuts'], 1)
        p = self.fx.packet()
        self.assertEqual(p['faz39']['receipt_sha256'], digest(self.p))
        self.assertEqual(p['shadow']['status'], 'NO_MODEL_AVAILABLE')
        self.assertEqual([s['stage'] for s in p['reference']['bundle']['stages']], ['FAZ13', 'FAZ22', 'FAZ23'])
        self.assertIn('multilayer', p['reference']['bundle'])
        audited = faz39.audit(self.fx.ledger.path)
        self.assertEqual(audited['faz39_bound_cuts'], 1)
        self.assertEqual(audited['prospective_cuts'], 0)
        before = cut_proofs(self.fx.ledger.path); after = await faz39.capture_armed(runner)
        self.assertEqual(after['status'], 'ALREADY_RECORDED')
        self.assertEqual(cut_proofs(self.fx.ledger.path), before)

    async def test_early_capture_never_generates_or_inserts(self):
        runner = self.runner()
        with patch.object(runner, 'capture', new_callable=AsyncMock) as generate:
            result = await faz39.capture_armed(runner)
        generate.assert_not_awaited(); self.assertEqual(result['reason'], 'WAITING_FOR_CUT')
        self.assert_no_cut()

    async def test_host_clock_at_boundary_is_insufficient_until_trusted_utc_lower_bound(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE
        result = await faz39.capture_armed(runner)
        self.assertEqual(result['reason'], 'WAITING_FOR_CUT'); self.assert_no_cut()
        self.fx.clock.now = fixtures.BASE + 3
        self.assertEqual((await faz39.capture_armed(runner))['status'], 'RECORDED')

    async def test_expired_cut_never_generates(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 300.001
        with patch.object(runner, 'capture', new_callable=AsyncMock) as generate:
            result = await faz39.capture_armed(runner)
        generate.assert_not_awaited(); self.assertEqual(result['reason'], 'MISSED_CUT'); self.assert_no_cut()

    async def test_faz38_200444_to_200512_delay_is_rechecked_after_local_checks(self):
        cut = int(datetime(2026, 11, 5, 20, tzinfo=timezone.utc).timestamp())
        p = synthetic_ready(self.fx, cut=cut, horizon='T6H')
        self.fx.clock.now = cut - 6; gate = self.gate(p)
        self.fx.clock.now = cut + 284  # 20:04:44 UTC, still inside the cut window.
        def delayed_source_check():
            self.fx.clock.now += 28  # 20:05:12 UTC, after the deadline.
            return p['source']
        gate.source_check = delayed_source_check
        with self.assertRaisesRegex(faz39.Refused, 'MISSED_CUT'): gate.check()
        self.assertEqual(self.fx.clock.now, cut + 312)
        self.assert_no_cut()

    async def test_validation_crossing_deadline_rolls_back_fixture_and_prediction(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        await faz39.capture_armed(runner); packet = self.fx.packet()
        target = faz39.EvidenceLedger(self.fx.root/'empty.sqlite', 'SYNTHETIC_TEST', runner.gate)
        from prospective_cuts import validate_packet
        def delayed(*args):
            validate_packet(*args); self.fx.clock.now = fixtures.BASE + 301
        with patch('prospective_cuts.validate_packet', side_effect=delayed):
            with self.assertRaisesRegex(faz39.Refused, 'MISSED_CUT'): target.insert(packet)
        self.assert_no_cut(target)

    async def test_sqlite_trigger_rechecks_after_parameter_serialization_delay(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        await faz39.capture_armed(runner); packet = self.fx.packet()
        target = faz39.EvidenceLedger(self.fx.root/'serialization.sqlite', 'SYNTHETIC_TEST', runner.gate)
        from prediction_inputs import canonical_json
        def delayed(value):
            raw = canonical_json(value)
            self.fx.clock.now = fixtures.BASE + 301
            return raw
        with patch('prospective_cuts.canonical_json', side_effect=delayed):
            with self.assertRaisesRegex(faz39.Refused, 'MISSED_CUT'): target.insert(packet)
        self.assert_no_cut(target)

    async def test_sqlite_trigger_refuses_even_in_window_stale_recorded_second(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        await faz39.capture_armed(runner); packet = self.fx.packet()
        target = faz39.EvidenceLedger(self.fx.root/'recorded-second.sqlite', 'SYNTHETIC_TEST', runner.gate)
        from prediction_inputs import canonical_json
        def delayed(value):
            raw = canonical_json(value); self.fx.clock.now += 1
            return raw
        with patch('prospective_cuts.canonical_json', side_effect=delayed):
            with self.assertRaisesRegex(faz39.Refused, 'RECORDING_SECOND_CHANGED'): target.insert(packet)
        self.assert_no_cut(target)

    async def test_clock_discontinuity_and_changed_sha_fail_closed(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        runner.gate.guard.monotonic = lambda: 0
        result = await faz39.capture_armed(runner)
        self.assertIn('CLOCK_DISCONTINUITY', result['reason']); self.assert_no_cut()
        self.fx.clock.now = fixtures.BASE - 6
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        runner.gate.source_check = lambda: dict(self.p['source'], sha='b'*40)
        result = await faz39.capture_armed(runner)
        self.assertIn('SOURCE_CHANGED', result['reason']); self.assert_no_cut()

    async def test_readiness_mutation_after_arming_is_refused(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        runner.gate.ready['source']['sha'] = 'b'*40
        result = await faz39.capture_armed(runner)
        self.assertEqual(result['reason'], 'READINESS_CHANGED_AFTER_ARM'); self.assert_no_cut()

    async def test_same_database_busy_lock_does_not_generate(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        with exclusive(self.fx.ledger.path):
            result = await faz39.capture_armed(runner)
        self.assertEqual(result['status'], 'BUSY'); self.assert_no_cut()

    async def test_concurrent_runners_produce_exactly_one_immutable_cut(self):
        a = self.runner(); b = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        results = await asyncio.gather(faz39.capture_armed(a), faz39.capture_armed(b))
        self.assertEqual(sum(x.get('new_synthetic_cuts', 0) for x in results), 1)
        self.assertEqual(len(cut_proofs(self.fx.ledger.path)), 1)
        self.assertEqual(faz39.audit(self.fx.ledger.path)['faz39_bound_cuts'], 1)

    async def test_parallel_thread_workers_contend_on_the_same_file_lock(self):
        a = self.runner(); b = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        entered, release = threading.Event(), threading.Event()
        original = a.recheck
        async def blocked(fixture):
            entered.set()
            self.assertTrue(release.wait(3))
            return await original(fixture)
        a.recheck = blocked
        completed = []
        worker = threading.Thread(target=lambda: completed.append(asyncio.run(faz39.capture_armed(a))))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            result = await faz39.capture_armed(b)
            self.assertEqual(result['status'], 'BUSY')
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        result = completed[0]
        self.assertEqual(result['new_synthetic_cuts'], 1)
        self.assertEqual(len(cut_proofs(self.fx.ledger.path)), 1)

    async def test_sqlite_writer_lock_refuses_without_partial_cut(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        with self.fx.ledger.connect() as locked:
            locked.execute('BEGIN IMMEDIATE')
            result = await faz39.capture_armed(runner)
        self.assertEqual(result['status'], 'REFUSED'); self.assertIn('locked', result['reason'])
        self.assert_no_cut()

    async def test_packet_for_different_target_is_rejected(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        await faz39.capture_armed(runner); p = self.fx.packet(); p['horizon'] = 'T6H'
        with self.assertRaisesRegex(faz39.Refused, 'UNARMED_TARGET'): runner.ledger.insert(p)

    async def test_late_arm_at_200444_does_no_network_or_generation(self):
        self.p['config_sha256'] = digest(self.config())
        sha = self.store.put(self.p); self.fx.clock.now = fixtures.BASE + 284
        client = AsyncMock()
        with patch('faz39.CutLedger', return_value=self.fx.ledger):
            with self.assertRaisesRegex(faz39.Refused, 'ARM_MUST_START_BEFORE_WINDOW'):
                await faz39.arm(self.config(), sha, client)
        client.fetch.assert_not_awaited(); self.assert_no_cut()

    def config(self):
        return dict(schema_version=1, collection=dict(database=self.fx.ledger.path,
            research_database=self.fx.store.path, state_directory=str(self.fx.root), legacy_databases={}),
            storage=dict(mode='LOCAL_ONLY', external_target=None, upload_enabled=False))

    async def test_runtime_aborts_when_utc_precheck_finishes_after_cut(self):
        self.p['config_sha256'] = digest(self.config()); sha = self.store.put(self.p)
        async def late(url):
            self.fx.clock.now = fixtures.BASE + 1
            return utc_proof(self.fx.clock.now)
        client = AsyncMock(); client.fetch.side_effect = late
        with patch('faz39.CutLedger', return_value=self.fx.ledger):
            with self.assertRaisesRegex(faz39.Refused, 'PRECHECKS_NOT_READY_BEFORE_CUT'):
                await faz39.arm(self.config(), sha, client)
        self.assert_no_cut()

    async def test_foreground_arm_waits_and_captures_without_in_window_network(self):
        self.p['config_sha256'] = digest(self.config()); sha = self.store.put(self.p)
        client = AsyncMock(); client.fetch.return_value = utc_proof(self.fx.clock.now)
        guard = ClockGuard(wall=self.fx.clock.time, monotonic=lambda: self.fx.clock.now + 100000)
        with patch('faz39.CutLedger', return_value=self.fx.ledger), \
             patch('faz39.local_source', return_value=self.p['source']), \
             patch('faz39.ClockGuard', return_value=guard):
            result = await faz39.arm(self.config(), sha, client)
            first = cut_proofs(self.fx.ledger.path)
            repeated = await faz39.arm(self.config(), sha, client)
        self.assertEqual(result['status'], 'RECORDED'); self.assertEqual(result['new_synthetic_cuts'], 1)
        self.assertEqual(repeated['status'], 'ALREADY_RECORDED')
        self.assertEqual(first, cut_proofs(self.fx.ledger.path))
        client.fetch.assert_awaited_once_with(faz39.UTC_URL)

    async def test_interruption_inside_transaction_rolls_back_all_rows(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 3
        await faz39.capture_armed(runner); packet = self.fx.packet()
        ledger = faz39.EvidenceLedger(self.fx.root/'interrupt.sqlite', 'SYNTHETIC_TEST', runner.gate)
        checks = 0
        def interrupted():
            nonlocal checks
            checks += 1
            if checks == 2: raise OSError('synthetic process interruption before INSERT')
            return runner.gate.check()
        ledger.clock_check = interrupted
        with self.assertRaisesRegex(OSError, 'interruption'): ledger.insert(packet)
        self.assert_no_cut(ledger)

    async def test_stale_receipt_is_never_refreshed_inside_capture(self):
        runner = self.runner(); self.fx.clock.now = fixtures.BASE + 293
        result = await faz39.capture_armed(runner)
        self.assertIn('EXPIRED', result['reason']); self.assert_no_cut()

    async def test_readiness_rejects_failed_pending_missing_or_wrong_sha_ci(self):
        for name, change in [
            ('ref', lambda d: d['object'].update(sha='b'*40)),
            ('runs', lambda d: d['workflow_runs'][0].update(status='in_progress', conclusion=None)),
            ('runs', lambda d: d['workflow_runs'][0].update(conclusion='failure')),
            ('jobs', lambda d: d['jobs'].pop()),
            ('jobs', lambda d: d['jobs'][0].update(head_sha='b'*40)),
            ('jobs', lambda d: d['jobs'][0].update(conclusion='skipped')),
        ]:
            p = deepcopy(self.p); replace_json(p, name, change)
            with self.subTest(name=name):
                with self.assertRaises(faz39.Refused): self.store.put(p)
        self.assert_no_cut()

    async def test_official_time_status_missing_game_and_response_hash_are_mandatory(self):
        for old, new in [('Regular Season', 'Preseason'), ('"gameStatus": 1', '"gameStatus": 2'),
                         ('"BOS"', '"PHX"'), ('+00:00', '+01:00')]:
            p = deepcopy(self.p); q = p['proofs']['official']
            p['proofs']['official'] = proof(q['body'].replace(old, new), q['source_url'], q['observed_utc'])
            with self.subTest(change=(old, new)):
                with self.assertRaises(faz39.Refused): self.store.put(p)
        p = deepcopy(self.p); p['proofs']['official']['body'] += 'tampered'
        with self.assertRaisesRegex(faz39.Refused, 'SOURCE_HASH'): self.store.put(p)

    async def test_missing_utc_wrong_zone_large_rtt_or_clock_offset_is_rejected(self):
        for change in [lambda p: p['proofs'].pop('utc'),
                       lambda p: replace_json(p, 'utc', lambda d: d.update(timeZone='Europe/Istanbul')),
                       lambda p: p['proofs']['utc'].update(elapsed_seconds=3),
                       lambda p: replace_json(p, 'utc', lambda d: d.update(dateTime='2026-01-01T00:00:00'))]:
            p = deepcopy(self.p); change(p)
            with self.assertRaises((ValueError, KeyError)): self.store.put(p)

    async def test_future_stale_or_late_preparation_cannot_authorize_capture(self):
        for field, value in [('ready_utc', fixtures.BASE + 1), ('ready_utc', fixtures.BASE - 200)]:
            p = deepcopy(self.p); p[field] = value
            with self.assertRaises(faz39.Refused): self.store.put(p)
        p = deepcopy(self.p); p['proofs']['directory']['observed_utc'] = fixtures.BASE + 1
        with self.assertRaises(faz39.Refused): self.store.put(p)

    async def test_frozen_history_requires_real_counts_unique_ids_and_precut_ingestion(self):
        p = deepcopy(self.p); p['history_rows'] = p['history_rows'][:5]; p['history_sha256'] = digest(p['history_rows'])
        with self.assertRaisesRegex(faz39.Refused, 'MIN_6'): self.store.put(p)
        p = deepcopy(self.p); p['history_rows'].append(deepcopy(p['history_rows'][0])); p['history_sha256'] = digest(p['history_rows'])
        with self.assertRaisesRegex(faz39.Refused, 'DUPLICATE'): self.store.put(p)
        p = deepcopy(self.p); row = p['history_rows'][0]; row['payload']['ingested_utc'] = fixtures.BASE
        row['sha256'] = digest(row['payload']); p['history_sha256'] = digest(p['history_rows'])
        with self.assertRaisesRegex(faz39.Refused, 'HISTORY_LEAK'): self.store.put(p)

    async def test_frozen_snapshot_ignores_post_prepare_history_mutation(self):
        runner = self.runner(); expected = deepcopy(runner.store.rows)
        self.p['history_rows'].clear()
        self.assertEqual(runner.store.select(), expected)
        self.fx.clock.now = fixtures.BASE + 3
        self.assertEqual((await faz39.capture_armed(runner))['status'], 'RECORDED')

    async def test_prepare_in_window_stops_before_directory_history_ci_and_model(self):
        self.fx.clock.now = fixtures.BASE + 284; client = AsyncMock()
        client.fetch.return_value = self.p['proofs']['schedule']
        with patch('faz39.local_source', return_value=self.p['source']), \
             patch('faz39.CutLedger', return_value=self.fx.ledger):
            with self.assertRaisesRegex(faz39.Refused, 'PREPARE_OUTSIDE_PREWINDOW'):
                await faz39.prepare(self.config(), self.p['fixture']['provider_fixture_id'], 'T24H', client)
        self.assertEqual(client.fetch.await_count, 1); self.assert_no_cut()


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_403_429_and_timeout_have_explicit_fail_closed_status(self):
        for status in (403, 429):
            response = AsyncMock(); response.status = status
            request = AsyncMock(); request.__aenter__.return_value = response
            client = faz39.PublicSources(); client.session = unittest.mock.Mock()
            client.session.get.return_value = request
            with self.assertRaisesRegex(faz39.Refused, 'HTTP_' + str(status)):
                await client.fetch(faz39.UTC_URL)
        client.session.get.side_effect = asyncio.TimeoutError()
        with self.assertRaisesRegex(faz39.Refused, 'TIMEOUT'): await client.fetch(faz39.UTC_URL)

    async def test_network_failure_does_not_become_an_empty_success(self):
        client = faz39.PublicSources(); client.session = unittest.mock.Mock()
        client.session.get.side_effect = OSError('offline')
        with self.assertRaisesRegex(faz39.Refused, 'NETWORK_UNAVAILABLE'):
            await client.fetch(faz39.UTC_URL)


if __name__ == '__main__':
    unittest.main()
