from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,patch
from core.team_identity import digest
from hybrid_engine.rotation_premium import panels,present,install,LABELS
from hybrid_engine.telegram_premium_ui import page_view

NOW=1796000000
def packet():
    s=dict(fixture_id='f',fixture_start_utc=NOW+3600,home={'official_name':'Home & Team'},away={'official_name':'Away'})
    band=dict(mean=100.,p05=80,p10=85,p90=115,p95=120)
    m={k:dict(total=dict(band,mean=200.),home=dict(band),away=dict(band),margin=dict(band,mean=0.)) for k,_ in LABELS}
    p=dict(fixture_id='f',original_snapshot_sha256=digest(s),fixture_start_utc=s['fixture_start_utc'],generated_at_utc=NOW-10,
        production_enabled=False,forecast_changed=False,calibrated=False,residual_games=83,simulation=dict(scenarios=8192,markets=m))
    row=dict(fixture_id='f',snapshot_sha256=digest(s))
    return s,(NOW-10,NOW-9,'a'*64,p,row)

def response():
    s,r=packet()
    keys=('period','ranges','market','audit','roster','archive')
    old=dict(summary='OLD SUMMARY',sections={k:'OLD '+k for k in keys},section_pages={k:['OLD '+k] for k in keys},
        chat_id=1,tipoff_utc=s['fixture_start_utc'],iddaa_first_half_total=99)
    markup=SimpleNamespace(inline_keyboard=[[SimpleNamespace(callback_data='zui:123456789abc:period')]])
    return dict(status='ANALYSIS_OK',snapshot=s,reply_markup=markup,html='OLD',html_parts=['OLD']),{'123456789abc':old},r

class PremiumTests(TestCase):
    def test_coherent_archive_and_preserved_legacy(self):
        res,cache,r=response();before=deepcopy(cache);snapshot=deepcopy(res['snapshot'])
        out=present(res,cache,r,NOW)
        e=cache['123456789abc'];self.assertIn('Home &amp; Team',out['html'])
        self.assertIn('200,00',out['html']);self.assertIn('Yeni canlı hesap değil',out['html'])
        self.assertIn('1. çeyrek',e['sections']['period'])
        self.assertEqual(len(e['section_pages']['ranges']),7)
        self.assertEqual(e['sections']['archive'],before['123456789abc']['sections']['archive'])
        self.assertEqual(e['sections']['roster'],before['123456789abc']['sections']['roster'])
        self.assertIn('OLD market',e['sections']['market']);self.assertIn('OLD SUMMARY',e['sections']['audit'])
        self.assertIsNone(e['iddaa_first_half_total'])
        self.assertEqual(out['snapshot'],snapshot);self.assertEqual(res['html'],'OLD')
        self.assertIn('ARTIK GÜNCEL DEĞİL',page_view(e,'period',0,now=snapshot['fixture_start_utc']-300)[0])
    def test_wrong_pin_and_cutoff_refused(self):
        s,r=packet()
        with self.assertRaisesRegex(ValueError,'IDENTITY_OR_CLOCK'):panels(s,r,s['fixture_start_utc']-300)
        s['fixture_id']='different'
        with self.assertRaisesRegex(ValueError,'IDENTITY_OR_CLOCK'):panels(s,r,NOW)

class PremiumInstallTests(IsolatedAsyncioTestCase):
    async def test_opt_in_lookup_and_failure_fallback(self):
        res,cache,r=response();base=SimpleNamespace(analyze=AsyncMock(return_value=res))
        state=dict(verified_analysis_service=base,premium_reports=cache)
        install(state,'root','ledger')
        with patch('hybrid_engine.rotation_premium.time.time',return_value=NOW),patch('hybrid_engine.rotation_premium.lookup',return_value=r):
            out=await state['verified_analysis_service'].analyze('NBA','date','home','away')
        self.assertIn('200,00',out['html'])
        with patch('hybrid_engine.rotation_premium.time.time',return_value=NOW),patch('hybrid_engine.rotation_premium.lookup',side_effect=ValueError('bad')):
            out=await state['verified_analysis_service'].analyze('NBA','date','home','away')
        self.assertIs(out,res)
        with patch('hybrid_engine.rotation_premium.lookup') as lookup:
            self.assertIs(await state['verified_analysis_service'].analyze('EUROLEAGUE'),res)
            lookup.assert_not_called()
