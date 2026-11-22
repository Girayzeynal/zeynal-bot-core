"""Two-clock user display: original and published current score remain distinct."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch

from hybrid_engine.current_assessment_ui import two_clock_text,install_dual_clock_display,current_panels,bound_current_market_cards

NOW=1795339800


class DualClockTextTests(unittest.TestCase):
    def setUp(self):
        self.ctx=dict(league="NBA",fixture_id="x",fixture_start_utc=NOW+10800,
            prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        self.candidate=dict(candidate=dict(home=108.,away=110.,total=218.),
            prediction_generated_at_utc=NOW-60,
            source_available_max_utc=NOW-70,
            parameter_fit_cutoff_utc=NOW-3600)
    def test_new_research_score_shows_both_clocks_and_delta_without_fake_player_integration(self):
        a=SimpleNamespace(latest=Mock(return_value=self.candidate))
        text=two_clock_text(self.ctx,a,now=NOW)
        self.assertIn("GÜNCEL AYRI ARAŞTIRMA SKORU",text)
        self.assertIn("Toplam 218.00",text)
        self.assertIn("İlk skor: 105.00 – 115.00",text)
        self.assertIn("-2.00 sayı",text)
        self.assertIn("DAHİL EDİLMEDİ",text)
        self.assertIn("NOT_CALIBRATED",text)
        self.assertTrue(self.candidate["candidate"]["total"]==218.)
    def test_missing_or_stale_candidate_does_not_claim_an_updated_score(self):
        a=SimpleNamespace(latest=Mock(return_value=None))
        text=two_clock_text(self.ctx,a,now=NOW)
        self.assertIn("HENÜZ YAYIMLANMADI",text)
        self.assertIn("İlk skor: 105.00",text)
        a.latest.return_value=self.candidate
        self.candidate["prediction_generated_at_utc"]=NOW-4000
        aged=two_clock_text(self.ctx,a,now=NOW)
        self.assertIn("ARŞİV",aged)
        self.assertNotIn("GÜNCEL AYRI ARAŞTIRMA SKORU",aged)


class DualClockDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_does_not_modify_source_or_fit_in_telegram_handler(self):
        ctx=dict(league="NBA",fixture_id="x",fixture_start_utc=NOW+10800,
            prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        response=dict(status="ANALYSIS_OK",snapshot=ctx,html="FIRST",html_parts=["FIRST"],new_record=False)
        base=SimpleNamespace(analyze=AsyncMock(return_value=response),ledger=object())
        a=SimpleNamespace(latest=Mock(return_value=None))
        state=dict(verified_analysis_service=base)
        install_dual_clock_display(state,a)
        with patch("hybrid_engine.current_assessment_ui.time.time",return_value=NOW):
            out=await state["verified_analysis_service"].analyze("NBA","date","home","away")
        self.assertIn("HENÜZ YAYIMLANMADI",out["html"])
        self.assertIn("FIRST",out["html"])
        self.assertIs(response["snapshot"],out["snapshot"])
        self.assertEqual(response["html"],"FIRST")
        a.latest.assert_called_once_with(ctx)
    async def test_current_score_replaces_first_score_as_main_card_without_mutation(self):
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        ctx=dict(league="NBA",fixture_id="x",season="2026/2027",
            home=dict(provider_id="1",official_name="Home"),
            away=dict(provider_id="2",official_name="Away"),
            fixture_start_utc=NOW+10800,
            prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        token="abc123abc123"
        markup=InlineKeyboardMarkup([[InlineKeyboardButton("Period",callback_data="zui:"+token+":period")]])
        response=dict(status="ANALYSIS_OK",snapshot=ctx,html="ORIGINAL 220",html_parts=["ORIGINAL 220"],
                      new_record=False,reply_markup=markup)
        base=SimpleNamespace(analyze=AsyncMock(return_value=response))
        _,current=CurrentPanelsTests().setup_case()
        current['source_available_max_utc']=NOW-70
        a=SimpleNamespace(latest=Mock(return_value=current),refresh_fixture=Mock(return_value=dict(status="READY")))
        state=dict(verified_analysis_service=base,
            premium_reports={token:dict(chat_id=1,summary="INITIAL V1 220",
                sections=dict(audit="AUDIT"),section_pages=dict(audit=["AUDIT"]))})
        install_dual_clock_display(state,a)
        with patch("hybrid_engine.current_assessment_ui.time.time",return_value=NOW):
            out=await state["verified_analysis_service"].analyze("NBA","date","home","away")
        self.assertIn("GÜNCEL NBA TAHMİNİ",out["html"])
        self.assertIn("Toplam 218.00",out["html"])
        self.assertNotIn("INITIAL V1 220",out["html"])
        self.assertIn("INITIAL V1 220",state["premium_reports"][token]["sections"]["audit"])
        self.assertEqual(response["html"],"ORIGINAL 220")
        a.refresh_fixture.assert_not_called()

    async def test_missing_current_candidate_identified_as_pending_not_live(self):
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        from hybrid_engine.data import Abstain
        token='c'*12
        ctx=dict(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1',official_name='Home'),
            away=dict(provider_id='2',official_name='Away'),
            fixture_start_utc=NOW+10800,prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        response=dict(status='ANALYSIS_OK',snapshot=ctx,html='V1',html_parts=['V1'],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Periyot',callback_data='zui:'+token+':period')]]),
            new_record=False)
        a=SimpleNamespace(latest=Mock(return_value=None),
            refresh_fixture=Mock(side_effect=Abstain('CURRENT_FIXTURE_OR_ORIGINAL_NOT_ELIGIBLE')))
        queue=SimpleNamespace(request_fixture=Mock(return_value=True))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=response)),
            premium_reports={token:dict(summary='ORIGINAL',sections=dict(audit='AUDIT'),
            section_pages=dict(audit=['AUDIT']))},research_cycle=queue)
        install_dual_clock_display(state,a)
        with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
            out=await state['verified_analysis_service'].analyze('NBA','date','Home','Away')
        self.assertIn('GÜNCEL TAHMİN BEKLENİYOR',out['html'])
        self.assertIn('CURRENT_RESEARCH_BACKGROUND_PENDING',out['html'])
        self.assertNotIn('GÜNCEL NBA TAHMİNİ',out['html'])
        self.assertIn('ORIGINAL',state['premium_reports'][token]['sections']['audit'])
        a.refresh_fixture.assert_not_called()
        queue.request_fixture.assert_called_once_with(ctx)

    async def test_slow_on_demand_retraining_is_never_called_from_analyze(self):
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        token='e'*12
        ctx=dict(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1',official_name='Home'),
            away=dict(provider_id='2',official_name='Away'),
            fixture_start_utc=NOW+10800,prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        response=dict(status='ANALYSIS_OK',snapshot=ctx,html='OLD 220',
            html_parts=['OLD 220'],reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('Periyotlar',callback_data='zui:'+token+':period')]]))
        def prohibit_fit(_):
            raise AssertionError('ON_DEMAND_MODEL_FIT_FORBIDDEN_IN_TELEGRAM_HANDLER')
        a=SimpleNamespace(latest=Mock(return_value=None),
            refresh_fixture=Mock(side_effect=prohibit_fit))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=response)),
            premium_reports={token:dict(summary='OLD 220',sections=dict(period='OLD 1Q',
                ranges='OLD BANDS',market='OLD MARKET',audit='OLD AUDIT'),
                section_pages=dict(audit=['OLD AUDIT']))})
        install_dual_clock_display(state,a)
        with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
            out=await state['verified_analysis_service'].analyze('NBA','date','Home','Away')
        a.refresh_fixture.assert_not_called()
        a.latest.assert_called_once_with(ctx)
        self.assertIn('CURRENT_RESEARCH_BACKGROUND_PENDING',out['html'])
        self.assertNotIn('GÜNCEL NBA TAHMİNİ',out['html'])
        entry=state['premium_reports'][token]
        self.assertIn('CURRENT_ASSESSMENT_NOT_PUBLISHED',entry['sections']['period'])
        self.assertNotIn('OLD BANDS',entry['sections']['ranges'])
        self.assertIn('OLD BANDS',entry['sections']['audit'])

    async def test_no_augmentation_of_non_analysis_results(self):
        response=dict(status="ABSTAIN",html="No verified fixture")
        base=SimpleNamespace(analyze=AsyncMock(return_value=response))
        a=SimpleNamespace(latest=Mock())
        state=dict(verified_analysis_service=base)
        install_dual_clock_display(state,a)
        out=await state["verified_analysis_service"].analyze("NBA","bad")
        self.assertIs(out,response)
        a.latest.assert_not_called()


    async def test_long_archived_forecast_cannot_hide_health_card_from_first_audit_page(self):
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        from hybrid_engine.telegram_premium_ui import page_view
        token='f'*12
        ctx=dict(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1',official_name='Home'),
            away=dict(provider_id='2',official_name='Away'),
            fixture_start_utc=NOW+10800,prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        original_summary='OLD 220\n'+('ORIGINAL ARCHIVE DETAILS\n'*250)
        report=dict(status='ANALYSIS_OK',snapshot=ctx,html='OLD 220',
            html_parts=['OLD 220'],reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('Model / Kaynak',callback_data='zui:'+token+':audit')]]))
        original=dict(summary=original_summary,chat_id=17,
            sections=dict(period='ORIGINAL 1Q 51',ranges='ORIGINAL TOTAL 220',
                market='ORIGINAL OLD MARKET',audit='🛡 <b>TAHMİN SAĞLIK KARTI</b>\n'
                'NOT_CALIBRATED\nOriginal source audit'),
            section_pages=dict(audit=['Old audit before wrapper']))
        a=SimpleNamespace(latest=Mock(return_value=None),
            refresh_fixture=Mock(side_effect=AssertionError('MUST NOT FIT')))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=report)),
            premium_reports={token:original})
        install_dual_clock_display(state,a)
        with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
            await state['verified_analysis_service'].analyze('NBA','day','Home','Away')
        entry=state['premium_reports'][token]
        self.assertGreater(len(entry['section_pages']['audit']),1)
        first,count=page_view(entry,'audit',0,now=NOW)
        self.assertGreater(count,1)
        self.assertIn('TAHMİN SAĞLIK KARTI',first)
        self.assertIn('NOT_CALIBRATED',first)
        self.assertIn('ORIGINAL OLD MARKET',entry['sections']['audit'])
        a.refresh_fixture.assert_not_called()

    async def test_live_candidate_price_appears_in_telegram_market_button(self):
        from core.team_identity import digest
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        context,current=CurrentPanelsTests().setup_case()
        context.update(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1',official_name='Home'),
            away=dict(provider_id='2',official_name='Away'),
            prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        token='b'*12
        row=dict(current=True,fixture_id='x',tipoff_utc=context['fixture_start_utc'],
            period='FULL',market='TOTAL',line=219.5,mean=218.,
            model_digest='bound-research-model',prediction_utc=current['prediction_generated_at_utc'],
            available_at_utc=NOW-30,asof_utc=NOW-20,valid_until_utc=NOW+60,
            prices=dict(over=1.91,under=1.91))
        market_snapshot=dict(current_assessment_sha256=digest(current),
            linked_original_snapshot_sha256=digest(context),
            fixture_id='x',fixture_start_utc=context['fixture_start_utc'],
            prediction_generated_at_utc=current['prediction_generated_at_utc'],
            model_digest='bound-research-model')
        response=dict(status='ANALYSIS_OK',snapshot=context,html='FIRST 220',
            html_parts=['FIRST 220'],reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('Piyasa',callback_data='zui:'+token+':market')]]))
        entry=dict(chat_id=17,summary='FIRST 220',
            sections=dict(audit='HEALTH CARD',period='FIRST 1Q',ranges='FIRST RANGES',
                market='FIRST MARKET'),section_pages=dict(audit=['HEALTH CARD']),
            research_market_snapshot=market_snapshot,research_market_cards=[row])
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=response)),
            premium_reports={token:entry})
        a=SimpleNamespace(latest=Mock(return_value=current))
        install_dual_clock_display(state,a)
        with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW), \
                patch('hybrid_engine.market_direction_ui.render',return_value='<b>VERIFIED 219.5</b>'), \
                patch('hybrid_engine.market_direction_ui.order',side_effect=lambda values:values):
            await state['verified_analysis_service'].analyze('NBA','day','Home','Away')
        market=state['premium_reports'][token]['sections']['market']
        self.assertIn('VERIFIED 219.5',market)
        self.assertNotIn('EŞLEŞMİŞ PİYASA HESABI YOK',market)
        self.assertIn('FIRST MARKET',state['premium_reports'][token]['sections']['audit'])
        self.assertEqual(state['premium_reports'][token]['quote_valid_until_utc'],NOW+60)

    async def test_telegram_cached_buttons_are_rebound_to_same_new_candidate(self):
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        context,latest=CurrentPanelsTests().setup_case()
        context.update(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1',official_name='Home'),
            away=dict(provider_id='2',official_name='Away'),
            prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        latest['source_available_max_utc']=NOW-100
        token='a'*12
        report=dict(status='ANALYSIS_OK',snapshot=context,html='ORIGINAL 220',
            html_parts=['ORIGINAL 220'],reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('Periyotlar',callback_data='zui:'+token+':period')]]))
        original=dict(summary='ORIGINAL SUMMARY 220',chat_id=17,
            sections=dict(period='ORIGINAL 1Q 51',ranges='ORIGINAL P50 220',
                market='ORIGINAL OLD PRICE',audit='🛡 <b>TAHMİN SAĞLIK KARTI</b>\nSOURCE AUDIT'),
            section_pages=dict(audit=['SOURCE AUDIT']))
        a=SimpleNamespace(latest=Mock(return_value=latest),
            refresh_fixture=Mock(return_value=dict(status='READY')))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=report)),
            premium_reports={token:original})
        install_dual_clock_display(state,a)
        with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
            result=await state['verified_analysis_service'].analyze('NBA','day','Home','Away')
        entry=state['premium_reports'][token]
        self.assertIn('Toplam 218.00',result['html'])
        self.assertIn('Toplam 218.00',entry['summary'])
        self.assertIn('<b>1Q</b> 27.00 – 28.00',entry['sections']['period'])
        self.assertIn('P50 218.0',entry['sections']['ranges'])
        self.assertNotIn('ORIGINAL P50 220',entry['sections']['ranges'])
        self.assertIn('ORIGINAL P50 220',entry['sections']['audit'])
        self.assertIn('ORIGINAL OLD PRICE',entry['sections']['audit'])
        self.assertTrue(entry['section_pages']['audit'][0].startswith('🛡 <b>TAHMİN SAĞLIK KARTI</b>'))
        self.assertIn('EŞLEŞMİŞ PİYASA HESABI YOK',entry['sections']['market'])
        a.latest.assert_called_once_with(context)


class CurrentPanelsTests(unittest.TestCase):
    def setup_case(self):
        context=dict(fixture_start_utc=NOW+10000)
        candidate=dict(model='VERIFIED_TEST_CANDIDATE',home=108.,away=110.,total=218.,
            quarters=[[27.,28.],[27.,27.],[27.,27.],[27.,28.]],
            halves=[[54.,55.],[54.,55.]])
        def band(mid):
            return dict(p50=mid,p25=mid-5,p75=mid+5,p10=mid-10,
                        p90=mid+10,p05=mid-15,p95=mid+15)
        row=dict(candidate=candidate,prediction_generated_at_utc=NOW-60,
            parameter_fit_cutoff_utc=NOW-3600,
            intervals=dict(markets=dict(TOTAL=band(218),HOME=band(108),
                AWAY=band(110),MARGIN=band(-2),**{'1Q':band(55),'2Q':band(54),
                                  '3Q':band(54),'4Q':band(55),
                                  '1H':band(109),'2H':band(109)})))
        return context,row

    def test_quote_requires_exact_current_candidate_pin_and_live_price(self):
        from core.team_identity import digest
        from copy import deepcopy
        context,assessment=self.setup_case()
        context.update(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1'),away=dict(provider_id='2'))
        snap=dict(fixture_id=context['fixture_id'],fixture_start_utc=context['fixture_start_utc'],
            prediction_generated_at_utc=assessment['prediction_generated_at_utc'],
            current_assessment_sha256=digest(assessment),
            linked_original_snapshot_sha256=digest(context),
            model_digest='authenticated-market-model')
        card=dict(current=True,fixture_id=context['fixture_id'],
            tipoff_utc=context['fixture_start_utc'],period='FULL',market='TOTAL',
            mean=218.,line=220.5,model_digest=snap['model_digest'],
            prediction_utc=assessment['prediction_generated_at_utc'],
            available_at_utc=NOW-30,asof_utc=NOW-20,valid_until_utc=NOW+60,
            prices=dict(over=1.85,under=1.93))
        entry=dict(research_market_snapshot=snap,research_market_cards=[card])
        self.assertEqual(bound_current_market_cards(context,assessment,entry,now=NOW),[card])
        bad=deepcopy(entry)
        bad['research_market_snapshot']['current_assessment_sha256']='wrong-model-record'
        self.assertEqual(bound_current_market_cards(context,assessment,bad,now=NOW),[])
        bad=deepcopy(entry)
        bad['research_market_cards'][0]['mean']=225.
        self.assertEqual(bound_current_market_cards(context,assessment,bad,now=NOW),[])
        self.assertEqual(bound_current_market_cards(context,assessment,entry,now=NOW+61),[])
        bad=deepcopy(entry)
        bad['research_market_cards'][0]['current']=False
        self.assertEqual(bound_current_market_cards(context,assessment,bad,now=NOW),[])
        bad=deepcopy(entry)
        bad['research_market_cards'][0]['prices']={}
        self.assertEqual(bound_current_market_cards(context,assessment,bad,now=NOW),[])

    def test_period_and_range_buttons_use_current_record_not_first_prediction(self):
        context,row=self.setup_case()
        panels=current_panels(context,row,now=NOW)
        self.assertTrue(panels['fresh'])
        self.assertIn('<b>Maç toplamı:</b> 218.00',panels['period'])
        self.assertIn('<b>1Q</b> 27.00 – 28.00',panels['period'])
        self.assertIn('P50 218.0',panels['ranges'])
        self.assertNotIn('220.00',panels['period']+panels['ranges'])
        self.assertEqual(panels['valid_until'],NOW+3540)

    def test_conflicting_scores_and_nonmonotone_quantiles_are_rejected(self):
        from copy import deepcopy
        context,row=self.setup_case()
        wrong=deepcopy(row)
        wrong['candidate']['total']=219.
        blocked=current_panels(context,wrong,now=NOW)
        self.assertFalse(blocked['fresh'])
        self.assertIn('SCORE_CONSERVATION_FAILED',blocked['period'])
        wrong=deepcopy(row)
        wrong['intervals']['markets']['TOTAL']['p25']=300.
        blocked=current_panels(context,wrong,now=NOW)
        self.assertFalse(blocked['fresh'])
        self.assertIn('CURRENT_DISTRIBUTION_NOT_VERIFIED',blocked['ranges'])

    def test_stale_or_incomplete_current_record_never_reuses_archive_periods(self):
        context,row=self.setup_case()
        self.assertFalse(current_panels(context,row,now=NOW+3601)['fresh'])
        broken=dict(row,candidate=dict(row['candidate'],quarters=[]))
        panels=current_panels(context,broken,now=NOW)
        self.assertFalse(panels['fresh'])
        self.assertIn('CURRENT_PERIOD_PATHS_NOT_VERIFIED',panels['period'])
        self.assertNotIn('220.',panels['period'])
        self.assertIn('Model / Kaynak',panels['ranges'])

    def test_expired_button_view_is_explicitly_archived(self):
        from hybrid_engine.telegram_premium_ui import page_view
        context,row=self.setup_case()
        panels=current_panels(context,row,now=NOW)
        entry=dict(summary='CURRENT 218',sections=dict(period=panels['period'],
            ranges=panels['ranges']),section_pages=dict(period=[panels['period']],
            ranges=[panels['ranges']]),current_assessment_panels=True,
            current_assessment_valid_until_utc=panels['valid_until'],
            tipoff_utc=context['fixture_start_utc'])
        active,_=page_view(entry,'period',0,now=NOW)
        expired,_=page_view(entry,'period',0,now=NOW+3600)
        self.assertNotIn('ARTIK GÜNCEL DEĞİL',active)
        self.assertIn('ARTIK GÜNCEL DEĞİL',expired)
        range_text,_=page_view(entry,'ranges',0,now=NOW+3600)
        self.assertIn('ARTIK GÜNCEL DEĞİL',range_text)
