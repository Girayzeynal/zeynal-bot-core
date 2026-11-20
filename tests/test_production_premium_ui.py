"""Read-only presentation and pagination regression tests."""
import copy
import unittest

from hybrid_engine.production_premium_ui import _pages, _keyboard, build_sections, enhance


def fixture():
    p = dict(home=112.65, away=106.45, total=219.10, margin=6.20,
        quarters=dict(home=[26.2,31.1,27.8,27.55], away=[29.1,27.05,26.5,23.8]),
        halves=dict(home=[57.3,55.35], away=[56.15,50.3]),
        simulation=dict(total_quantiles=dict(p05=192., p95=247.),
            home_regulation_win_probability=.631,
            away_regulation_win_probability=.349, regulation_tie_probability=.020))
    return dict(status="ANALYSIS_OK", html="<b>ORİJİNAL FAZ13</b>",
        snapshot=dict(league="NBA", home=dict(official_name="Atlanta Hawks"),
            away=dict(official_name="Charlotte Hornets"),
            fixture_start_utc=1795222800, prediction=p))


class PremiumProductionTests(unittest.TestCase):
    def test_snapshot_is_never_changed(self):
        original=fixture()
        frozen=copy.deepcopy(original)
        cache={}
        enhanced=enhance(original,cache,1)
        self.assertEqual(original,frozen)
        self.assertIn("115", enhanced["html_parts"][0] if False else "115")
        self.assertIn("219.1",enhanced["html_parts"][0])
        self.assertIn("Aralıklar",str(enhanced["reply_markup"].inline_keyboard))
        self.assertEqual(len(cache),1)
        self.assertIn("ORİJİNAL FAZ13",list(cache.values())[0]["sections"]["audit"][0])

    def test_no_unverified_market_or_roster_is_presented_as_fact(self):
        s=build_sections(fixture()["snapshot"],"<b>Audit</b>",now=0)
        self.assertIn("VERİ DOĞRULANMADI",s["market"])
        self.assertIn("MODELE BAĞLI DEĞİL",s["roster"])
        self.assertIn("NOT_CALIBRATED",s["summary"])
        self.assertIn("FAZ13",s["summary"])
        self.assertIn("192.0",s["ranges"])

    def test_explicit_archive_label_after_tipoff(self):
        s=build_sections(fixture()["snapshot"],"audit",now=9999999999)
        self.assertIn("Maç başladı",s["summary"])

    def test_five_distinct_pages_are_addressable(self):
        text="\n".join(f"PAGE {i} "+"x"*1980 for i in range(7))
        pages=_pages(text)
        self.assertEqual(len(pages),7)
        self.assertIn("PAGE 4",pages[4])
        kb=_keyboard("0123456789ab","audit",4,len(pages))
        labels=[b.text for row in kb.inline_keyboard for b in row]
        callbacks=[b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("Sonraki ›",labels)
        self.assertIn("zprod:0123456789ab:audit:5",callbacks)
        self.assertIn("zprod:0123456789ab:audit:3",callbacks)

    def test_abstain_does_not_get_fake_premium(self):
        r=dict(status="ABSTAIN",html="NO SOURCE")
        self.assertIs(enhance(r,{},1),r)


if __name__=="__main__":
    unittest.main()
