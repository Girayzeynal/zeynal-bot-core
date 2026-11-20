"""Fixture club identity, articles, safe clocks and real Telegram roster wiring.

All HTTP and Telegram responses are SYNTHETIC. No real player is asserted OUT.
"""
import json
import unittest

from hybrid_engine.europe_injury_public_sources import (
    PublicEuroInjuryNewsHub,sources_for,probe,render)
from hybrid_engine.europe_injury_article_source import (
    observe_article,text_candidates)
from tests.test_europe_roster_evidence_wiring import CTX,TIME

ROBOTS=b"User-agent: *\nAllow: /\n"
INDEX=b'<html><title>Latest</title><a href="/en/2026/injury-update/">EuroLeague injury update</a></html>'
ARTICLE=(b'<html><head><meta property="article:published_time" '
    b'content="2026-11-19T17:00:00+00:00"><title>Fixture injury</title></head>'
    b'<body><article>Maodo Lo will miss the game. Another Player is doubtful.'
    b'</article></body></html>')


def transport(url,*,mime,limit):
    if url.endswith("/robots.txt"):
        return dict(status="RECEIVED",body=ROBOTS)
    if url.endswith("/en/2026/injury-update/"):
        return dict(status="RECEIVED",body=ARTICLE)
    return dict(status="RECEIVED",body=INDEX)


class RealArticleCodeContractTests(unittest.TestCase):
    def test_sponsor_name_alias_matches_official_club_keys(self):
        sources=sources_for(CTX)
        clubs=[s["name"] for s in sources if s["kind"]=="OFFICIAL_CLUB_INDEX"]
        self.assertEqual(set(clubs),
            {"euroleague_zalgiris","euroleague_panathinaikos_athens"})
        self.assertEqual(len(sources),5)

    def test_unknown_name_never_guessed_by_city(self):
        ctx=dict(CTX,home=dict(official_name="Athens Unknown"),
                 away=dict(official_name="Zalgiris Kaunas"))
        clubs=[s["name"] for s in sources_for(ctx) if s["kind"]=="OFFICIAL_CLUB_INDEX"]
        self.assertEqual(clubs,["euroleague_zalgiris"])

    def test_eurocup_two_clubs_from_same_82_registry(self):
        ctx=dict(CTX,league="EUROCUP",
                 home=dict(official_name="TOFAŞ Bursa"),
                 away=dict(official_name="Cedevita Olimpija Ljubljana"))
        sources=sources_for(ctx)
        self.assertEqual(len(sources),2)
        self.assertEqual({s["name"] for s in sources},
           {"eurocup_tofas","eurocup_cedevita_olimpija"})
        self.assertTrue(all(s["kind"]=="OFFICIAL_CLUB_INDEX" for s in sources))

    def test_article_not_just_index_is_fetched_under_own_robots_rule(self):
        spec={"name":"EUROHOOPS","url":"https://www.eurohoops.net/en/euroleague/",
              "kind":"SECONDARY_EDITORIAL"}
        observed=1795179600  # 2026-11-20 UTC, after source date
        row=probe(spec,requester=transport,now=observed,read_article=True)
        self.assertEqual(len(row["inspected_articles"]),1,row)
        article=row["inspected_articles"][0]
        self.assertEqual(article["status"],"ARTICLE_TEXT_OBSERVED_CANDIDATES_ONLY")
        self.assertEqual(article["publication_time_status"],"PRECISE_PAGE_PUBLICATION_TIME")
        self.assertTrue(isinstance(article["source_published_at_utc"],int))
        names={x["player_name_text"] for x in article["unverified_player_candidates"]}
        self.assertIn("Maodo Lo",names)
        self.assertNotIn("Another Player",names)
        self.assertTrue(all(not p["match_availability_verified"]
                            and p["official_player_id"] is None
                            and not p["model_input"]
                            for p in article["unverified_player_candidates"]))
        view=render(dict(sources=[row]))
        self.assertIn("Maodo Lo",view)
        self.assertIn("MAÇ DOĞRULANMADI",view)

    def test_article_robots_denied_prevents_html_fetch(self):
        spec={"name":"EUROHOOPS","url":"https://www.eurohoops.net/en/euroleague/"}
        calls=[]
        def denied(url,*,mime,limit):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return dict(status="RECEIVED",body=b"User-agent: *\nDisallow: /\n")
            raise AssertionError("article must not be fetched")
        result=observe_article(spec,{"url":"https://www.eurohoops.net/en/test-injury/"},requester=denied,now=TIME)
        self.assertEqual(result["status"],"ARTICLE_ROBOTS_DISALLOW")
        self.assertEqual(len(calls),1)

    def test_off_host_and_unbounded_url_rejected(self):
        spec={"name":"EUROHOOPS","url":"https://www.eurohoops.net/en/euroleague/"}
        for url in ("https://evil.example/secret","http://www.eurohoops.net/a",
                    "https://www.eurohoops.net/en/a?token=test"):
            result=observe_article(spec,{"url":url},requester=lambda *a,**kw:(
                self.fail("network should never happen")),now=TIME)
            self.assertEqual(result["status"],"ARTICLE_HOST_OR_URL_REFUSED")

    def test_live_hub_synthetic_report_never_enters_model(self):
        ctx=dict(CTX,fixture_start_utc=TIME+3600)
        hub=PublicEuroInjuryNewsHub(clock=lambda:TIME+50,requester=transport,enabled=True)
        r=hub.review(ctx)
        self.assertEqual(r["verified_player_records"],[])
        self.assertFalse(r["player_status_verified"])
        self.assertFalse(r["model_input"])
        self.assertFalse(r["original_forecast_modified"])
        self.assertTrue(any(x.get("inspected_articles") for x in r["sources"]))
