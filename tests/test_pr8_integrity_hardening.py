"""Regression tests for PR #8 data-integrity hardening."""
import asyncio
import tempfile
import time
import unittest

from baseline.team_baseline_store import TeamBaseline, TeamBaselineBootstrapper, TeamBaselineStore


class EmptyProvider:
    async def fetch_team_recent_games(self, league, team, n_games):
        return []

class DuplicateProvider:
    def __init__(self, game):
        self.game = game

    async def fetch_team_recent_games(self, league, team, n_games):
        return [self.game]


def _append_in_child_process(directory, game_id):
    store = TeamBaselineStore(directory)
    store.append_game(
        "NBA", "BOS", 110 + int(game_id), 100, 98.0, True,
        ts_utc=1700000000 + int(game_id),
        game_id=game_id, source="multiprocess", timestamp_precision="exact",
    )


class IntegrityHardeningTests(unittest.TestCase):
    def test_main_uses_configured_baseline_directory(self):
        import ast
        from pathlib import Path

        main_path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"))
        constructors = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "TeamBaselineStore"
        ]
        self.assertEqual(len(constructors), 1)
        base_dir = next(
            (keyword.value for keyword in constructors[0].keywords
             if keyword.arg == "base_dir"), None
        )
        self.assertIsNotNone(base_dir)
        self.assertIsInstance(base_dir, ast.Call)
        self.assertIsInstance(base_dir.func, ast.Attribute)
        self.assertEqual(base_dir.func.attr, "getenv")
        self.assertEqual(base_dir.args[0].value, "BASELINE_DIR")

    def test_series_lock_releases_after_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            with self.assertRaises(RuntimeError):
                with store._series_write_lock("NBA", "BOS"):
                    raise RuntimeError("injected failure")
            store.append_game(
                "NBA", "BOS", 110, 100, 98.0, True,
                ts_utc=int(time.time()) - 86400,
                game_id="after-failure", source="test",
                timestamp_precision="exact",
            )
            self.assertEqual(len(store.get_series("NBA", "BOS", 10)), 1)

    def test_series_lock_serializes_independent_store_instances(self):
        import threading
        with tempfile.TemporaryDirectory() as directory:
            entered = threading.Event()
            release = threading.Event()
            second_entered = threading.Event()
            failures = []

            def first():
                try:
                    with TeamBaselineStore(directory)._series_write_lock("NBA", "BOS"):
                        entered.set()
                        if not release.wait(5):
                            raise TimeoutError("first lock timed out")
                except Exception as exc:
                    failures.append(exc)

            def second():
                try:
                    if not entered.wait(5):
                        raise TimeoutError("first lock not acquired")
                    with TeamBaselineStore(directory)._series_write_lock("NBA", "BOS"):
                        second_entered.set()
                except Exception as exc:
                    failures.append(exc)

            a = threading.Thread(target=first)
            b = threading.Thread(target=second)
            a.start()
            b.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertFalse(second_entered.wait(0.2))
            finally:
                release.set()
                a.join(5)
                b.join(5)
            self.assertFalse(a.is_alive())
            self.assertFalse(b.is_alive())
            self.assertEqual(failures, [])
            self.assertTrue(second_entered.is_set())

    def test_parallel_writers_preserve_distinct_games(self):
        import threading
        with tempfile.TemporaryDirectory() as directory:
            gate = threading.Barrier(2)
            errors = []

            def write(index):
                try:
                    gate.wait(timeout=5)
                    TeamBaselineStore(directory).append_game(
                        "NBA", "BOS", 110 + index, 100, 98.0, True,
                        ts_utc=int(time.time()) - 86400 + index,
                        game_id=str(index), source="parallel",
                        timestamp_precision="exact",
                    )
                except Exception as exc:
                    errors.append(exc)

            workers = [threading.Thread(target=write, args=(i,)) for i in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)
            self.assertFalse(any(worker.is_alive() for worker in workers))
            self.assertEqual(errors, [])
            records = TeamBaselineStore(directory).get_series("NBA", "BOS", 10)
            self.assertEqual({record.game_id for record in records}, {"0", "1"})

    def test_parallel_duplicate_writers_are_idempotent(self):
        import threading
        with tempfile.TemporaryDirectory() as directory:
            gate = threading.Barrier(2)
            errors = []

            def write():
                try:
                    gate.wait(timeout=5)
                    TeamBaselineStore(directory).append_game(
                        "NBA", "BOS", 110, 100, 98.0, True,
                        ts_utc=1700000000, game_id="shared-game",
                        source="parallel", timestamp_precision="exact",
                    )
                except Exception as exc:
                    errors.append(exc)

            workers = [threading.Thread(target=write) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)
            self.assertFalse(any(worker.is_alive() for worker in workers))
            self.assertEqual(errors, [])
            records = TeamBaselineStore(directory).get_series("NBA", "BOS", 10)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].game_id, "shared-game")

    def test_independent_process_writers_preserve_both_games(self):
        import multiprocessing
        with tempfile.TemporaryDirectory() as directory:
            ctx = multiprocessing.get_context("spawn")
            workers = [
                ctx.Process(target=_append_in_child_process, args=(directory, str(i)))
                for i in range(2)
            ]
            for worker in workers:
                worker.start()
            try:
                for worker in workers:
                    worker.join(timeout=15)
                self.assertTrue(all(worker.exitcode == 0 for worker in workers))
                records = TeamBaselineStore(directory).get_series("NBA", "BOS", 10)
                self.assertEqual({record.game_id for record in records}, {"0", "1"})
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(timeout=5)

    def test_anonymous_same_timestamp_distinct_games_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400
            store.append_game("NBA", "BOS", 110, 100, 98.0, True, ts_utc=ts)
            store.append_game("NBA", "BOS", 111, 100, 98.0, True, ts_utc=ts)
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 2)
            store.append_game("NBA", "BOS", 110, 100, 98.0, True, ts_utc=ts)
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 2)

    def test_anonymous_records_from_distinct_sources_are_not_collapsed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400
            for source in ("provider_a", "provider_b"):
                store.append_game(
                    "NBA", "BOS", 110, 100, 98.0, True,
                    ts_utc=ts, source=source, timestamp_precision="date_only",
                )
            records = store.get_series("NBA", "BOS", 20)
            self.assertEqual(len(records), 2)
            self.assertEqual({record.source for record in records},
                             {"provider_a", "provider_b"})

    def test_conflicting_provider_identity_preserves_original_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400
            kwargs = {"ts_utc": ts, "game_id": "same-game",
                      "source": "verified", "timestamp_precision": "exact"}
            store.append_game("NBA", "BOS", 110, 100, 98.0, True, **kwargs)
            with self.assertRaises(ValueError):
                store.append_game("NBA", "BOS", 120, 100, 98.0, True, **kwargs)
            records = store.get_series("NBA", "BOS", 20)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].pts_for, 110)

    def test_cross_provider_duplicate_must_not_inflate_baseline(self):
        # Known safety gap: identical observations from different providers
        # are retained, but cannot count as two independently verified games.
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(5):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i, game_id=str(i),
                                  source="provider_a", timestamp_precision="exact")
            store.append_game("NBA", "BOS", 104, 95, 98.0, True,
                              ts_utc=ts + 4, game_id="other-provider-id",
                              source="provider_b", timestamp_precision="exact")
            self.assertIsNone(
                store.compute_baseline_before(
                    "NBA", "BOS", ts + 86400, n_games=6, min_games=6
                )
            )

    def test_cross_provider_duplicate_blocks_dynamic_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(5):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i, game_id=str(i),
                                  source="provider_a", timestamp_precision="exact")
            store.append_game("NBA", "BOS", 104, 95, 98.0, True,
                              ts_utc=ts + 4, game_id="another-id",
                              source="provider_b", timestamp_precision="exact")
            self.assertIsNone(store.compute_dynamic_baseline("NBA", "BOS", 6))
            quality = store.prefixture_quality_status(
                "NBA", "BOS", ts + 86400, n_games=6, min_games=6
            )
            self.assertEqual(quality["status"], "ambiguous_cross_provider")

    def test_distinct_exact_games_with_different_times_are_not_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(6):
                store.append_game(
                    "NBA", "BOS", 110, 100, 98.0, True,
                    ts_utc=ts + i * 3600, game_id=str(i),
                    source="provider_a" if i % 2 == 0 else "provider_b",
                    timestamp_precision="exact",
                )
            quality = store.prefixture_quality_status(
                "NBA", "BOS", ts + 86400, n_games=6, min_games=6
            )
            self.assertEqual(quality["status"], "ready")
            self.assertIsNotNone(store.compute_dynamic_baseline("NBA", "BOS", 6))

    def test_duplicate_provider_does_not_restamp_stale_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            game = {"pts_for": 110, "pts_against": 100, "pace": 98.0,
                    "home": True, "ts_utc": ts, "game_id": "000001",
                    "source": "test", "timestamp_precision": "exact"}
            store.append_game("NBA", "BOS", 110, 100, 98.0, True,
                              ts_utc=ts, game_id="000001", source="test",
                              timestamp_precision="exact")
            for i in range(1, 6):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i)
            old_ts = int(time.time()) - 86400 * 9
            store.put(TeamBaseline("NBA", "BOS", 6, 102.5, 95.0, 98.0, 0.0, old_ts))
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [DuplicateProvider(game)]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get("NBA", "BOS").updated_ts, old_ts)

    def test_recent_cache_does_not_skip_provider_check(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(6):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i)
            cached_ts = int(time.time()) - 3600
            store.put(TeamBaseline("NBA", "BOS", 6, 102.5, 95.0, 98.0, 0.0, cached_ts))
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [EmptyProvider()]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get("NBA", "BOS").updated_ts, cached_ts)

    def test_newer_game_refreshes_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(6):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i)
            old_ts = int(time.time()) - 86400 * 9
            store.put(TeamBaseline("NBA", "BOS", 6, 102.5, 95.0, 98.0, 0.0, old_ts))
            game = {"pts_for": 120, "pts_against": 105, "pace": 99.0,
                    "home": True, "ts_utc": ts + 86400, "game_id": "000002",
                    "source": "test", "timestamp_precision": "exact"}
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [DuplicateProvider(game)]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNotNone(result)
            self.assertEqual(result.n_games, 6)
            self.assertGreater(result.updated_ts, old_ts)
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 7)

    def test_undersampled_newer_game_does_not_publish_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(4):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0,
                                  True, ts_utc=ts + i)
            game = {"pts_for": 120, "pts_against": 105, "pace": 99.0,
                    "home": True, "ts_utc": ts + 86400, "game_id": "000003",
                    "source": "test", "timestamp_precision": "exact"}
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [DuplicateProvider(game)]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertIsNone(store.get("NBA", "BOS"))
            self.assertEqual(len(store.get_series("NBA", "BOS", 20)), 5)

    def test_missing_measured_pace_does_not_publish_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            game = {"pts_for": 120, "pts_against": 105, "pace": None,
                    "home": True, "ts_utc": ts, "game_id": "000004",
                    "source": "nba_com", "timestamp_precision": "date_only"}
            result = asyncio.run(TeamBaselineBootstrapper(
                store, [DuplicateProvider(game)]
            ).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get_series("NBA", "BOS", 20), [])
            self.assertIsNone(store.get("NBA", "BOS"))

    def test_empty_provider_does_not_restamp_stale_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            ts = int(time.time()) - 86400 * 10
            for i in range(6):
                store.append_game("NBA", "BOS", 100 + i, 95, 98.0, True, ts_utc=ts + i)
            old_ts = int(time.time()) - 86400 * 9
            store.put(TeamBaseline("NBA", "BOS", 6, 102.5, 95.0, 98.0, 0.0, old_ts))
            result = asyncio.run(TeamBaselineBootstrapper(store, [EmptyProvider()]).ensure_async("NBA", "BOS", min_games=6))
            self.assertIsNone(result)
            self.assertEqual(store.get("NBA", "BOS").updated_ts, old_ts)


if __name__ == "__main__":
    unittest.main()
