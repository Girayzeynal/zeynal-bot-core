"""Real source fixtures plus explicitly synthetic season/history/clock contract cases."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import time
from uuid import uuid5, NAMESPACE_URL
import unittest
from unittest.mock import AsyncMock, patch

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from faz13_engine import Faz13Engine, PrematchRequest
from prematch_series_audit import audit_prematch_series
from providers.euroleague_live import EuroleagueLiveAdapter, PACE_METHOD, audit_catalog, estimate_pace
from test_euroleague_live import source


def observation(league="EUROLEAGUE", *, year=2026, code=None, observed=None):
    fixture = source(league)
    raw, stats = fixture["game"], fixture["stats"]
    prefix, name = ("E", "EuroLeague") if league == "EUROLEAGUE" else ("U", "EuroCup")
    original_code = raw["gameCode"]
    code = original_code if code is None else code
    # Mutated cases are synthetic, never reported as live historical games.
    if year != 2026 or code != original_code:
        raw.update(gameCode=code, identifier=f"{prefix}{year}_{code}",
                   id=str(uuid5(NAMESPACE_URL, f"synthetic-euro:{league}:{year}:{code}")))
        date = datetime.fromisoformat(raw["utcDate"].replace("Z", "+00:00")).replace(year=year)
        raw["utcDate"] = (date + timedelta(days=code-original_code)).isoformat()
        seasons = [raw["season"]] + [row["player"]["season"]
                   for side in ("local", "road") for row in stats[side]["players"]]
        for season in seasons:
            season.update(code=f"{prefix}{year}", year=year, name=f"{name} {year}-{str(year+1)[-2:]}",
                          alias=f"{year}-{str(year+1)[-2:]}", startDate=f"{year}-07-01T00:00:00")
    observed = int(time.time())-120 if observed is None else observed
    evidence = estimate_pace(raw, stats, league=league, year=year, observed_at_utc=observed)
    assert evidence is not None
    return fixture, evidence


def values(evidence, home=True):
    game = evidence["game"]
    return dict(pts_for=game["actual_home"] if home else game["actual_away"],
                pts_against=game["actual_away"] if home else game["actual_home"],
                home=home, pace=evidence["pace"], ts_utc=game["start_ts_utc"],
                game_id=game["provider_fixture_id"], source=PACE_METHOD,
                timestamp_precision="exact", pace_evidence=evidence)


class EuroBaselineBindingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = TeamBaselineStore(self.folder.name)
        _, self.evidence = observation()
        self.path = Path(self.store._series_path("EUROLEAGUE", "RED"))

    def append(self, *, evidence=None, league="EUROLEAGUE", team="RED", **changes):
        data = values(self.evidence if evidence is None else evidence)
        data.update(changes)
        self.store.append_game(league, team, **data)

    def test_real_euroleague_and_eurocup_observations_reopen_and_replay(self):
        for league, team in (("EUROLEAGUE", "RED"), ("EUROCUP", "KLA")):
            _, evidence = observation(league)
            self.append(evidence=evidence, league=league, team=team)
            reopened = TeamBaselineStore(self.folder.name).get_series(league, team, 10)
            self.assertEqual(len(reopened), 1)
            self.assertEqual(reopened[0].pace_evidence, evidence)

    def test_cross_league_writes_are_rejected(self):
        for league in ("NBA", "EUROCUP"):
            with self.subTest(league=league), self.assertRaises(ValueError):
                self.append(league=league)

    def test_team_key_and_home_away_orientation_are_bound(self):
        with self.assertRaises(ValueError):
            self.append(team="ZAL")
        with self.assertRaises(ValueError):
            self.append(home=False)
        self.store.append_game("EUROLEAGUE", "ZAL", **values(self.evidence, home=False))
        self.assertEqual(len(self.store.get_series("EUROLEAGUE", "ZAL", 10)), 1)

    def test_missing_evidence_or_altered_record_cannot_enter_store(self):
        for field, changed in (("pace_evidence", None), ("pace", 100), ("pts_for", 78),
                               ("game_id", "E2026_999"), ("ts_utc", 1), ("timestamp_precision", "date_only")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.append(**{field: changed})
        self.assertFalse(self.path.exists())

    def test_different_season_cannot_mix_with_existing_series(self):
        self.append()
        before = self.path.read_bytes()
        _, prior = observation(year=2025)
        with self.assertRaisesRegex(ValueError, "Mixed season"):
            self.append(evidence=prior)
        self.assertEqual(self.path.read_bytes(), before)
        corrupted = json.loads(before)
        corrupted.append(values(prior))
        self.path.write_text(json.dumps(corrupted))
        self.assertEqual(self.store.get_series("EUROLEAGUE", "RED", 20), [])
        self.assertEqual(self.store.series_quality_status("EUROLEAGUE", "RED")["status"], "corrupt")

    def test_unknown_provider_cannot_mix_with_evidence_backed_series(self):
        self.append()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Mixed season/provider"):
            self.append(source="unmapped_other_provider", game_id="other", pace_evidence=None)
        self.assertEqual(self.path.read_bytes(), before)

    def test_playoff_observation_is_not_a_regular_season_baseline(self):
        fixture = source()
        fixture["game"]["phaseType"]["code"] = "PO"
        evidence = estimate_pace(fixture["game"], fixture["stats"], league="EUROLEAGUE",
                                 year=2026, observed_at_utc=int(time.time())-120)
        with self.assertRaises(ValueError):
            self.append(evidence=evidence)

    def test_late_observation_is_excluded_from_historical_cutoff(self):
        self.append()
        observed = self.evidence["observed_at_utc"]
        self.assertEqual(self.store.get_series_before("EUROLEAGUE", "RED", observed, 10), [])
        self.assertEqual(len(self.store.get_series_before("EUROLEAGUE", "RED", observed+1, 10)), 1)
        with self.assertRaisesRegex(ValueError, "Insufficient pre-prediction"):
            audit_prematch_series(self.store, league="EUROLEAGUE", team="RED", prediction_utc=observed, min_games=1)

    def test_repeat_fetch_keeps_first_observation_and_rejects_backdating(self):
        self.append()
        before = self.path.read_bytes()
        _, later = observation(observed=self.evidence["observed_at_utc"]+60)
        self.append(evidence=later)
        self.assertEqual(self.path.read_bytes(), before)
        _, earlier = observation(observed=self.evidence["observed_at_utc"]-60)
        with self.assertRaisesRegex(ValueError, "conflicting pace"):
            self.append(evidence=earlier)

    def test_disk_corruption_blocks_read_and_rewrite(self):
        self.append()
        data = json.loads(self.path.read_text())
        data[0]["pace_evidence"]["snapshot"]["stats"]["local"]["total"]["points"] += 1
        self.path.write_text(json.dumps(data))
        before = self.path.read_bytes()
        self.assertEqual(self.store.get_series("EUROLEAGUE", "RED", 10), [])
        with self.assertRaises(ValueError):
            self.append()
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_atomic_replace_does_not_leave_half_an_observation(self):
        with patch("baseline.team_baseline_store.os.replace", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                self.append()
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob(".baseline-*.tmp")), [])


class EuroBaselineAdapterTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, league="EUROLEAGUE", n=6):
        samples = [observation(league, code=(1+i if league == "EUROLEAGUE" else 12+i)) for i in range(n)]
        fixture = samples[0][0]
        catalog = audit_catalog(fixture["competition"], fixture["season"],
            dict(total=n, data=[row[0]["game"] for row in samples]), league=league, year=2026,
            observed_at_utc=int(time.time()))
        adapter = EuroleagueLiveAdapter(baseline_season_year=2026, allow_estimated_pace=True)
        adapter.fetch_catalog = AsyncMock(return_value=catalog)
        evidence = {e["game"]["provider_fixture_id"]: e for _, e in samples}
        adapter.fetch_pace_evidence = AsyncMock(side_effect=lambda raw, **kwargs: evidence[raw["identifier"]])
        return adapter

    async def test_default_adapter_never_fetches_estimated_baseline(self):
        adapter = EuroleagueLiveAdapter()
        adapter.fetch_catalog = AsyncMock()
        self.assertIsNone(await adapter.fetch_team_recent_games("EUROLEAGUE", "RED", 6))
        adapter.fetch_catalog.assert_not_awaited()
        with self.assertRaises(ValueError):
            EuroleagueLiveAdapter(allow_estimated_pace=True)

    async def test_exact_source_names_resolve_but_guessed_aliases_do_not(self):
        adapter = self.adapter()
        name = source()["game"]["local"]["club"]["name"]
        self.assertEqual(await adapter.resolve_team_abbr("EUROLEAGUE", name), "RED")
        self.assertIsNone(await adapter.resolve_team_abbr("EUROLEAGUE", "invented RED alias"))
        adapter.fetch_catalog.assert_awaited_once()

    async def test_selected_missing_game_rejects_whole_fetch(self):
        adapter = self.adapter()
        original = adapter.fetch_pace_evidence.side_effect
        adapter.fetch_pace_evidence.side_effect = lambda raw, **kwargs: (
            None if raw["gameCode"] == 3 else original(raw, **kwargs))
        self.assertIsNone(await adapter.fetch_team_recent_games("EUROLEAGUE", "RED", 6))
        self.assertEqual(adapter.baseline_diagnostics["fixture_id"], "E2026_3")
        self.assertEqual(adapter.baseline_diagnostics["collected_before_failure"], 2)
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            result = await TeamBaselineBootstrapper(store, [adapter]).ensure_async("EUROLEAGUE", "RED", min_games=6)
            self.assertIsNone(result)
            self.assertEqual(store.get_series("EUROLEAGUE", "RED", 20), [])

    async def test_real_bootstrap_retains_six_observations_and_faz13_input_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            adapter = self.adapter()
            bootstrap = TeamBaselineBootstrapper(store, [adapter])
            for team in ("RED", "ZAL"):
                baseline = await bootstrap.ensure_async("EUROLEAGUE", team, min_games=6)
                self.assertIsNotNone(baseline)
                self.assertEqual(baseline.n_games, 6)
                self.assertEqual(len(TeamBaselineStore(directory).get_series("EUROLEAGUE", team, 10)), 6)
            engine = Faz13Engine("", "https://example.invalid", baseline_store=store)
            engine.espn = None
            output = await engine.run_prematch(PrematchRequest(0, "EUROLEAGUE", "2026-11-10", "RED", "ZAL"))
            self.assertEqual(output.meta["input_snapshot_status"], "CAPTURED")
            self.assertEqual(output.meta["input_snapshot"]["payload"]["league"], "EUROLEAGUE")

    async def test_eurocup_baseline_does_not_unlock_an_uncalibrated_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            baseline = await TeamBaselineBootstrapper(store, [self.adapter("EUROCUP")]).ensure_async(
                "EUROCUP", "KLA", min_games=6)
            self.assertIsNotNone(baseline)
            engine = Faz13Engine("", "https://example.invalid", baseline_store=store)
            engine.espn = None
            with self.assertRaisesRegex(ValueError, "No calibrated profile"):
                await engine.run_prematch(PrematchRequest(0, "EUROCUP", "2026-11-10", "KLA", "TRN"))

    async def test_short_history_is_not_manufactured_into_six_games(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TeamBaselineStore(directory)
            baseline = await TeamBaselineBootstrapper(store, [self.adapter(n=3)]).ensure_async(
                "EUROLEAGUE", "RED", min_games=6)
            self.assertIsNone(baseline)
            self.assertIsNone(store.get("EUROLEAGUE", "RED"))
            self.assertEqual(len(store.get_series("EUROLEAGUE", "RED", 10)), 3)


if __name__ == "__main__":
    unittest.main()
