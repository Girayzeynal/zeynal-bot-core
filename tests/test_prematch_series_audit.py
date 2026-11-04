import unittest
from types import SimpleNamespace

from prematch_series_audit import audit_prematch_series


def game(i, *, ts=None, source="ESPN", precision="exact", game_id=None):
    return SimpleNamespace(
        ts_utc=i if ts is None else ts,
        source=source, timestamp_precision=precision,
        game_id=str(i) if game_id is None else game_id,
    )


class Store:
    def __init__(self, records):
        self.records = records

    def get_series(self, league, team, n_games):
        return self.records

    @staticmethod
    def _ambiguous_cross_provider_games(records):
        return False


class PrematchSeriesAuditTests(unittest.TestCase):
    def test_six_exact_games_before_prediction_pass(self):
        result = audit_prematch_series(
            Store([game(i) for i in range(1, 7)]),
            league="NBA", team="ABC", prediction_utc=10)
        self.assertEqual(result["eligible_games"], 6)
        self.assertEqual(result["latest_game_ts_utc"], 6)

    def test_future_games_do_not_count(self):
        with self.assertRaises(ValueError):
            audit_prematch_series(
                Store([game(i) for i in range(5, 11)]),
                league="NBA", team="ABC", prediction_utc=10)

    def test_date_only_games_do_not_count(self):
        with self.assertRaises(ValueError):
            audit_prematch_series(
                Store([game(i, precision="date_only") for i in range(1, 7)]),
                league="NBA", team="ABC", prediction_utc=10)

    def test_missing_provider_id_does_not_count(self):
        with self.assertRaises(ValueError):
            audit_prematch_series(
                Store([game(i, game_id="") for i in range(1, 7)]),
                league="NBA", team="ABC", prediction_utc=10)

    def test_duplicate_identity_rejected(self):
        rows = [game(i) for i in range(1, 7)]
        rows[-1].game_id = rows[0].game_id
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit_prematch_series(
                Store(rows), league="NBA", team="ABC", prediction_utc=10)

    def test_manual_records_do_not_count(self):
        with self.assertRaises(ValueError):
            audit_prematch_series(
                Store([game(i, source="MANUAL_BASELINE") for i in range(1, 7)]),
                league="NBA", team="ABC", prediction_utc=10)

    def test_same_start_with_distinct_provider_ids_rejected(self):
        rows = [game(i) for i in range(1,7)]
        rows[-1].ts_utc = rows[0].ts_utc
        with self.assertRaisesRegex(ValueError, "same-team fixture start"):
            audit_prematch_series(Store(rows), league="NBA", team="ABC", prediction_utc=10)

    def test_cross_provider_start_collision_does_not_need_store_checker(self):
        class PlainStore:
            def get_series(self, league, team, n_games):
                return rows
        rows = [game(i) for i in range(1,7)]
        rows[-1].source = "OTHER_LEGACY_SOURCE"
        rows[-1].ts_utc = rows[0].ts_utc
        with self.assertRaisesRegex(ValueError, "same-team fixture start"):
            audit_prematch_series(PlainStore(), league="NBA", team="ABC", prediction_utc=10)

    def test_ineligible_future_start_does_not_inflate_count(self):
        rows = [game(i) for i in range(1,7)] + [game(7, ts=10), game(8, ts=10)]
        report = audit_prematch_series(Store(rows), league="NBA", team="ABC", prediction_utc=10)
        self.assertEqual(report["eligible_games"], 6)


if __name__ == "__main__":
    unittest.main()
