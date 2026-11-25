"""Two-clock user display: original and published current score remain distinct."""
from types import SimpleNamespace
import asyncio
import threading
import unittest
from unittest.mock import AsyncMock,Mock,patch

from hybrid_engine.current_assessment_ui import two_clock_text,install_dual_clock_display,current_panels,bound_current_market_cards,bound_audit_provenance,missing_current_market_card

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
        self.assertIn("ÖNCEKİ V3 KAYDINDAN",text)
        self.assertIn("Bu /analyze komutunda yeni V3 skor hesaplanmadı",text)
        self.assertIn("İlk V1 arşiv kaydı maç kimliği ve karşılaştırma için okundu",text)
        self.assertIn("Kayıttaki en geç kaynak kabul zamanı",text)
        self.assertNotIn("Yeni hesaplama:",text)
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




class IndexedCurrentFixtureTests(unittest.TestCase):
    """An interactive NBA read must not reopen all unrelated publications."""

    def test_last_hour_slot_index_avoids_full_archive_scan(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from core.team_identity import digest
        from hybrid_engine.current_assessment import AssessmentRegistry,POLICY
        with TemporaryDirectory() as directory:
            reg=AssessmentRegistry(Path(directory))
            slot_now=NOW//POLICY['refresh_seconds']
            protocol='verified-study-sha'
            expected=[]
            for hour in (slot_now-1,slot_now):
                version=protocol+':'+str(hour)
                p=reg.root/('first-'+digest(dict(fixture='fixture-1',version=version))+'.json')
                p.write_text('{}')
                expected.append(p)
            # An unrelated fixture must never be opened, even if it exists.
            other=reg.root/('first-'+digest(dict(fixture='unrelated',version=protocol+':'+str(slot_now)))+'.json')
            other.write_text('{}')
            versions={p:protocol+':'+str(h) for p,h in zip(expected,(slot_now-1,slot_now))}
            def checked(slot):
                return dict(payload=dict(fixture=dict(canonical_id='fixture-1'),
                    version=versions[slot],prediction_generated_at_utc=NOW-30))
            with patch.object(reg,'_verified_slot',side_effect=checked) as verified:
                out=reg.recent_fixture('fixture-1',protocol,now_utc=NOW)
            self.assertEqual(len(out),2)
            self.assertEqual([call.args[0] for call in verified.call_args_list],expected)
            self.assertNotIn(other,[call.args[0] for call in verified.call_args_list])

    def test_old_slot_not_used_as_current_without_archive_replay(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from core.team_identity import digest
        from hybrid_engine.current_assessment import AssessmentRegistry,POLICY
        with TemporaryDirectory() as directory:
            reg=AssessmentRegistry(Path(directory))
            prior=NOW//POLICY['refresh_seconds']-3
            slot=reg.root/('first-'+digest(dict(fixture='fixture-1',version='study:'+str(prior)))+'.json')
            slot.write_text('{}')
            with patch.object(reg,'_verified_slot',side_effect=AssertionError('stale read forbidden')):
                self.assertEqual(reg.recent_fixture('fixture-1','study',now_utc=NOW),[])

    def test_recent_publication_still_checks_original_pin_and_assets(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from core.team_identity import digest
        from hybrid_engine.current_assessment import CurrentAssessments
        with TemporaryDirectory() as directory:
            service=CurrentAssessments(Path(directory),worker=None,study=None)
            (service.root/'policy.json').write_text('{}')
            ctx=dict(league='NBA',season='2026/2027',fixture_id='fixture-1',
                fixture_start_utc=NOW+10800,
                home=dict(provider_id='home',official_name='Home'),
                away=dict(provider_id='away',official_name='Away'))
            item=dict(original_snapshot_sha256=digest(ctx),
                prediction_generated_at_utc=NOW-30,
                fixture=dict(canonical_id='fixture-1',league='NBA',season='2026/2027',
                    fixture_start_utc=ctx['fixture_start_utc'],
                    home_team_id='home',away_team_id='away'))
            service.plan=Mock(return_value=dict(sha256='study'))
            service.registry.recent_fixture=Mock(return_value=[dict(payload=item)])
            service.registry.records=Mock(side_effect=AssertionError('full archive scan forbidden'))
            service.registry.validate_assets=Mock()
            with patch('hybrid_engine.current_assessment.time.time',return_value=NOW):
                self.assertIs(service.latest_display(ctx),item)
            service.registry.recent_fixture.assert_called_once_with('fixture-1','study',now_utc=NOW)
            service.registry.records.assert_not_called()
            service.registry.validate_assets.assert_called_once_with(item)
            item['original_snapshot_sha256']='corrupted-original'
            with self.assertRaisesRegex(ValueError,'CURRENT_ASSESSMENT_ORIGINAL_PIN'):
                service.latest_display(ctx)
            service.registry.validate_assets=Mock(side_effect=ValueError('CURRENT_ASSET_PIN'))
            with self.assertRaisesRegex(ValueError,'CURRENT_ASSET_PIN'):
                service.latest_display(ctx)


class MarketMissingPricePanelTests(unittest.TestCase):
    def test_current_v3_model_reference_with_provider_failure_not_invented_quote(self):
        context,candidate=CurrentPanelsTests().setup_case()
        panels=current_panels(context,candidate,now=NOW)
        self.assertTrue(panels['fresh'])
        result=missing_current_market_card(candidate,
            dict(research_market_source_status='KEY_NOT_AVAILABLE_IN_TEST_PROCESS'),panels)
        self.assertIn('EŞLEŞMİŞ PİYASA HESABI YOK',result)
        self.assertIn('KEY_NOT_AVAILABLE_IN_TEST_PROCESS',result)
        self.assertIn('V3 MODEL REFERANSI — BAHİS BAREMİ DEĞİLDİR',result)
        self.assertIn('Model maç toplamı: 218.00',result)
        self.assertIn('NOT_CALIBRATED',result)
        self.assertNotIn('Oranlar:',result)
        self.assertNotIn('219.5',result)
        self.assertIn('Model takım toplamları',result)
        self.assertGreaterEqual(result.count('\n'),5)

    def test_stale_candidate_never_shows_stale_model_reference_as_current_market(self):
        context,candidate=CurrentPanelsTests().setup_case()
        stale=current_panels(context,candidate,now=NOW+2701)
        self.assertFalse(stale['fresh'])
        result=missing_current_market_card(candidate,dict(
            research_market_source_status='PROVIDER_QUOTA_EXHAUSTED'),stale)
        self.assertIn('PROVIDER_QUOTA_EXHAUSTED',result)
        self.assertIn('güncel doğrulanmış V3 sayı paketi yok'.casefold(),result.casefold())
        self.assertNotIn('Model maç toplamı: 218.00',result)

    def test_untrusted_provider_status_is_never_injected_into_html(self):
        result=missing_current_market_card(None,dict(
            research_market_source_status='<b>INJECTED</b>'),dict(fresh=False))
        self.assertIn('PROVIDER_STATUS_UNAVAILABLE',result)
        self.assertNotIn('INJECTED',result)


class ModelSourceBoundaryTests(unittest.TestCase):
    def test_current_model_does_not_inherit_original_health_card_metrics(self):
        from core.team_identity import digest
        context, candidate=CurrentPanelsTests().setup_case()
        candidate['candidate']['model']='NEW_RESEARCH_MODEL'
        candidate['source_available_max_utc']=NOW-30
        panels=current_panels(context,candidate,now=NOW)
        original=('🛡 <b>TAHMİN SAĞLIK KARTI</b>\n'
                  'Durum: LIMITED_RESEARCH\nAynı fit SHA: 54\n'
                  'Geçmiş toplam MAE: 16.71\n'
                  '<b>MODEL DENETİMİ</b>\nModel: ORIGINAL_V1')
        shown=bound_audit_provenance(original,candidate,panels)
        self.assertTrue(shown.startswith('🛡 <b>TAHMİN SAĞLIK KARTI</b>'))
        self.assertIn('KAPSAM: İLK KAYITLI V1 TAHMİNİ',shown)
        self.assertIn('NEW_RESEARCH_MODEL',shown)
        self.assertIn(digest(candidate)[:16],shown)
        self.assertIn('İlk V1 sağlık kartı bu adaya taşınmadı',shown)
        self.assertIn('KÖKEN: V3 tahmini kendi doğrulanmış aday arşivinden okundu.',shown)
        self.assertIn('V1 skor ve periyot değerleri V3 skoru olarak kopyalanmadı.',shown)
        self.assertIn('Model: ORIGINAL_V1',shown)
        self.assertIn('Geçmiş toplam MAE: 16.71',shown)
        self.assertLess(shown.index('AYRI GÜNCEL ARAŞTIRMA ADAYI'),shown.index('<b>MODEL DENETİMİ</b>'))
        self.assertEqual(shown.count('Geçmiş toplam MAE: 16.71'),1)

    def test_missing_candidate_keeps_original_card_but_no_current_model_claim(self):
        original=('🛡 <b>TAHMİN SAĞLIK KARTI</b>\n'
                  'NOT_CALIBRATED\n<b>MODEL DENETİMİ</b>\nOriginal V1')
        shown=bound_audit_provenance(original,None,dict(fresh=False))
        self.assertIn('GÜNCEL ARAŞTIRMA ADAYI DENETİMİ YOK',shown)
        self.assertNotIn('Aday kayıt SHA:',shown)
        self.assertIn('Original V1',shown)
        self.assertTrue(shown.startswith('🛡 <b>TAHMİN SAĞLIK KARTI</b>'))


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
        self.assertIn("<b>Home – Away</b>",out["html"])
        self.assertIn("Kayıtlı V3 · ",out["html"])
        self.assertIn("Beklenen toplam  218,0",out["html"])
        self.assertNotIn("INITIAL V1 220",out["html"])
        self.assertIn("INITIAL V1 220",state["premium_reports"][token]["sections"]["archive"])
        self.assertNotIn("INITIAL V1 220",state["premium_reports"][token]["sections"]["audit"])
        self.assertEqual(response["html"],"ORIGINAL 220")
        a.refresh_fixture.assert_not_called()

    async def test_slow_optional_sources_do_not_prevent_current_candidate_display(self):
        """Reproduces provider/panel TimeoutError before candidate lookup."""
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        from hybrid_engine.isolated_execution import IsolatedExecutor,optional_source_thread

        asyncio.get_running_loop().set_default_executor(IsolatedExecutor())
        release=threading.Event()
        ctx=dict(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1',official_name='Home'),
            away=dict(provider_id='2',official_name='Away'),
            fixture_start_utc=NOW+10800,prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        token='b'*12
        report=dict(status='ANALYSIS_OK',snapshot=ctx,html='OLD 220',
            html_parts=['OLD 220'],reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('Periyotlar',callback_data='zui:'+token+':period')]]))
        async def base_analyze(*args):
            for _ in range(2):
                try:
                    await asyncio.wait_for(
                        optional_source_thread(lambda:release.wait(3)),timeout=.04)
                except TimeoutError:
                    pass
            return report
        _,current=CurrentPanelsTests().setup_case()
        current['source_available_max_utc']=NOW-70
        assessments=SimpleNamespace(latest=Mock(return_value=current))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=base_analyze),
            premium_reports={token:dict(chat_id=1,summary='OLD 220',
                sections=dict(audit='AUDIT',period='OLD Q',ranges='OLD BAND',
                    market='OLD MARKET'),
                section_pages=dict(audit=['AUDIT']))})
        install_dual_clock_display(state,assessments)
        try:
            with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
                out=await asyncio.wait_for(
                    state['verified_analysis_service'].analyze('NBA','day','Home','Away'),
                    timeout=1.5)
            self.assertIn('Kayıtlı V3 · ',out['html'])
            self.assertIn('Beklenen toplam  218,0',out['html'])
            self.assertIn('Medyan 218',state['premium_reports'][token]['sections']['ranges'])
            assessments.latest.assert_called_once_with(ctx)
        finally:
            release.set()

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
        self.assertNotIn('Beklenen toplam  ',out['html'])
        self.assertIn('ORIGINAL',state['premium_reports'][token]['sections']['archive'])
        self.assertIn('İLK KAYITLI V1 REFERANSI — V3 DEĞİL',out['html'])
        a.refresh_fixture.assert_not_called()
        queue.request_fixture.assert_called_once_with(ctx)

    async def test_python310_asyncio_timeout_is_bounded_without_false_v3_score(self):
        """Python 3.10 asyncio.TimeoutError is distinct from built-in TimeoutError.

        Simulate the legacy exception even when CI itself runs on Python 3.11+.
        """
        class LegacyAsyncioTimeout(Exception):
            pass

        ctx=dict(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1',official_name='Home'),
            away=dict(provider_id='2',official_name='Away'),
            fixture_start_utc=NOW+10800,prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        response=dict(status='ANALYSIS_OK',snapshot=ctx,html='FIRST V1 220',
            html_parts=['FIRST V1 220'],new_record=False)
        a=SimpleNamespace(latest=Mock())
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=response)))
        install_dual_clock_display(state,a)

        async def legacy_timeout(awaitable, *, timeout):
            awaitable.close()  # Simulated wait_for never scheduled the read.
            raise LegacyAsyncioTimeout('EXPIRED')

        with patch('hybrid_engine.current_assessment_ui.asyncio.TimeoutError',LegacyAsyncioTimeout), \
                patch('hybrid_engine.current_assessment_ui.asyncio.wait_for',legacy_timeout), \
                patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
            out=await state['verified_analysis_service'].analyze('NBA','day','Home','Away')
        self.assertIn('CURRENT_READ_TIMEOUT',out['html'])
        self.assertIn('GÜNCEL TAHMİN DOĞRULANAMADI',out['html'])
        self.assertNotIn('GÜNCEL AYRI ARAŞTIRMA SKORU',out['html'])
        self.assertIn('FIRST V1 220',out['html'])
        a.latest.assert_not_called()

    async def test_stuck_v3_archive_reader_returns_bounded_telegram_blocker(self):
        """A slow verified archive cannot consume the entire analyze window.

        Timeout does not return the older V1 figures as current V3 numbers.
        """
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        from hybrid_engine.current_assessment_ui import CURRENT_READ_DEADLINE_SECONDS

        release=threading.Event()
        ctx=dict(league='NBA',fixture_id='x',season='2026/2027',
            home=dict(provider_id='1',official_name='Home'),
            away=dict(provider_id='2',official_name='Away'),
            fixture_start_utc=NOW+10800,prediction_generated_at_utc=NOW-86400,
            prediction=dict(home=105.,away=115.,total=220.))
        token='a'*12
        response=dict(status='ANALYSIS_OK',snapshot=ctx,html='FIRST V1 220',
            html_parts=['FIRST V1 220'],new_record=False,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('Period',callback_data='zui:'+token+':period')]]))
        def slow_read(_):
            release.wait(3)
            return None
        latest=Mock(side_effect=slow_read)
        queue=SimpleNamespace(request_fixture=Mock(return_value=True))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=response)),
            premium_reports={token:dict(summary='FIRST V1 220',
                sections=dict(audit='V1 AUDIT',period='V1 FIRST Q',ranges='V1 BANDS',market='V1 PRICE'),
                section_pages=dict(audit=['V1 AUDIT']))},
            research_cycle=queue)
        install_dual_clock_display(state,SimpleNamespace(latest=latest))
        try:
            with patch('hybrid_engine.current_assessment_ui.CURRENT_READ_DEADLINE_SECONDS',.04), \
                    patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
                result=await asyncio.wait_for(
                    state['verified_analysis_service'].analyze('NBA','day','Home','Away'),
                    timeout=.7)
            self.assertIn('CURRENT_READ_TIMEOUT',result['html'])
            self.assertIn('GÜNCEL TAHMİN BEKLENİYOR',result['html'])
            self.assertNotIn('Beklenen toplam  ',result['html'])
            entry=state['premium_reports'][token]
            self.assertIn('V1 FIRST Q',entry['sections']['archive'])
            self.assertIn('V1 BANDS',entry['sections']['archive'])
            self.assertIn('CURRENT_ASSESSMENT_NOT_PUBLISHED',entry['sections']['period'])
            self.assertIn('İLK V1 REFERANSI — GÜNCEL V3 DEĞİL',entry['sections']['period'])
            self.assertIn('V1 FIRST Q',entry['sections']['period'])
            queue.request_fixture.assert_called_once_with(ctx)
            latest.assert_called_once_with(ctx)
        finally:
            release.set()

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
        self.assertNotIn('Beklenen toplam  ',out['html'])
        entry=state['premium_reports'][token]
        self.assertIn('CURRENT_ASSESSMENT_NOT_PUBLISHED',entry['sections']['period'])
        self.assertIn('İLK V1 REFERANSI — GÜNCEL V3 DEĞİL',entry['sections']['ranges'])
        self.assertIn('OLD BANDS',entry['sections']['ranges'])
        self.assertIn('OLD BANDS',entry['sections']['archive'])
        self.assertNotIn('OLD BANDS',entry['sections']['audit'])
        self.assertIn('V1 İlk Tahmin',entry['sections']['period'])

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
        self.assertGreater(len(entry['section_pages']['archive']),1)
        first,count=page_view(entry,'audit',0,now=NOW)
        self.assertEqual(count,len(entry['section_pages']['audit']))
        self.assertIn('TAHMİN SAĞLIK KARTI',first)
        self.assertIn('NOT_CALIBRATED',first)
        self.assertIn('ORIGINAL OLD MARKET',entry['sections']['archive'])
        self.assertNotIn('ORIGINAL OLD MARKET',entry['sections']['audit'])
        first_archived,_=page_view(entry,'archive',0,now=NOW)
        self.assertIn('V1 İLK TAHMİN',first_archived)
        self.assertIn('OLD 220',first_archived)
        a.refresh_fixture.assert_not_called()

    async def test_live_candidate_price_appears_in_telegram_market_button(self):
        from core.team_identity import digest
        from telegram import InlineKeyboardButton,InlineKeyboardMarkup
        context,current=CurrentPanelsTests().setup_case()
        current['source_available_max_utc']=NOW-70
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
            prices=dict(over=1.91,under=1.91),bookmaker=dict(name='Test Book'),
            side='under',probability=.54)
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
        from hybrid_engine.telegram_premium_ui import page_view
        fresh, _ = page_view(entry,'summary',0,now=NOW)
        expired, _ = page_view(entry,'summary',0,now=NOW+60)
        self.assertIn('Piyasa gözlemi</b> · Test Book',fresh)
        self.assertIn('Barem 219,5',fresh)
        self.assertIn('Ham %54,0',fresh)
        self.assertIn('Ödeme kapsamı doğrulanmadı',fresh)
        self.assertLess(expired.index('Beklenen toplam'),expired.index('Arşiv fiyatı'))
        self.assertNotIn('Piyasa gözlemi',expired)
        self.assertLess(len(fresh),600)
        self.assertIn('VERIFIED 219.5',market)
        self.assertIn('ZAMAN DAMGALI FİYAT GÖZLEMİ',market)
        self.assertIn('Ham NORMAL SÜRE simülasyonu',market)
        self.assertIn('uzatma ve ödeme kuralları doğrulanmadı',market)
        self.assertNotIn('DOĞRULANMIŞ FİYATLAR',market)
        self.assertNotIn('EŞLEŞMİŞ PİYASA HESABI YOK',market)
        self.assertIn('FIRST MARKET',state['premium_reports'][token]['sections']['archive'])
        self.assertIn('FIRST MARKET',market)
        self.assertIn('BAĞIMSIZ ÖNCEKİ MODEL / PİYASA İNCELEMESİ',market)
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
            section_pages=dict(audit=['SOURCE AUDIT']),
            research_market_source_status='KEY_NOT_AVAILABLE_IN_TEST_PROCESS')
        a=SimpleNamespace(latest=Mock(return_value=latest),
            refresh_fixture=Mock(return_value=dict(status='READY')))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=report)),
            premium_reports={token:original})
        install_dual_clock_display(state,a)
        with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
            result=await state['verified_analysis_service'].analyze('NBA','day','Home','Away')
        entry=state['premium_reports'][token]
        self.assertIn('Beklenen toplam  218,0',result['html'])
        self.assertIn('Beklenen toplam  218,0',entry['summary'])
        self.assertIn('1. çeyrek   27,0 – 28,0',entry['sections']['period'])
        self.assertIn('Medyan 218',entry['sections']['ranges'])
        self.assertIn('Kayıtlı V3',entry['sections']['period'])
        pages = entry['section_pages']['ranges']
        self.assertEqual(len(pages),3)
        self.assertIn('Maç ve takımlar',pages[0])
        self.assertIn('Çeyrekler',pages[1])
        self.assertIn('Yarılar',pages[2])
        self.assertTrue(all(len(page)<640 for page in pages))
        self.assertEqual(entry['section_pages']['period'],[entry['sections']['period']])
        self.assertTrue(result['compact_candidate_summary'])
        self.assertNotIn('ORIGINAL P50 220',entry['sections']['ranges'])
        self.assertIn('ORIGINAL P50 220',entry['sections']['archive'])
        self.assertNotIn('ORIGINAL P50 220',entry['sections']['audit'])
        self.assertIn('ORIGINAL OLD PRICE',entry['sections']['archive'])
        self.assertNotIn('ORIGINAL OLD PRICE',entry['sections']['audit'])
        self.assertIn('BAĞIMSIZ ÖNCEKİ MODEL / PİYASA İNCELEMESİ',entry['sections']['market'])
        self.assertIn('ORIGINAL OLD PRICE',entry['sections']['market'])
        self.assertTrue(entry['section_pages']['audit'][0].startswith('🛡 <b>TAHMİN SAĞLIK KARTI</b>'))
        self.assertIn('EŞLEŞMİŞ PİYASA HESABI YOK',entry['sections']['market'])
        self.assertIn('KEY_NOT_AVAILABLE_IN_TEST_PROCESS',entry['sections']['market'])
        self.assertIn('V3 MODEL REFERANSI',entry['sections']['market'])
        self.assertIn('Model maç toplamı: 218.00',entry['sections']['market'])
        from hybrid_engine.telegram_premium_ui import page_view
        callbacks=[b.callback_data for row in result['reply_markup'].inline_keyboard for b in row]
        self.assertIn('zui:'+token+':archive',callbacks)
        self.assertIn('zui:'+token+':period',callbacks)
        self.assertIn('zui:'+token+':audit',callbacks)
        archived,count=page_view(entry,'archive',1,now=NOW)
        self.assertGreaterEqual(count,4)
        self.assertIn('ORIGINAL 1Q 51',archived)
        self.assertNotIn('Medyan 218',archived)
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
        row=dict(candidate=candidate,prediction_generated_at_utc=NOW-60,source_available_max_utc=NOW-70,
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
        self.assertIn('<b>Maç toplamı  218,0',panels['period'])
        self.assertIn('1. çeyrek   27,0 – 28,0',panels['period'])
        self.assertIn('Medyan 218',panels['ranges'])
        self.assertNotIn('220.00',panels['period']+panels['ranges'])
        self.assertEqual(panels['valid_until'],NOW+2640)

    def test_45_minute_freshness_boundary_and_24_hour_fit_age(self):
        from copy import deepcopy
        context,row=self.setup_case()
        generated=row['prediction_generated_at_utc']
        self.assertTrue(current_panels(context,row,now=generated+2700)['fresh'])
        expired=current_panels(context,row,now=generated+2701)
        self.assertFalse(expired['fresh'])
        self.assertIn('STALE_OR_STARTED',expired['period'])
        aged=deepcopy(row)
        aged['parameter_fit_cutoff_utc']=NOW-7*3600
        self.assertTrue(current_panels(context,aged,now=NOW)['fresh'])
        self.assertIn('6 saatten eski',current_panels(context,aged,now=NOW)['period'])
        aged['parameter_fit_cutoff_utc']=NOW-24*3600-1
        self.assertFalse(current_panels(context,aged,now=NOW)['fresh'])

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
        self.assertNotIn('220,0',panels['period'])
        self.assertIn('V1 İlk Tahmin',panels['ranges'])

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

class EuropeCurrentDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_status_no_longer_skips_europe_candidate_and_preserves_original(self):
        from telegram import InlineKeyboardMarkup,InlineKeyboardButton
        token='c'*12
        context=dict(league='EUROLEAGUE',fixture_id='e',fixture_start_utc=NOW+10000)
        response=dict(status='EUROPE_HYBRID_OK',html='ORIGINAL BAYES',html_parts=['ORIGINAL BAYES'],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Piyasa',callback_data='zui:'+token+':market')]]))
        entry=dict(europe_context=context,summary='ORIGINAL BAYES',
            sections=dict(period='OLD Q',ranges='OLD RANGE',market='OLD PRICE',audit='OLD AUDIT'),
            section_pages=dict(period=['OLD Q'],ranges=['OLD RANGE'],market=['OLD PRICE'],audit=['OLD AUDIT']))
        queue=SimpleNamespace(request_fixture=Mock(return_value=True))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=response)),
                   premium_reports={token:entry},research_cycle=queue)
        a=SimpleNamespace(latest=Mock(return_value=None))
        install_dual_clock_display(state,a)
        with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
            out=await state['verified_analysis_service'].analyze('EUROLEAGUE','day','h','a')
        self.assertIn('AVRUPA GÜNCEL ARAŞTIRMA ADAYI YAYIMLANMADI',out['html'])
        self.assertIn('ORIGINAL BAYES',out['html'])
        self.assertEqual(entry['sections']['market'],'OLD PRICE')
        queue.request_fixture.assert_called_once_with(context)

    async def test_fresh_europe_candidate_owns_numeric_buttons_first_bayes_in_archive(self):
        from telegram import InlineKeyboardMarkup,InlineKeyboardButton
        token='d'*12
        context,row=CurrentPanelsTests().setup_case()
        context=dict(context,league='EUROLEAGUE')
        response=dict(status='EUROPE_HYBRID_OK',html='ORIGINAL BAYES',html_parts=['ORIGINAL BAYES'],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Piyasa',callback_data='zui:'+token+':market')]]))
        entry=dict(europe_context=context,summary='ORIGINAL BAYES',
            sections=dict(period='OLD Q',ranges='OLD RANGE',market='OLD PRICE',audit='OLD AUDIT'),
            section_pages=dict(period=['OLD Q'],ranges=['OLD RANGE'],market=['OLD PRICE'],audit=['OLD AUDIT']))
        state=dict(verified_analysis_service=SimpleNamespace(analyze=AsyncMock(return_value=response)),
                   premium_reports={token:entry})
        install_dual_clock_display(state,SimpleNamespace(latest=Mock(return_value=row)))
        with patch('hybrid_engine.current_assessment_ui.time.time',return_value=NOW):
            out=await state['verified_analysis_service'].analyze('EUROLEAGUE','day','h','a')
        self.assertIn('AVRUPA GÜNCEL TEMPO',out['html'])
        self.assertIn('218,0',entry['sections']['period'])
        self.assertNotIn('OLD Q',entry['sections']['period'])
        self.assertNotIn('OLD RANGE',entry['sections']['ranges'])
        self.assertIn('OLD Q',entry['sections']['archive'])
        self.assertIn('OLD RANGE',entry['sections']['archive'])
        self.assertEqual(entry['sections']['market'],'OLD PRICE')
