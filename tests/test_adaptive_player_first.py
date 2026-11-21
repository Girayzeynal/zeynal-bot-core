"""Proof that preforecast NBA player-minute evidence is attempted before slow V2 fetches.

Only synthetic control data. Never queries real providers or modifies archives.
"""
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from hybrid_engine.adaptive_worker import AdaptiveWorker


class FirstPlayerEvidenceOrderTests(IsolatedAsyncioTestCase):
    async def test_fixture_player_minutes_checked_before_native_history_and_fit(self):
        actions=[]
        worker=object.__new__(AdaptiveWorker)
        worker.running=False;worker.sequence=0
        worker.last_report=None;worker.last_journal=int(time.time())
        worker.group_reports={};worker.refreshed=set()
        worker.retry={};worker.player_retry={}
        worker.progress=dict(phase="NOT_STARTED")
        case=dict(code="NBA",
                  target=dict(fixture_id="f",season="2026/2027",league="NBA"),
                  original="a"*64,snapshot=dict(fixture_id="f"))
        worker.cases=lambda:[case]
        worker.nba=SimpleNamespace(assets="/tmp/never-access-real-archive")
        def no_actual_fit(*args):
            actions.append("fit")
            raise ValueError("SYNTHETIC_NO_FIT")
        worker.research=SimpleNamespace(
            plan=lambda **kwargs:dict(sha256="b"*64),
            admit=lambda *args:None,
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
        self.assertEqual(actions,["minutes","refresh","fit"])
        self.assertEqual(report["player_inputs"]["status"],"BLOCKED")
        self.assertEqual(worker.progress["player_input_status"],"BLOCKED")
        self.assertEqual(worker.progress["phase"],"COMPLETED")
        self.assertTrue(report["original_predictions_changed"] is False)
        self.assertTrue(report["production_changed"] is False)
        self.assertEqual(worker.sequence,1)
