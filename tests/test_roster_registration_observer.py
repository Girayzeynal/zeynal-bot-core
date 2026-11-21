"""Synthetic team registration receipts; never assert real player transfers."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from hybrid_engine.roster_registration_observer import record,observe
from hybrid_engine.three_league_roster_bridge import snapshot

NOW=int(time.time())-120


def item(ids,at=NOW):
    return snapshot(league="EUROLEAGUE",season="2026/2027",team_id="ZAL",
        observed_at_utc=at,
        source_url="https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/clubs/ZAL/people",
        source_body_sha256="a"*64,
        source_kind="EUROPE_OFFICIAL_SEASON_REGISTRATION",
        players=[dict(player_id=x,name=x) for x in ids])


class OfficialClubObserverTests(unittest.TestCase):
    def test_first_capture_and_next_native_change_are_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            a=item(["a","b","c","d","e"],at=NOW-20)
            b=item(["a","b","c","d","new"],at=NOW)
            result_a=record(td,a)
            result_b=record(td,b)
            self.assertEqual(result_a["status"],"APPENDED_OBSERVED_OFFICIAL_REGISTRATION")
            delta=result_b["registration_delta"]
            self.assertEqual(delta["newly_registered_player_ids"],["new"])
            self.assertEqual(delta["no_longer_registered_player_ids"],["e"])
            self.assertFalse(result_b["actual_transfer_confirmed"])
            self.assertFalse(result_b["model_input_allowed"])
            self.assertEqual(len(list(Path(td).glob("*.json"))),2)
            self.assertEqual(record(td,a)["status"],"UNCHANGED_PREVIOUSLY_SAVED_OBSERVATION")
            self.assertEqual(len(list(Path(td).glob("*.json"))),2)

    def test_stale_or_conflicting_clock_does_not_replace_newer(self):
        with tempfile.TemporaryDirectory() as td:
            newer=item(["a","b","c","d","e"])
            record(td,newer)
            old=item(["a","b","c","d","e"],at=NOW-30)
            with self.assertRaisesRegex(ValueError,"REVERSE_TIME"):
                record(td,old)
            same=item(["x","b","c","d","e"],at=NOW)
            with self.assertRaisesRegex(ValueError,"CONFLICTING_EQUAL"):
                record(td,same)
            self.assertEqual(len(list(Path(td).glob("*.json"))),1)

    def test_nba_does_not_fake_native_euro_source(self):
        nba=snapshot(league="NBA",season="2026/2027",team_id="A",
            observed_at_utc=NOW,source_url="https://www.nba.com/players",
            source_body_sha256="a"*64,source_kind="NBA_OFFICIAL_ROSTER_DIRECTORY",
            players=[dict(player_id="a",name="A")])
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,"EURO_ONLY"):
                record(td,nba)

    def test_future_and_fake_pins_block(self):
        bad=item(["a","b","c","d","e"]);bad["payload"]["players"][0]["player_id"]="tampered"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,"TAMPERED"):
                record(td,bad)
            with self.assertRaisesRegex(ValueError,"FUTURE"):
                record(td,item(["a","b","c","d","e"]),decision_utc=NOW-5)

    def test_actual_euro_adapter_two_clubs_dry_run_and_save(self):
        def getter(url):
            club="ZAL" if url.endswith("/ZAL/people") else "PAN"
            raw=[dict(type="J",person=dict(code=club+str(i),name="Name "+str(i)),
                 club=dict(code=club),season=dict(code="E2026")) for i in range(6)]
            return dict(status="RECEIVED",body=json.dumps(raw).encode(),
                        observed_at_utc=NOW)
        dry=observe("EUROLEAGUE","2026/2027","ZAL","PAN",
                    getter=getter,clock=lambda:NOW+1)
        self.assertEqual(dry["results"]["home"]["status"],"DRY_RUN_OFFICIAL_SEASON_REGISTRATION")
        self.assertFalse(dry["scheduled_polling_installed"])
        with tempfile.TemporaryDirectory() as td:
            saved=observe("EUROLEAGUE","2026/2027","ZAL","PAN",root=td,
                          getter=getter,clock=lambda:NOW+1)
            self.assertEqual(saved["results"]["away"]["status"],"APPENDED_OBSERVED_OFFICIAL_REGISTRATION")
            self.assertEqual(len(list(Path(td).glob("*.json"))),2)

    def test_status_429_never_saved_as_empty_or_healthy(self):
        with tempfile.TemporaryDirectory() as td:
            result=observe("EUROCUP","2026/2027","ZAL","PAN",root=td,
                 getter=lambda url:dict(status="SOURCE_HTTP_ERROR",http_status=429),
                 clock=lambda:NOW+1)
            self.assertEqual(result["results"]["home"]["status"],
                             "REGISTRATION_SOURCE_UNAVAILABLE_OR_INCOMPLETE")
            self.assertEqual(list(Path(td).glob("*.json")),[])

if __name__=="__main__":unittest.main()
