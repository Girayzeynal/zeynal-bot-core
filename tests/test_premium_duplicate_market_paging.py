"""Premium market pagination regression: duplicate quote text must still navigate."""
import unittest
from hybrid_engine.telegram_premium_ui import page_view, keyboard


class PremiumDuplicateMarketPagingTests(unittest.TestCase):
    @staticmethod
    def entry():
        return dict(summary="Özet", sections={"market": "<b>Original</b>"},
                    section_pages={"market": ["<b>Aynı piyasa</b>"]*12},
                    tipoff_utc=9999999999)

    def test_fifth_page_is_distinct_even_with_identical_quote_contents(self):
        entry=self.entry()
        fourth,n4=page_view(entry,"market",3,now=1)
        fifth,n5=page_view(entry,"market",4,now=1)
        self.assertEqual((n4,n5),(12,12))
        self.assertIn("4/12",fourth)
        self.assertIn("5/12",fifth)
        self.assertNotEqual(fourth,fifth)
        buttons=keyboard("0123456789ab",section="market",page=4,pages=12)
        callbacks=[b.callback_data for row in buttons.inline_keyboard for b in row]
        self.assertIn("zui:0123456789ab:market:5",callbacks)
        self.assertIn("zui:0123456789ab:market:3",callbacks)

    def test_invalid_page_is_blocked(self):
        with self.assertRaises(ValueError):
            page_view(self.entry(),"market",12,now=1)

    def test_post_tipoff_is_labeled_archive_without_rewriting_card(self):
        entry=self.entry()
        entry["tipoff_utc"]=2
        body,count=page_view(entry,"market",4,now=3)
        self.assertIn("Maç başladı",body)
        self.assertIn("5/12",body)
        self.assertEqual(count,12)


if __name__ == "__main__":
    unittest.main()
