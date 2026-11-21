"""Proof that preforecast NBA player-minute evidence is attempted before slow V2 fetches.

Only synthetic control data. Never queries real providers or modifies archives.
"""
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from hybrid_engine.adaptive_worker import AdaptiveWorker


class FirstPlayerEvidenceOrderTests(IsolatedAsyncioTestCase):

    async def test_empty_three_league_original_scan_shows_exact_counts_not_fake_minute_attempt(self):
        worker=object.__new__(AdaptiveWorker)
        worker.progress=dict(phase="NOT_STARTED")
        worker.nba=SimpleNamespace(ledger=SimpleNamespace(path="/tmp/synthetic-read-only"))
        worker.europe={
            "EUROLEAGUE":SimpleNamespace(registry=SimpleNamespace(independent_records=lambda:[])),
            "EUROCUP":SimpleNamespace(registry=SimpleNamespace(independent_records=lambda:[])),
        }
        worker.seen=set()
        with patch("hybrid_engine.adaptive_worker.read_confirmed",return_value=[]):
            matches=await __import__("asyncio").to_thread(worker.cases)
        self.assertEqual(matches,[])
        self.assertEqual(worker.progress["phase"],"ORIGINAL_SCAN_COMPLETE")
        self.assertEqual(worker.progress["original_scan_counts"],
                         {"NBA":0,"EUROLEAGUE":0,"EUROCUP":0})
        self.assertEqual(worker.progress["eligible_future_fixtures"],0)
        self.assertEqual(worker.progress["eligible_nba_fixtures"],0)

    async def test_fixture_player_minutes_checked_before_native_history_and_fit(self):
        actions=[]
        worker=object.__new__(AdaptiveWorker)
        worker.running=False;worker.sequence=0
        worker.last_report=None;worker.last_journal=int(time.time())
        worker.group_reports={};worker.refreshed=set()
        worker.retry={};worker.player_retry={}
        worker.progress=dict(phase="NOT_STARTED")
        case=dict(code="NBA",
                  target=dict(fixture_id="f",season="2026/2027",league="NBA",
                              fixture_start_utc=int(time.time())+7200),
                  original="a"*64,snapshot=dict(fixture_id="f"))
        worker.cases=lambda:[case]
        worker.nba=SimpleNamespace(assets="/tmp/never-access-real-archive")
        def no_actual_fit(*args):
            actions.append("fit")
            raise ValueError("SYNTHETIC_NO_FIT")
        worker.research=SimpleNamespace(
            plan=lambda **kwargs:dict(sha256="b"*64),
            admit=lambda *args:actions.append("admit"),
            fit=no_actual_fit,
            performance=lambda _:dict(groups=[]),
            players="/tmp/synthetic-player-only",
        )
        worker.store=SimpleNamespace(cohort=lambda *args:[],
                                     acquire_boxes=lambda cohort:{})
        worker.refresh_native_history=lambda *args:actions.append("refresh")
        worker.labels=lambda:[]
        worker.journal=SimpleNamespace(publish=lambda _:None)
        def minutes(*args):
            actions.append("minutes")
            self.assertEqual(worker.progress["phase"],"PREGAME_PLAYER_MINUTES_SOURCE")
            self.assertEqual(worker.progress["player_input_status"],"RUNNING")
            return dict(fixture_id="f",status="BLOCKED",
                        reason="SYNTHETIC_CURRENT_LINEUP_NOT_ATTESTED")
        with patch("hybrid_engine.adaptive_worker.collect_player_inputs",side_effect=minutes):
            report=await worker.tick()
        self.assertEqual(actions,["minutes","admit","refresh","fit"])
        self.assertEqual(worker.progress["eligible_future_fixtures"],1)
        self.assertEqual(worker.progress["eligible_nba_fixtures"],1)
        self.assertEqual(worker.progress["admission_position"],1)
        self.assertEqual(worker.progress["admission_done"],1)
        self.assertEqual(worker.progress["admission_skipped_after_cutoff"],0)
        self.assertEqual(report["player_inputs"]["status"],"BLOCKED")
        self.assertEqual(worker.progress["player_input_status"],"BLOCKED")
        self.assertEqual(worker.progress["phase"],"COMPLETED")
        self.assertTrue(report["original_predictions_changed"] is False)
        self.assertTrue(report["production_changed"] is False)
        self.assertEqual(worker.sequence,1)
