"""No invented manual pace or silent numeric coercion at the FAZ13 boundary."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from tests.test_faz13_baseline_contract import FakeStore, FakeBaseline
from faz13_engine import Faz13Engine, PrematchRequest
from core.aggregate_engine import aggregate_baseline


class Faz13MissingPaceTests(unittest.TestCase):
    def engine(self, store=None):
        engine = Faz13Engine("test", "https://example.invalid", baseline_store=store)
        engine.espn = None
        return engine

    def test_missing_or_invalid_summary_pace_fails_with_explicit_reason(self):
        for pace in (None, True, float("nan"), 0, "bad"):
            store = FakeStore({("NBA", "BOS"): FakeBaseline(team="BOS", pace=pace),
                               ("NBA", "NYK"): FakeBaseline(team="NYK")})
            with self.subTest(pace=pace), self.assertRaisesRegex(ValueError, "Tempo verisi"):
                asyncio.run(self.engine(store).run_prematch(
                    PrematchRequest(1, "NBA", "2026-11-01", "BOS", "NYK")))

    def test_manual_missing_pace_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = self.engine()
            engine.project_root = Path(folder)
            root = Path(folder)/"data/baselines/series/NBA"
            root.mkdir(parents=True)
            for team in ("BOS", "NYK"):
                (root/f"{team}.json").write_text(json.dumps(dict(pts_for=110, pts_against=100)))
            self.assertIsNone(engine._load_manual_baseline("NBA", "BOS")["pace"])
            with self.assertRaisesRegex(ValueError, "Tempo verisi"):
                asyncio.run(engine.run_prematch(PrematchRequest(1,"NBA","2026-11-01","BOS","NYK")))

    def test_boolean_summary_score_cannot_turn_into_one_point(self):
        store = FakeStore({("NBA", "BOS"): FakeBaseline(team="BOS", pts_for=True),
                           ("NBA", "NYK"): FakeBaseline(team="NYK")})
        with self.assertRaisesRegex(ValueError, "Güvenilir baseline"):
            asyncio.run(self.engine(store).run_prematch(
                PrematchRequest(1,"NBA","2026-11-01","BOS","NYK")))

    def test_aggregator_rejects_boolean_scores_and_nonstring_source(self):
        base = dict(pts_for=110, pts_against=100, confidence=.8, source="TEST", pace=99)
        for changes in ({"pts_for": True}, {"pts_against": False}, {"confidence": True},
                        {"source": None}, {"source": 42}):
            with self.subTest(changes=changes):
                self.assertIsNone(aggregate_baseline([{**base, **changes}]))
        self.assertIsNone(aggregate_baseline([None, []]))

    def test_manual_nonobject_json_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = self.engine()
            engine.project_root = Path(folder)
            root = Path(folder)/"data/baselines/series/NBA"
            root.mkdir(parents=True)
            (root/"BOS.json").write_text("[]")
            self.assertIsNone(engine._load_manual_baseline("NBA","BOS"))
