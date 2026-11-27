"""Public EuroLeague editorial+club adapters, zero real network in CI.

PTB integration uses the actual six-button callback handler and a synthetic
Telegram HTTP Bot API double. This is NOT delivery to a real Telegram account.
"""
import hashlib
import unittest
from unittest.mock import patch

from hybrid_engine.europe_injury_public_sources import (
    PublicEuroInjuryNewsHub, probe,render,sources_for,request,VERSION)
from tests.test_europe_roster_evidence_wiring import CTX,EuropeanRosterAdapterTests,TIME

HTML=b"<html><head><title>EuroLeague Injury &amp; Roster</title></head><body>Report</body></html>"
ROBOTS=b"User-agent: *\nAllow: /\n"


def fake_http(url,*,mime,limit):
    if url.endswith("/robots.txt"):
        return dict(status="RECEIVED",body=ROBOTS)
    return dict(status="RECEIVED",body=HTML)


class SourceHubUnitTests(unittest.TestCase):
    def test_three_editorial_adapters_and_exact_club_indexes(self):
        rows=sources_for(CTX)
        self.assertEqual([r["name"] for r in rows[:3]],
                         ["BASKETBALL_SPHERE","EUROHOOPS","BASKETLOGY"])
        self.assertGreaterEqual(len(rows),3)
        self.assertLessEqual(len(rows),5)
        self.assertEqual(len([r for r in rows if r["kind"]=="OFFICIAL_CLUB_INDEX"]),len(rows)-3)
        self.assertEqual(sources_for(dict(CTX,league="EUROCUP")),[])

    def test_structured_editorial_table_is_only_an_unverified_candidate(self):
        page=b"""<html><title>Injury report</title>
        <table><tr><th>Player</th><th>Team</th><th>Status</th></tr>
        <tr><td>Rolands Smits</td><td>Baskonia</td><td>Out</td></tr>
        <tr><td>Rolands Smits</td><td>Baskonia</td><td>Cleared</td></tr>
        <tr><td>Iffe Lundberg</td><td>Maccabi</td><td>Doubtful</td></tr></table>
        <a href="/en/injuries/euroleague/absences/">EuroLeague injury update</a>
        <a href="https://evil.example/injuries/">Injury report</a></html>"""
        def getter(url,**kwargs):
            if url.endswith("/robots.txt"):
                return dict(status="RECEIVED",body=ROBOTS)
            return dict(status="RECEIVED",body=page)
        src=sources_for(CTX)[0]
        row=probe(src,requester=getter,now=TIME+60)
        self.assertEqual(row["candidate_count"],1)
        c=row["unverified_player_candidates"][0]
        self.assertEqual(c["source_reported_status"],"DOUBTFUL_SITE_REPORTED")
        self.assertEqual(c["player_text"],"Iffe Lundberg")
        self.assertIsNone(c["official_player_id"])
        self.assertFalse(c["match_availability_verified"])
        self.assertFalse(c["model_input"])
        self.assertEqual(len(row["unverified_injury_article_links"]),1)
        self.assertIn("basketballsphere.com",row["unverified_injury_article_links"][0]["url"])
        self.assertIn("GENEL LİG ADAYI",render(dict(sources=[row])))
        self.assertNotIn("Rolands Smits",render(dict(sources=[row])))

    def test_robots_and_html_receipt_is_sha_bound_but_never_a_player_status(self):
        spec=sources_for(CTX)[0]
        calls=[]
        def getter(url,**kwargs):
            calls.append(url)
            return fake_http(url,**kwargs)
        row=probe(spec,requester=getter,now=TIME+60)
        self.assertEqual(row["status"],"SOURCE_INDEX_OBSERVED_CANDIDATES_ONLY")
        self.assertEqual(row["document_sha256"],hashlib.sha256(HTML).hexdigest())
        self.assertEqual(row["title"],"EuroLeague Injury & Roster")
        self.assertFalse(row["player_status_verified"])
        self.assertFalse(row["model_input"])
        self.assertFalse(row["source_publication_clock_verified"])
        self.assertEqual(len(calls),2)

    def test_403_or_429_or_robots_disallow_cannot_be_bypassed(self):
        spec=sources_for(CTX)[0]
        for outcome in ({"status":"SOURCE_HTTP_NOT_200","http_status":403},
                        {"status":"SOURCE_RATE_LIMITED","http_status":429}):
            calls=[]
            def getter(url,**kwargs):
                calls.append(url)
                return outcome
            r=probe(spec,requester=getter,now=TIME)
            self.assertEqual(r["status"],"SOURCE_ROBOTS_UNAVAILABLE")
            self.assertEqual(len(calls),1)
        calls=[]
        def denied(url,**kwargs):
            calls.append(url)
            if url.endswith("robots.txt"):
                return dict(status="RECEIVED",body=b"User-agent: *\nDisallow: /\n")
            raise AssertionError("ROBOTS_DISALLOW_MUST_NOT_FETCH_HTML")
        self.assertEqual(probe(spec,requester=denied,now=TIME)["status"],"SOURCE_ROBOTS_DISALLOW")
        self.assertEqual(len(calls),1)

    def test_config_disabled_and_post_tipoff_make_zero_network_requests(self):
        calls=[]
        def getter(url,**kwargs):
            calls.append(url)
            return fake_http(url,**kwargs)
        disabled=PublicEuroInjuryNewsHub(clock=lambda:TIME+10,requester=getter,enabled=False)
        self.assertEqual(disabled.review(CTX)["status"],"PUBLIC_NEWS_HUB_DISABLED")
        active=PublicEuroInjuryNewsHub(clock=lambda:CTX["fixture_start_utc"],requester=getter,enabled=True)
        self.assertEqual(active.review(CTX)["status"],"POST_TIPOFF_NO_NEW_NEWS")
        self.assertEqual(calls,[])

    def test_live_optin_hub_uses_robots_and_cache_without_player_promotion(self):
        calls=[]
        def getter(url,**kwargs):
            calls.append(url)
            return fake_http(url,**kwargs)
        hub=PublicEuroInjuryNewsHub(clock=lambda:TIME+60,requester=getter,enabled=True)
        before=hub.public_status()
        self.assertEqual(before["last_statuses"],[])
        self.assertFalse(before["model_input"])
        r=hub.review(CTX)
        self.assertEqual(r["status"],"PUBLIC_NEWS_SOURCES_REVIEWED_CANDIDATES_ONLY")
        self.assertEqual(r["verified_player_records"],[])
        self.assertFalse(r["player_status_verified"])
        self.assertFalse(r["model_input"])
        self.assertTrue(all(x["status"]=="SOURCE_INDEX_OBSERVED_CANDIDATES_ONLY" for x in r["sources"]))
        self.assertIn("X/kulüp sosyal medya",render(r))
        count=len(calls)
        self.assertEqual(hub.review(CTX),r)
        self.assertEqual(len(calls),count)
        self.assertEqual(len(hub.public_status()["last_statuses"]),len(r["sources"]))

    def test_existing_roster_admission_remains_separate(self):
        helper=EuropeanRosterAdapterTests("runTest")
        helper.setUp()
        try:
            hub=PublicEuroInjuryNewsHub(clock=lambda:TIME+60,requester=fake_http,enabled=True)
            reviewer=helper.reviewer({})
            reviewer.public_news_hub=hub
            with patch("hybrid_engine.europe_data.time.monotonic",return_value=100.0):
                body,details=reviewer.roster(CTX)
            self.assertIn("BASKETBALL_SPHERE",body)
            self.assertIn("EUROHOOPS",body)
            self.assertIn("BASKETLOGY",body)
            self.assertEqual(details["verified_player_records"],[])
            self.assertFalse(details["public_news_model_input"])
            self.assertFalse(details["forecast_changed"])
        finally:
            helper.doCleanups()


if __name__=="__main__":
    unittest.main()

class PublicCoverageRepairTests(unittest.TestCase):
    def test_partial_index_reads_late_table_with_one_bounded_retry(self):
        from hybrid_engine.europe_injury_public_sources import MAX_BYTES,MAX_INDEX_BYTES
        spec=sources_for(CTX)[0]
        late=b'<table><tr><th>Player</th><th>Team</th><th>Status</th></tr><tr><td>Josh Nebo</td><td>Barcelona</td><td>Out</td></tr></table>'
        page=b'<html><body>'+b' '*MAX_BYTES+late+b'</body></html>'
        calls=[]
        def get(url,*,mime,limit):
            calls.append((url,limit))
            if url.endswith('/robots.txt'):return dict(status='RECEIVED',body=ROBOTS)
            return dict(status='RECEIVED_PARTIAL' if limit<len(page) else 'RECEIVED',body=page[:limit])
        r=probe(spec,requester=get,now=TIME)
        self.assertEqual(r['candidate_count'],1)
        self.assertEqual(r['unverified_player_candidates'][0]['player_text'],'Josh Nebo')
        self.assertFalse(r['incomplete_html'])
        self.assertEqual([x[1] for x in calls[1:]],[MAX_BYTES,MAX_INDEX_BYTES])

    def test_editorial_source_reuse_across_matches_keeps_original_source_clock(self):
        calls=[]
        clock=[TIME+60]
        def get(url,**kwargs):
            calls.append(url);return fake_http(url,**kwargs)
        hub=PublicEuroInjuryNewsHub(clock=lambda:clock[0],requester=get,enabled=True)
        first=hub.review(CTX);count=len(calls);clock[0]+=10
        second=hub.review(dict(CTX,fixture_id='other-fixture'))
        self.assertEqual(len(calls),count)
        self.assertEqual(first['sources'],second['sources'])
        self.assertFalse(second['model_input'])

    def test_current_sponsor_club_alias_selects_both_club_sources(self):
        ctx=dict(CTX,league='EUROLEAGUE',home={'official_name':'FC Barcelona'},
                 away={'official_name':'Fenerbahce Tarfin Istanbul'})
        names={r['name'] for r in sources_for(ctx)}
        self.assertIn('euroleague_fc_barcelona',names)
        self.assertIn('euroleague_fenerbahce_istanbul',names)
