"""Offline tests only: external injury advisories cannot rewrite forecasts."""
import hashlib
import json
import unittest
from types import SimpleNamespace

from hybrid_engine.europe_injury_advisory import fetch,bind,render,SOURCE

NOW=1800000000
CTX={"league":"EUROLEAGUE","fixture_start_utc":NOW+3600,
     "home":{"provider_id":"VBC"},"away":{"provider_id":"ZAL"}}
NATIVE={"teams":{
    "home":{"status":"OFFICIAL_SEASON_REGISTRATION_OBSERVED",
            "registered_players":[{"name":"PUERTO, JOSEP","player_id":"P123","team_id":"VBC"}]},
    "away":{"status":"OFFICIAL_SEASON_REGISTRATION_OBSERVED",
            "registered_players":[{"name":"LO, MAODO","player_id":"L456","team_id":"ZAL"}]}}}
SAMPLE={"Players":[{"FirstName":"Josep","LastName":"Puerto","Team":{"Code":"VBC"},
                     "InjuryStatus":"GTD","Id":"different-vendor-id"},
                    {"FirstName":"Maodo","LastName":"Lo","Team":{"Code":"ZAL"},
                     "InjuryStatus":"OUT","Id":"vendor-123"}]}


def capture(payload=None,*,at=NOW):
    body=json.dumps(SAMPLE if payload is None else payload).encode()
    return dict(status="RECEIVED",source=SOURCE,observed_at_utc=at,body=body,
                body_sha256=hashlib.sha256(body).hexdigest())


class FakeResponse:
    status=200
    headers=SimpleNamespace(get_content_type=lambda:"application/json")
    def __init__(self, body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):return self.body[:n]


class EuroInjuryAdvisoryTests(unittest.TestCase):
    def test_explicit_opt_in_required_no_network_and_no_key_disclosure(self):
        called=[]
        transport=lambda *a,**k:called.append(True)
        self.assertEqual(fetch(api_key="TEST-12345678",enabled=False,opener=transport)["status"],
                         "INJURY_PROVIDER_NOT_CONFIGURED")
        self.assertEqual(called,[])
        body=json.dumps(SAMPLE).encode()
        def opener(request,*,timeout):
            self.assertIn("format=json",request.full_url)
            self.assertIn("TEST-12345678",request.full_url)
            self.assertEqual(timeout,2.0)
            return FakeResponse(body)
        row=fetch(api_key="TEST-12345678",enabled=True,opener=opener,clock=lambda:NOW)
        self.assertEqual(row["status"],"RECEIVED")
        self.assertEqual(row["source"],SOURCE)
        self.assertNotIn("TEST-12345678",str({k:v for k,v in row.items() if k!="body"}))

    def test_current_source_joins_only_unique_official_player_ids(self):
        r=bind(capture(),ctx=CTX,native_report=NATIVE,now=NOW)
        self.assertEqual(r["status"],"CURRENT_THIRD_PARTY_INJURY_ADVISORY_ONLY")
        self.assertEqual([(x["player_id"],x["source_reported_status"]) for x in r["player_rows"]],
                         [("P123","GAME_TIME_DECISION_REPORTED"),("L456","OUT_REPORTED")])
        self.assertFalse(r["injury_status_verified_for_fixture"])
        self.assertFalse(r["original_prediction_eligible"])
        self.assertFalse(r["model_input"])
        self.assertFalse(r["forecast_changed"])
        self.assertIn("Maç özelinde uygunluk",render(r))

    def test_wrong_club_and_unmatched_player_and_unknown_status_not_promoted(self):
        payload={"Players":[
            dict(FirstName="Josep",LastName="Puerto",Team={"Code":"ZAL"},InjuryStatus="OUT"),
            dict(FirstName="Unknown",LastName="One",Team={"Code":"VBC"},InjuryStatus="OUT"),
            dict(FirstName="Josep",LastName="Puerto",Team={"Code":"VBC"},InjuryStatus="HEALTHY")]}
        r=bind(capture(payload),ctx=CTX,native_report=NATIVE,now=NOW)
        self.assertEqual(r["player_rows"],[])
        self.assertEqual(r["unmatched"],3)
        self.assertFalse(r["model_input"])

    def test_ambiguous_native_name_cannot_choose_first(self):
        duplicate={"teams":{"home":{"status":"OFFICIAL_SEASON_REGISTRATION_OBSERVED",
            "registered_players":[{"team_id":"VBC","name":"JOSEP PUERTO","player_id":"A"},
                                  {"team_id":"VBC","name":"PUERTO, JOSEP","player_id":"B"}]},
                           "away":NATIVE["teams"]["away"]}}
        r=bind(capture(),ctx=CTX,native_report=duplicate,now=NOW)
        self.assertEqual(len(r["player_rows"]),1)
        self.assertEqual(r["player_rows"][0]["player_id"],"L456")
        self.assertEqual(r["unmatched"],1)

    def test_duplicate_secondary_rows_never_confirm_out(self):
        doc={"Players":[SAMPLE["Players"][0],SAMPLE["Players"][0]]}
        r=bind(capture(doc),ctx=CTX,native_report=NATIVE,now=NOW)
        self.assertEqual(r["player_rows"],[])
        self.assertFalse(r["injury_status_verified_for_fixture"])

    def test_after_tipoff_invalid_pin_and_stale_receipt_fail_closed(self):
        self.assertEqual(bind(capture(at=NOW+3600),ctx=CTX,
                              native_report=NATIVE,now=NOW+3600)["status"],
                         "POST_TIPOFF_INJURY_SOURCE_NOT_PREMATCH")
        p=capture();p["body_sha256"]="0"*64
        self.assertEqual(bind(p,ctx=CTX,native_report=NATIVE,now=NOW)["status"],
                         "INJURY_PROVIDER_BODY_PIN_REFUSED")
        self.assertEqual(bind(capture(at=NOW-301),ctx=CTX,
                              native_report=NATIVE,now=NOW)["status"],
                         "INJURY_PROVIDER_CAPTURE_CLOCK_REFUSED")

    def test_injury_source_does_not_apply_to_eurocup(self):
        ctx=dict(CTX,league="EUROCUP")
        r=bind(capture(),ctx=ctx,native_report=NATIVE,now=NOW)
        self.assertEqual(r["status"],"EUROLEAGUE_ONLY_INJURY_FEED")
        self.assertEqual(r["player_rows"],[])

    def test_http_denial_is_unknown_not_healthy(self):
        row=bind({"status":"INJURY_PROVIDER_HTTP_ERROR","http_status":429},
                 ctx=CTX,native_report=NATIVE,now=NOW)
        self.assertEqual(row["http_status"],429)
        self.assertEqual(row["player_rows"],[])
        self.assertIn("Bildirilmeyen oyuncu sağlıklı kabul edilmez",render(row))


if __name__=="__main__":
    unittest.main()
