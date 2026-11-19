"""Offline parser and safety tests; real source smoke runs in its own workflow."""
import json
import unittest
from hybrid_engine.europe_native_roster_source import (
    endpoint, parse_native, pair, render_public
)

NOW=1800000000
CTX={"league":"EUROLEAGUE","season":"2026/2027","fixture_id":"E2026_111",
     "home":{"provider_id":"ZAL"},"away":{"provider_id":"PAN"}}


def payload(club, *, player_code="P001",season="E2026"):
    rows=[
        {"type":"J","person":{"name":"PLAYER, TEST","code":player_code},
         "club":{"code":club},"season":{"code":season},"active":True},
        {"type":"C","person":{"name":"COACH, TEST","code":"COACH"},
         "club":{"code":club},"season":{"code":season}},
    ]
    return {"status":"RECEIVED","observed_at_utc":NOW,
            "body":json.dumps(rows).encode("utf-8")}


class NativeRosterSourceTests(unittest.TestCase):
    def test_only_exact_urls(self):
        self.assertEqual(
            endpoint("EUROLEAGUE","2026/2027","ZAL"),
            "https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/clubs/ZAL/people")
        for x in ("zal","ZAL?key=x","..",""):
            with self.subTest(code=x),self.assertRaises(ValueError):
                endpoint("EUROLEAGUE","2026/2027",x)

    def test_verified_registration_is_not_injury(self):
        row=parse_native(payload("ZAL"),"EUROLEAGUE","2026/2027","ZAL",now=NOW)
        self.assertEqual(row["status"],"OFFICIAL_SEASON_REGISTRATION_OBSERVED")
        self.assertEqual(row["mapped_player_ids"],1)
        self.assertEqual(row["named_players"],1)
        self.assertEqual(row["registered_players"][0]["player_id"],"P001")
        self.assertFalse(row["player_status_verified"])
        self.assertFalse(row["model_input"])

    def test_team_and_season_mismatch_are_rejected(self):
        for receipt in (payload("PAN"),payload("ZAL",season="E2025")):
            with self.subTest(receipt=receipt),self.assertRaises(ValueError):
                parse_native(receipt,"EUROLEAGUE","2026/2027","ZAL",now=NOW)

    def test_missing_person_code_cannot_be_invented(self):
        row=parse_native(payload("ZAL",player_code=None),"EUROLEAGUE","2026/2027","ZAL",now=NOW)
        self.assertEqual(row["mapped_player_ids"],0)
        self.assertEqual(row["registered_players"][0]["player_id"],None)

    def test_future_or_late_receipt_cannot_be_backdated(self):
        record=payload("ZAL")
        record["observed_at_utc"]=NOW+1
        with self.assertRaises(ValueError):
            parse_native(record,"EUROLEAGUE","2026/2027","ZAL",now=NOW)

    def test_failed_source_is_not_empty_healthy_roster(self):
        result=parse_native({"status":"SOURCE_HTTP_ERROR","http_status":429},
                            "EUROLEAGUE","2026/2027","ZAL",now=NOW)
        self.assertEqual(result["status"],"SOURCE_HTTP_ERROR")
        self.assertFalse(result["player_status_verified"])
        self.assertEqual(result["registered_players"],[])

    def test_fixture_pair_uses_exact_codes_and_never_claims_injury(self):
        calls=[]
        def getter(url):
            calls.append(url)
            club=url.split("/clubs/")[1].split("/")[0]
            return payload(club)
        rows=pair(CTX,getter=getter,clock=lambda:NOW)
        self.assertEqual(len(calls),2)
        self.assertEqual(rows["teams"]["home"]["mapped_player_ids"],1)
        self.assertEqual(rows["teams"]["away"]["mapped_player_ids"],1)
        self.assertFalse(rows["injury_status_verified"])
        self.assertFalse(rows["model_input"])
        self.assertIn("SAKATLIK RAPORU DEĞİL",render_public(rows))


if __name__=="__main__":
    unittest.main()
