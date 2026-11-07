"""Replay, immutable observation time and atomic storage of derived pace evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from prematch_series_audit import audit_prematch_series
from providers.espn_boxscore_pace import METHOD
from providers.espn_pace_evidence import capture_pace_evidence
from test_espn_boxscore_pace import fixture, game
from providers.espn_adapter import ESPNAdapter
from baseline_numeric_reconciliation import reconcile_team_average


def signed(evidence):
    result = deepcopy(evidence)
    serialized = json.dumps(result["snapshot"], sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode()
    result["snapshot_sha256"] = hashlib.sha256(serialized).hexdigest()
    return result


class PaceEvidenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = TeamBaselineStore(self.folder.name)
        payload = fixture()
        self.game = game(payload)
        self.observed = int(time.time()) - 120
        self.evidence = capture_pace_evidence(payload, self.game, observed_at_utc=self.observed)
        self.path = Path(self.store._series_path("NBA", "ORL"))

    def append(self, store=None, **changes):
        values = dict(pts_for=97, pts_against=108, pace=self.evidence["pace"],
                      home=True, ts_utc=self.game["start_ts_utc"],
                      game_id=self.game["provider_fixture_id"], source=METHOD,
                      timestamp_precision="exact", pace_evidence=self.evidence)
        values.update(changes)
        (store or self.store).append_game("NBA", "ORL", **values)

    def test_reopen_replays_source_evidence_without_network(self):
        self.append()
        reloaded = TeamBaselineStore(self.folder.name).get_series("NBA", "ORL", 10)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].pace_evidence, self.evidence)
        self.assertAlmostEqual(reloaded[0].pace, 94.4)

    def test_missing_evidence_cannot_enter_method_tagged_history(self):
        with self.assertRaises(ValueError):
            self.append(pace_evidence=None)
        self.assertFalse(self.path.exists())

    def test_record_numbers_identity_and_source_are_bound_to_snapshot(self):
        for field, value in (("pace", 100), ("home", False), ("pts_for", 98),
                             ("ts_utc", self.game["start_ts_utc"] - 1),
                             ("game_id", "999"), ("source", "other"),
                             ("timestamp_precision", "date_only")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.append(**{field: value})
        self.assertFalse(self.path.exists())

    def test_disk_tampering_rejects_read_and_preserves_file_on_append(self):
        self.append()
        rows = json.loads(self.path.read_text())
        rows[0]["pace_evidence"]["snapshot"]["observed_at_utc"] -= 1
        self.path.write_text(json.dumps(rows))
        corrupt = self.path.read_bytes()
        self.assertEqual(self.store.get_series("NBA", "ORL", 10), [])
        with self.assertRaises(ValueError):
            self.append()
        self.assertEqual(self.path.read_bytes(), corrupt)

    def test_rehashing_does_not_bypass_replay_or_time_checks(self):
        for action in ("counts", "future", "before_game", "version", "scope"):
            with self.subTest(action=action):
                evidence = deepcopy(self.evidence)
                snapshot = evidence["snapshot"]
                if action == "counts":
                    snapshot["summary"]["boxscore"]["teams"][0]["statistics"][0]["displayValue"] = "38-84"
                elif action == "future":
                    snapshot["observed_at_utc"] = int(time.time()) + 86400
                elif action == "before_game":
                    snapshot["observed_at_utc"] = self.game["start_ts_utc"]
                elif action == "version":
                    snapshot["schema_version"] = 2
                else:
                    snapshot["game"]["scope"] = "REGULATION_ONLY"
                with self.assertRaises(ValueError):
                    self.append(pace_evidence=signed(evidence))

    def test_late_fetch_is_excluded_from_point_in_time_selection_and_audit(self):
        self.append()
        for cutoff in (self.observed - 1, self.observed):
            with self.subTest(cutoff=cutoff):
                self.assertEqual(self.store.get_series_before("NBA", "ORL", cutoff, 10), [])
                with self.assertRaisesRegex(ValueError, "Insufficient pre-prediction"):
                    audit_prematch_series(self.store, league="NBA", team="ORL",
                                          prediction_utc=cutoff, min_games=1)
        report = audit_prematch_series(self.store, league="NBA", team="ORL",
                                       prediction_utc=self.observed + 1, min_games=1)
        self.assertEqual(report["eligible_games"], 1)

    def test_later_refetch_does_not_rewrite_first_observation_or_allow_backdating(self):
        self.append()
        original = self.path.read_bytes()
        later = deepcopy(self.evidence)
        later["snapshot"]["observed_at_utc"] += 60
        self.append(pace_evidence=signed(later))
        self.assertEqual(self.path.read_bytes(), original)
        earlier = deepcopy(self.evidence)
        earlier["snapshot"]["observed_at_utc"] -= 60
        with self.assertRaisesRegex(ValueError, "conflicting pace"):
            self.append(pace_evidence=signed(earlier))
        self.assertEqual(self.path.read_bytes(), original)

    def test_numerical_reconciliation_rejects_late_evidence_even_with_correct_means(self):
        self.append()
        # This isolated numerical gate has a six-row minimum. Fixture uniqueness
        # is checked by the separate series audit before canonical persistence.
        rows = self.store.get_series("NBA", "ORL", 10) * 6
        average = SimpleNamespace(points_for=97, points_against=108, pace=self.evidence["pace"])
        with self.assertRaisesRegex(ValueError, "unavailable before prediction"):
            reconcile_team_average(average, rows, prediction_utc=self.observed)

    def test_legacy_record_without_evidence_field_is_not_rewritten(self):
        self.append(source="legacy_provider", pace_evidence=None)
        rows = json.loads(self.path.read_text())
        rows[0].pop("pace_evidence")
        self.path.write_text(json.dumps(rows))
        original = self.path.read_bytes()
        self.assertEqual(len(self.store.get_series("NBA", "ORL", 10)), 1)
        self.assertEqual(self.path.read_bytes(), original)

    def test_atomic_replace_failure_cannot_partially_write_observation(self):
        with patch("baseline.team_baseline_store.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.append()
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob(".baseline-*.tmp")), [])


class PaceEvidenceBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_retains_evidence_returned_by_real_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            adapter = ESPNAdapter(allow_estimated_pace=True)
            adapter.resolve_team = AsyncMock(return_value={"id": "19", "abbr": "ORL"})
            adapter.fetch_completed_nba_events = AsyncMock(return_value=[game(fixture())])
            adapter._get_json = AsyncMock(return_value=fixture())
            await TeamBaselineBootstrapper(store, [adapter]).ensure_async("NBA", "ORL", min_games=1)
            rows = TeamBaselineStore(directory).get_series("NBA", "ORL", 10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].pace_evidence["snapshot"]["game"]["provider_fixture_id"], "401909903")
            self.assertEqual(rows[0].pace_evidence["method"], METHOD)


if __name__ == "__main__":
    unittest.main()
