"""Regressions for screenshot 2026-11-20: no NBA links or other team players."""
import unittest
from hybrid_engine.europe_injury_public_sources import (
    _page_candidates, review_current_team_news, render, sources_for,
    _official_team_key,
)

ROBOTS=b"User-agent: *\nAllow: /\n"
INDEX=b"""<html><head><title>EuroLeague Injury Report</title></head><body>
<table><tr><th>Player</th><th>Team</th><th>Status</th></tr>
<tr><td>Rolands Smits</td><td>Baskonia</td><td>Out</td></tr>
<tr><td>Iffe Lundberg</td><td>Maccabi Tel Aviv</td><td>Out</td></tr>
<tr><td>Maodo Lo</td><td>Zalgiris Kaunas</td><td>Questionable</td></tr>
<tr><td>Player Test</td><td>Panathinaikos Athens</td><td>Doubtful</td></tr></table>
<a href="/en/injuries/nba/">NBA injuries</a>
<a href="/en/injuries/">All injuries</a>
<a href="/en/injuries/euroleague/absences/">EuroLeague injuries</a>
</body></html>"""
ART=b"<html><head><title>EuroLeague report</title></head><body>No player statuses.</body></html>"

def fake_transport(url,*,mime,limit):
    if url.endswith("/robots.txt"):
        return dict(status="RECEIVED",body=ROBOTS)
    if url.endswith("/en/injuries/euroleague/absences/"):
        return dict(status="RECEIVED",body=ART)
    return dict(status="RECEIVED",body=INDEX)

class LeagueTeamScopeTests(unittest.TestCase):
    def test_basketball_sphere_nba_and_generic_portal_links_rejected(self):
        players,links=_page_candidates(INDEX,"https://basketballsphere.com/en/injuries/euroleague/")
        self.assertEqual(len(players),4)
        self.assertEqual([x["url"] for x in links],
            ["https://basketballsphere.com/en/injuries/euroleague/absences/"])

    def test_basketball_sphere_twenty_club_tables_not_only_first_six(self):
        # Real index layout: 10 recent updates table, then 20
        # Player/Status/Injury/Expected-return tables under club headings.
        primary="<table><tr><th>Player</th><th>Team</th><th>Status</th></tr><tr><td>Rolands Smits</td><td>Baskonia</td><td>Out</td></tr></table>"
        unrelated="".join(
            "<h3>Real Madrid</h3><table><tr><th>Player</th><th>Status</th></tr>"+
            "<tr><td>Example Player</td><td>Out</td></tr></table>"
            for _ in range(8))
        club=("<h3><a href='/team/zalgiris'>Zalgiris</a></h3>"
              "<table><tr><th>Player</th><th>Status</th><th>Injury</th>"
              "<th>Expected return</th></tr>"
              "<tr><td>Nigel Williams-Goss</td><td>Out</td><td>Hamstring</td>"
              "<td>4 weeks</td></tr></table>"
              "<h3>Panathinaikos</h3><p>No injured players reported.</p>")
        body=("<html><body>"+primary+unrelated+club+"</body></html>").encode()
        from hybrid_engine.europe_injury_public_sources import _page_candidates
        rows,links=_page_candidates(body,
                    "https://basketballsphere.com/en/injuries/euroleague/")
        self.assertEqual(links,[])
        match=[r for r in rows if r["player_text"]=="Nigel Williams-Goss"]
        self.assertEqual(len(match),1)
        self.assertEqual(match[0]["team_text"],"Zalgiris")
        self.assertEqual(match[0]["source_reported_status"],"OUT_SITE_REPORTED")
        self.assertFalse(match[0]["match_availability_verified"])
        self.assertFalse(match[0]["model_input"])
        self.assertFalse(any(r["team_text"]=="Panathinaikos" for r in rows))
        report={"league":"EUROLEAGUE",
                "selected_team_keys":["euroleague_zalgiris",
                                      "euroleague_panathinaikos_athens"],
                "sources":[{"source":"BASKETBALL_SPHERE",
                            "status":"SOURCE_INDEX_OBSERVED_CANDIDATES_ONLY",
                            "unverified_player_candidates":rows}]}
        text=render(report)
        self.assertIn("Nigel Williams-Goss",text)
        self.assertNotIn("Rolands Smits",text)
        self.assertIn("MAÇ DOĞRULANMADI",text)

    def test_club_table_requires_unambiguous_own_heading_and_status(self):
        from hybrid_engine.europe_injury_public_sources import _page_candidates
        html=("<html><body>"
              "<h3>Latest updates</h3><table><tr><th>Player</th>"
              "<th>Status</th></tr><tr><td>Fake Absentee</td>"
              "<td>Out</td></tr></table>"
              "<h3>Zalgiris</h3><table><tr><th>Player</th>"
              "<th>Status</th></tr><tr><td>Unknown Player</td>"
              "<td>Injured maybe</td></tr></table></body></html>").encode()
        rows,_=_page_candidates(html,
                   "https://basketballsphere.com/en/injuries/euroleague/")
        self.assertEqual(rows,[])

    def test_pagination_is_not_an_injury_article(self):
        from hybrid_engine.europe_injury_public_sources import (
            _article_matches_index_competition, probe)
        index_url="https://basketballsphere.com/en/injuries/euroleague/"
        html=b"""<html><title>EuroLeague Injuries</title>
        <a href="/en/injuries/euroleague/page/2/">Euroleague injuries page 2</a>
        <a href="/en/injuries/euroleague/page/3/">Euroleague injuries page 3</a>
        <a href="/en/injuries/euroleague/fixture-absence-report/">Injury report</a>
        </html>"""
        self.assertFalse(_article_matches_index_competition(
            index_url,index_url+"page/2/"))
        self.assertFalse(_article_matches_index_competition(
            index_url,index_url+"page/3/"))
        _, links=_page_candidates(html,index_url)
        self.assertEqual([x["url"] for x in links],
                         [index_url+"fixture-absence-report/"])
        calls=[]
        def requester(url,*,mime,limit):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return dict(status="RECEIVED",body=ROBOTS)
            if url==index_url:
                return dict(status="RECEIVED",body=html)
            return dict(status="RECEIVED",body=ART)
        observed=probe(dict(name="BASKETBALL_SPHERE",
                            url=index_url,kind="SECONDARY_EDITORIAL"),
                       requester=requester,now=1795179600,read_article=True)
        self.assertEqual(len(observed["inspected_articles"]),1)
        self.assertNotIn("page/2",str(observed))
        self.assertNotIn("page/3",str(observed))
        self.assertNotIn(index_url+"page/2/",calls)
        self.assertNotIn(index_url+"page/3/",calls)
        self.assertFalse(observed["model_input"])

    def test_current_team_panel_only_shows_two_relevant_team_candidates(self):
        report=review_current_team_news(
            "EUROLEAGUE","Zalgiris Kaunas","Panathinaikos AKTOR Athens",
            requester=fake_transport,now=1795179600)
        self.assertEqual(set(report["selected_team_keys"]),{
            "euroleague_zalgiris","euroleague_panathinaikos_athens"})
        self.assertTrue(all(x["model_input"] is False for x in report["sources"]))
        screen=render(report)
        self.assertIn("Maodo Lo",screen)
        self.assertIn("İLGİLİ KULÜP HABER ADAYI",screen)
        self.assertIn("Panathinaikos Athens",screen)
        self.assertNotIn("Rolands Smits",screen)
        self.assertNotIn("Iffe Lundberg",screen)
        self.assertNotIn("/en/injuries/nba/",screen)
        self.assertNotIn("https://basketballsphere.com/en/injuries/\n",screen)
        self.assertIn("farklı kulübe ait aday",screen)
        self.assertFalse(report["player_status_verified"])
        self.assertIsNone(report["fixture_id"])

    def test_editorial_article_unnamed_team_candidate_does_not_claim_fixture(self):
        report={"league":"EUROLEAGUE",
                "selected_team_keys":["euroleague_zalgiris"],
                "sources":[{"source":"EUROHOOPS","kind":"SECONDARY_EDITORIAL",
                    "status":"SOURCE_INDEX_OBSERVED_CANDIDATES_ONLY",
                    "inspected_articles":[{"status":"ARTICLE_TEXT_OBSERVED_CANDIDATES_ONLY",
                        "unverified_player_candidates":[{
                            "player_name_text":"Some Player",
                            "source_reported_status":"OUT_TEXT_CANDIDATE"}]}]}]}
        value=render(report)
        self.assertNotIn("Some Player",value)
        self.assertIn("kulübe bağlanamadı",value)

    def test_names_are_exactly_bound_to_existing_club_identity(self):
        self.assertEqual(_official_team_key("EUROLEAGUE","Panathinaikos Athens"),
                         "euroleague_panathinaikos_athens")
        self.assertEqual(_official_team_key("EUROLEAGUE","Panathinaikos"),
                         "euroleague_panathinaikos_athens")
        self.assertEqual(_official_team_key("EUROLEAGUE","Zalgiris Kaunas"),
                         "euroleague_zalgiris")
        self.assertIsNone(_official_team_key("EUROLEAGUE","Unknown Athens"))
        self.assertIsNone(_official_team_key("EUROCUP","Panathinaikos"))

if __name__=="__main__":
    unittest.main()
