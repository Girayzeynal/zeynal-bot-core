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

    def test_real_http_response_arriving_after_request_start_is_valid(self):
        t=[NOW]
        def clock():return t[0]
        def getter(url):
            # A 2-second real provider request is NOT a future timestamp.
            t[0]+=2
            club=url.split("/clubs/")[1].split("/")[0]
            r=payload(club)
            r["observed_at_utc"]=t[0]
            return r
        rows=pair(CTX,getter=getter,clock=clock)
        self.assertEqual(rows["teams"]["home"]["status"],
                         "OFFICIAL_SEASON_REGISTRATION_OBSERVED")
        self.assertEqual(rows["teams"]["away"]["status"],
                         "OFFICIAL_SEASON_REGISTRATION_OBSERVED")
        self.assertEqual(rows["observed_at_utc"],NOW+4)

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


    def test_provider_timeout_does_not_hide_other_club(self):
        calls=[]
        def getter(url):
            club=url.split("/clubs/")[1].split("/")[0]
            calls.append(club)
            if club=="ZAL":
                raise TimeoutError("synthetic upstream timeout")
            return payload(club)
        result=pair(CTX,getter=getter,clock=lambda:NOW)
        self.assertEqual(calls,["ZAL","PAN"])
        self.assertEqual(result["teams"]["home"]["status"],"SOURCE_NETWORK_OR_TIMEOUT")
        self.assertEqual(result["teams"]["home"]["registered_players"],[])
        self.assertEqual(result["teams"]["away"]["status"],"OFFICIAL_SEASON_REGISTRATION_OBSERVED")
        self.assertEqual(result["teams"]["away"]["registered_players"][0]["player_id"],"P001")
        public=render_public(result)
        self.assertIn("SOURCE_NETWORK_OR_TIMEOUT",public)
        self.assertIn("PLAYER, TEST",public)
        self.assertIn("kaynak hatası sağlıklı kadro anlamına gelmez",public)
        self.assertFalse(result["injury_status_verified"])
        self.assertFalse(result["model_input"])

    def test_unexpected_oserror_does_not_crash_entire_europe_roster(self):
        def getter(url):
            if "/clubs/PAN/" in url:
                raise ConnectionResetError("synthetic connection reset")
            return payload("ZAL")
        result=pair(CTX,getter=getter,clock=lambda:NOW)
        self.assertEqual(result["teams"]["home"]["mapped_player_ids"],1)
        self.assertEqual(result["teams"]["away"]["status"],"SOURCE_NETWORK_OR_TIMEOUT")

    def test_http_429_is_visible_but_not_assumed_to_be_healthy(self):
        report=pair(CTX,getter=lambda url: {"status":"SOURCE_HTTP_ERROR","http_status":429},
                    clock=lambda:NOW)
        public=render_public(report)
        self.assertEqual(public.count("HTTP durum kodu: 429"),2)
        self.assertEqual(public.count("kaynak hatası sağlıklı kadro anlamına gelmez"),2)
        self.assertFalse(report["injury_status_verified"])
        self.assertFalse(report["model_input"])



class NativeRosterTelegramOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_sourceplayers_long_two_club_directory_is_not_truncated(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from hybrid_engine.europe_native_roster_source import telegram_command
        sent=[]
        async def reply_text(body,**kwargs):
            sent.append(body)
        players=[dict(player_id=f"P{i:03}",name="REAL-LENGTH-TEST-"+("X"*100)+str(i))
                 for i in range(24)]
        def record():
            return dict(status="OFFICIAL_SEASON_REGISTRATION_OBSERVED",named_players=24,
                        mapped_player_ids=24,body_sha256="f"*64,
                        source_url="https://api-live.euroleague.net/official",
                        registered_players=players)
        response=dict(teams={"home":record(),"away":record()})
        update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply_text))
        context=SimpleNamespace(args=["EUROLEAGUE","2026/2027","ZAL","PAN"])
        with patch("hybrid_engine.europe_native_roster_source.pair",return_value=response):
            await telegram_command(update,context)
        self.assertGreaterEqual(len(sent),2)
        self.assertTrue(all(len(x.encode("utf-16-le"))//2<=3200 for x in sent))
        self.assertIn("Oyuncu durumu ve sayısal skor etkisi doğrulanmadı", "".join(sent))
        self.assertEqual("".join(sent),render_public(response))

    async def test_native_sourceplayers_receipt_is_visible_not_model_input(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from hybrid_engine.europe_native_roster_source import telegram_command
        from hybrid_engine.production_parity import runtime_command
        sent=[]
        async def reply_text(body,**kwargs):sent.append(body)
        def row(side):
            return dict(status="OFFICIAL_SEASON_REGISTRATION_OBSERVED",
                        mapped_player_ids=16 if side=="home" else 17,
                        named_players=16 if side=="home" else 17,
                        observed_at_utc=1790000000,body_sha256="a"*64,
                        source_url="https://api-live.euroleague.net/official",
                        registered_players=[dict(name="Athlete "+side,player_id=side)])
        response=dict(teams={"home":row("home"),"away":row("away")})
        state={}
        update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply_text))
        context=SimpleNamespace(args=["EUROLEAGUE","2026/2027","ZAL","PAN"],
            application=SimpleNamespace(bot_data=state))
        with patch("hybrid_engine.europe_native_roster_source.pair",return_value=response):
            await telegram_command(update,context)
        observed=state["last_sourceplayers_native_receipt"]
        self.assertEqual(observed["teams"]["home"]["official_player_ids"],16)
        self.assertEqual(observed["teams"]["away"]["official_player_ids"],17)
        self.assertFalse(observed["roster_confirmed_for_game"])
        self.assertFalse(observed["numeric_player_effect_applied"])
        context.args=["integrations"]
        sent.clear()
        await runtime_command(update,context)
        import json
        report=json.loads("".join(sent))
        self.assertEqual(report["last_actual_official_player_directory_query"],observed)
        self.assertFalse(report["independently_verified_player_coach_effects_in_numeric_forecast"])




if __name__=="__main__":
    unittest.main()
