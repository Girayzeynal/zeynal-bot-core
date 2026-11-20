"""Offline evidence contract: no private key, no provider call in CI."""
from datetime import datetime,timezone
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest

from hybrid_engine.hoopsapi_market import (
    BASE,HoopsFreeMarket,valid_pair,bound_game,parse_lines,render,namekey,read_key
)
NOW=int(datetime.fromisoformat("2026-11-20T19:00:00+00:00").timestamp())
TIP=int(datetime.fromisoformat("2026-11-20T19:45:00+00:00").timestamp())
CTX={"league":"EUROLEAGUE","fixture_start_utc":TIP,
     "home":{"official_name":"Partizan Mozzart Bet Belgrade"},
     "away":{"official_name":"Beşiktaş Fuzul Istanbul"}}
EVENT={"game_id":12345,"competition":"Europe - Euroleague",
       "home":"Partizan Mozzart Bet","away":"Besiktas Istanbul",
       "start_time":"2026-11-20T19:45:00Z"}
DETAIL=dict(EVENT,providers={"betway":{"captured_at":"2026-11-20T18:59:00Z"}},
 periods={"ft":{"betway":{"total":{"line":164.5,"over":1.91,"under":1.93}}},
          "q1":{"betway":{"spread":{"line":-1.5,"home":1.80,"away":2.05}}}},
 lines={"ft":{"betway":{"total":[{"line":164.5,"over":1.91,"under":1.93},
                                 {"line":166.5,"over":2.13,"under":1.74}]}},
        "q1":{"betway":{"team_total_home":[{"line":19.5,"over":1.90,"under":1.92}]}}})

class HoopsMarketTest(unittest.TestCase):
    def provider(self,url,key):
        self.calls.append(url)
        if url==BASE+"/games?competition=Europe%20-%20Euroleague":
            return {"status":"RECEIVED","document":{"count":1,"games":[EVENT]}}
        if url==BASE+"/games/12345":
            return {"status":"RECEIVED","document":DETAIL}
        raise AssertionError("unexpected provider URL")

    def setUp(self):self.calls=[]

    def client(self):
        return HoopsFreeMarket(requester=self.provider,clock=lambda:NOW)

    def test_disabled_really_zero_requests(self):
        with patch.dict("os.environ",{"ZEYNAL_HOOPSAPI_ENABLED":"0",
                                     "ZEYNAL_HOOPSAPI_KEY":"test-secret-placeholder"},clear=False):
            report=self.client().review(CTX)
        self.assertEqual(report["status"],"OPT_IN_DISABLED")
        self.assertEqual(self.calls,[])

    def test_missing_key_zero_requests(self):
        with patch.dict("os.environ",{"ZEYNAL_HOOPSAPI_ENABLED":"1",
                                     "ZEYNAL_HOOPSAPI_KEY":""},clear=False):
            report=self.client().review(CTX)
        self.assertEqual(report["status"],"FREE_API_KEY_NOT_CONFIGURED")
        self.assertEqual(self.calls,[])

    def test_real_schema_all_periods_alternate_and_team_totals(self):
        with patch.dict("os.environ",{"ZEYNAL_HOOPSAPI_ENABLED":"1",
                                     "ZEYNAL_HOOPSAPI_KEY":"not-real-api-key"},clear=False):
            client=self.client()
            report=client.review(CTX)
            repeated=client.review(CTX)
        self.assertEqual(report["status"],"CURRENT_REFERENCE_ONLY_NOT_SETTLEMENT_VERIFIED")
        self.assertEqual(len(self.calls),2)
        self.assertEqual(report,repeated)
        self.assertEqual({(x["period"],x["market"]) for x in report["quotes"]},
                         {("ft","total"),("q1","spread"),("q1","team_total_home")})
        self.assertEqual(len(report["quotes"]),4) # 2 FT alternate, Q1 spread & team total
        self.assertFalse(report["model_input"])
        self.assertFalse(report["original_prediction_modified"])
        txt=render(report)
        self.assertIn("UZATMA DAHİL",txt)
        self.assertIn("166.5",txt)
        self.assertIn("1. çeyrek",txt)
        self.assertNotIn("NO EDGE",txt)

    def test_post_tipoff_cannot_be_pregame_pricing(self):
        client=HoopsFreeMarket(requester=self.provider,clock=lambda:TIP+2)
        with patch.dict("os.environ",{"ZEYNAL_HOOPSAPI_ENABLED":"1",
                                     "ZEYNAL_HOOPSAPI_KEY":"not-real-api-key"},clear=False):
            r=client.review(CTX)
        self.assertEqual(r["status"],"POST_TIPOFF_REFERENCE_ONLY_NO_LIVE_QUERY")
        self.assertEqual(self.calls,[])

    def test_exact_utc_and_ordered_identity(self):
        self.assertTrue(bound_game(EVENT,CTX))
        self.assertFalse(bound_game(dict(EVENT,start_time="2026-11-20T19:46:00Z"),CTX))
        self.assertFalse(bound_game(dict(EVENT,home="Besiktas Istanbul",away="Partizan Mozzart Bet"),CTX))
        self.assertFalse(bound_game(dict(EVENT,competition="NBA"),CTX))
        self.assertEqual(namekey("Beşiktaş Fuzul Istanbul"),"besiktas")

    def test_missing_and_ambiguous_game_never_admitted(self):
        def mismatch(url,key):
            self.calls.append(url)
            return {"status":"RECEIVED","document":{"games":[dict(EVENT,home="Other")]}}
        client=HoopsFreeMarket(requester=mismatch,clock=lambda:NOW)
        with patch.dict("os.environ",{"ZEYNAL_HOOPSAPI_ENABLED":"1",
                                     "ZEYNAL_HOOPSAPI_KEY":"not-real-api-key"},clear=False):
            r=client.review(CTX)
        self.assertEqual(r["status"],"FIXTURE_NOT_UNIQUELY_MATCHED")
        self.assertEqual(len(self.calls),1)

    def test_free_local_budget_eight_calls(self):
        def always_received(url,key):
            self.calls.append(url)
            return {"status":"RECEIVED","document":{}}
        client=HoopsFreeMarket(requester=always_received,clock=lambda:NOW)
        for i in range(1,9):
            client._get(BASE+"/games/"+str(i),"not-real-api-key",ttl=0)
        row=client._get(BASE+"/games/99","not-real-api-key",ttl=0)
        self.assertEqual(row["status"],"LOCAL_FREE_DAILY_BUDGET")
        self.assertEqual(len(self.calls),8)

    def test_private_key_file_requires_owner_only_mode(self):
        with TemporaryDirectory() as root:
            path=Path(root)/".zeynal-test-hoopsapi.key"
            path.write_text("a-private-test-key-not-live")
            os.chmod(path,0o644)
            with patch("hybrid_engine.hoopsapi_market.Path.home",return_value=Path(root)):
                with patch.dict("os.environ",{"ZEYNAL_HOOPSAPI_KEY":""},clear=False):
                    self.assertEqual(read_key(),"")
                    os.chmod(path,0o600)
                    self.assertEqual(read_key(),"a-private-test-key-not-live")
                    path.unlink()
                    path.symlink_to(Path(root)/"outside")
                    self.assertEqual(read_key(),"")

    def test_price_schema_and_provider_capture_clock(self):
        self.assertIsNone(valid_pair({"line":163.5,"over":1.9},"total"))
        self.assertIsNone(valid_pair({"line":163.5,"over":1.0,"under":1.9},"total"))
        report=parse_lines(dict(DETAIL,providers={
            "betway":{"captured_at":"2026-11-20T14:00:00Z"}}),now=NOW)
        self.assertEqual(report["rows"],[])
        self.assertGreater(report["stale"],0)

if __name__=="__main__":
    unittest.main()
