"""Contract tests for the isolated Telegram premium presentation."""
import unittest
from hybrid_engine.telegram_premium_ui import compact_summary, keyboard, detail_sections

class PremiumTelegramUITests(unittest.TestCase):
    def setUp(self):
        self.snapshot={
            'fixture_start_utc':1794697200,
            'home':{'official_name':'New Orleans Pelicans'},
            'away':{'official_name':'Denver Nuggets'},
            'prediction':{'home':113.01,'away':117.43,'total':230.44,'margin':-4.43}}
        self.evidence=[{'bookmaker':'DraftKings','market':'TOTAL','line':234.5},
                       {'bookmaker':'DraftKings','market':'HOME_HANDICAP','line':12.5}]

    def test_summary_is_compact_and_does_not_fabricate_edge(self):
        output=compact_summary(self.snapshot,self.evidence,replayed=True)
        self.assertIn('230.4',output)
        self.assertIn('234.5',output)
        self.assertIn('+12.5',output)
        self.assertNotIn('TOTAL +234.5',output)
        self.assertIn('Güven endeksi: yok',output)
        self.assertIn('Kayıtlı tahmin tekrar gösterildi',output)
        self.assertNotIn('Alt 234.5',output)
        self.assertLess(len(output.encode('utf-16-le'))//2,4096)

    def test_keyboard_callback_ids_are_short_and_scoped(self):
        markup=keyboard('abcdef123456')
        buttons=[b for row in markup.inline_keyboard for b in row]
        self.assertEqual(len(buttons),5)
        self.assertTrue(all(len(b.callback_data.encode())<=64 for b in buttons))
        self.assertEqual({b.callback_data.split(':')[-1] for b in buttons},
                         {'summary','period','market','ranges','audit'})

    def test_details_reuse_original_html_sections(self):
        parts=['<b>TAHMİN ARALIKLARI</b>\nP25 218',
               '<b>PERİYOT ANALİZİ</b>\n1Q 57',
               '<b>PİYASA KARŞILAŞTIRMASI</b>\nYok',
               '<b>MODEL DENETİMİ</b>\nKalibrasyon yok']
        result=detail_sections(parts,'<b>GÖZLENEN PİYASA</b>\n234.5')
        self.assertIn('1Q 57',result['period'])
        self.assertIn('P25 218',result['ranges'])
        self.assertIn('234.5',result['market'])
        self.assertIn('Kalibrasyon yok',result['audit'])

if __name__=='__main__':
    unittest.main()
