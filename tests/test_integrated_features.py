"""Functional activation is separate from promotion; all transport here is synthetic."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from telegram import Update

from hybrid_engine.integrated_features import features, models, score
from tests import test_europe_premium_ui as ui
from tests import test_issue90 as issue90


class ModelViewTests(TestCase):
    def setUp(self):
        h=issue90.Issue90ForwardTests('runTest');h.setUp()
        self.addCleanup(h.doCleanups);self.h=h
        h.study.admit(h.case,h.plan);h.study.capture(h.case,h.model,h.plan)
        self.row=dict(fixture_id=h.case['target']['fixture_id'],snapshot_sha256=h.case['original'],
            model_digest='a'*64,model_version='FROZEN',prediction=[110.,111.])
        self.reader=SimpleNamespace(read=Mock(return_value=dict(report=dict(report=dict(
            status='VERIFIED_LIVE_REPORT',forecasts=[self.row])))))
        h.worker.render=Mock(return_value='V2: kayıtlı ayrı araştırma çıktısı')
        self.state=dict(ledger_reports=self.reader,adaptive_v2_worker=h.worker,issue90_research=h.study)

    def files(self):
        return {str(p):p.read_bytes() for p in self.h.study.root.rglob('*') if p.is_file()}

    def view(self):return models(self.state,'NBA','401123456')

    def test_recorded_v3_score_visible_before_model_promotion_without_new_inference(self):
        before=self.files()
        for method in ('plan','capture','tick'):
            guard=patch.object(self.h.study,method,side_effect=AssertionError('VIEW_MUST_NOT_WRITE'))
            guard.start();self.addCleanup(guard.stop)
        with (patch('hybrid_engine.nba_dynamic.fit',side_effect=AssertionError('NO_FIT')),
              patch('hybrid_engine.nba_dynamic.predict',side_effect=AssertionError('NO_INFERENCE'))):
            text=self.view()
        pred=self.h.study.registry.records()[0]['payload']['candidate']
        self.assertIn('Kayıtlı FROZEN: 110.00 – 111.00',text)
        self.assertIn('V3 ayrı PREMATCH: '+score(pred),text)
        self.assertIn('V2: kayıtlı ayrı araştırma çıktısı',text)
        self.assertIn('otomatik terfi yapılmaz',text);self.assertEqual(before,self.files())
        self.reader.read.assert_called_once_with('NBA','401123456')

    def test_different_original_snapshot_is_not_presented_as_same_model_case(self):
        self.row['snapshot_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'ORIGINAL_SNAPSHOT_CONFLICT'):self.view()

    def test_changed_source_plan_refuses_current_version_claim_without_reset(self):
        before=self.files()
        with patch('hybrid_engine.issue90_research.pins',return_value={}):
            with self.assertRaisesRegex(ValueError,'CURRENT_PLAN_REQUIRED'):self.view()
        self.assertEqual(before,self.files())

    def test_absent_plan_does_not_create_plan_or_directories(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/'not-created'
            self.state['issue90_research']=SimpleNamespace(root=root)
            self.assertIn('kayıtlı plan bekleniyor',self.view());self.assertFalse(root.exists())

    def test_missing_current_publication_has_no_fabricated_v3_score(self):
        self.row['fixture_id']='another'
        self.assertNotIn('V3 ayrı PREMATCH:',self.view())
        self.assertIn('doğrulanmış ayrı yayın yok',self.view())

    def test_european_wrapped_reports_show_each_original_component(self):
        self.row['model_version']='BAYES_QMC'
        text=models(self.state,'EUROCUP','U2026_119')
        self.assertIn('Kayıtlı BAYES_QMC:',text);self.assertNotIn('V3 ayrı PREMATCH:',text)

    def test_provider_health_reports_real_setup_without_network_requests(self):
        class Provider:
            def public_status(self):
                return dict(last_source_status='INJURY_PROVIDER_HTTP_ERROR',last_http_status=429)
        self.state.update(europe_injury_advisory_enabled=True,
            europe_injury_advisory_setup_status='CONFIGURED_UNVERIFIED',
            europe_data_review=SimpleNamespace(injury_advisory_getter=Provider()))
        value=features(self.state)
        self.assertIn('CONFIGURED_UNVERIFIED',value)
        self.assertIn('INJURY_PROVIDER_HTTP_ERROR · HTTP 429',value)
        self.assertIn('CANLI ANALİZE BAĞLI DEĞİL',value)

    def test_rotowire_security_hold_is_visible_without_source_activity(self):
        self.state.update(europe_injury_advisory_enabled=False,
                          europe_injury_advisory_setup_status='SECURITY_HOLD_ROTOWIRE')
        value=features(self.state)
        self.assertIn('SECURITY_HOLD_ROTOWIRE',value)
        self.assertIn('KAYNAK_ETKİN_DEĞİL; İSTEK_YAPILMADI',value)
        self.assertIn('CANLI ANALİZE BAĞLI DEĞİL',value)

    def test_loaded_status_is_independent_of_a_failed_acceptance_gate(self):
        self.state.update(acceptance='NO_GO',verified_analysis_service=object(),
            europe_services={'EUROLEAGUE':object(),'EUROCUP':object()})
        text=features(self.state)
        self.assertIn('Ana analiz yönlendiricisi: YÜKLÜ',text)
        self.assertIn('V3 rakip / form / korelasyonlu periyot adayı: YÜKLÜ',text)
        self.assertIn('yukarıdaki işlevleri kapatmaz',text)
        self.assertNotIn('NO_GO',text)


class IntegratedCommandTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await ui.EuropeanButtonTests.asyncSetUp(self)

    async def command(self,text,chat=17):
        self.seq+=1
        update=Update.de_json(dict(update_id=self.seq,message=dict(message_id=self.seq,date=self.clock,
            chat=dict(id=chat,type='private'),**{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
            text=text,entities=[dict(type='bot_command',offset=0,length=len(text.split()[0]))])),self.app.bot)
        await self.app.process_update(update)

    async def test_new_commands_and_three_league_results_reach_real_handlers(self):
        # Real PTB routing and native report readers, synthetic provider/API only.
        before=self.nba.ledger.path.read_bytes()
        for command,expected in (
            ('/features','ETKİN ÖZELLİKLER'),
            ('/models NBA 401000123','AYNI MAÇTA AYRI MODEL'),
            ('/results all','ORİJİNAL TAHMİN'),
            ('/accuracy all','ÜÇ LİG AYRI MODEL PERFORMANSI')):
            start=len(self.api.sent);await self.command(command)
            self.assertGreater(len(self.api.sent),start,command)
            self.assertIn(expected,'\n'.join(self.api.sent[start:]))
        self.assertEqual(before,self.nba.ledger.path.read_bytes())
        self.nba.analyze.assert_not_awaited()

    async def test_european_model_command_shows_stored_scores_without_source_queries(self):
        report=await ui.EuropeanButtonTests.open(self,'EUROCUP')
        n=len(self.sources['EUROCUP'].calls)
        before=ui.EuropeanButtonTests.files(self)
        with patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO REPLAY INFERENCE')):
            await self.command('/models EUROCUP U2026_99')
        # Resolve actual provider fixture id from the report registry for this fixture.
        payload=self.app.bot_data['europe_services']['EUROCUP'].registry.independent_records()[0]['payload']
        fid=payload['fixture']['provider_fixture_ids'][0]
        await self.command('/models EUROCUP '+fid)
        self.assertIn('Kayıtlı BAYES_QMC:','\n'.join(self.api.sent))
        self.assertEqual(n,len(self.sources['EUROCUP'].calls));self.assertEqual(before,ui.EuropeanButtonTests.files(self))
        self.assertEqual(len([b for row in report['reply_markup'].inline_keyboard for b in row]),6)

    async def test_unauthorized_commands_and_missing_fixture_never_start_analysis(self):
        for command in ('/features','/models NBA 401000123'):
            await self.command(command,chat=99)
        self.assertEqual(self.api.sent,[])
        await self.command('/models NBA');self.assertIn('Kullanım:',self.api.sent[-1])
        self.nba.analyze.assert_not_awaited()

    async def test_prediction_send_diagnostics_are_available_in_authorized_chat(self):
        command=self.app.bot_data['predictions_command']
        command.last_send=dict(status='UNCONFIRMED',parts=3,sent=1,error_code='NETWORK_ERROR')
        await self.command('/test predictions')
        text='\n'.join(self.api.sent)
        self.assertIn('Tamamlanan bölüm: 1/3',text);self.assertIn('NETWORK_ERROR',text)
        self.nba.analyze.assert_not_awaited()

    async def test_successful_error_notice_is_not_reported_as_prediction_list_delivery(self):
        command=self.app.bot_data['predictions_command']
        command.last_read=dict(status='TIMEOUT',error_code='PREDICTIONS_READ_TIMEOUT',
            deadline_seconds=.01,queued_at=1.,started_at=1.1,finished_at=1.2)
        command.last_response_kind='ERROR_NOTICE'
        command.last_send=dict(status='SENT',parts=1,sent=1,error_code=None)
        await self.command('/test predictions');text='\n'.join(self.api.sent)
        self.assertIn('Arşiv okuma durumu: TIMEOUT',text)
        self.assertIn('Gönderilen yanıt: HATA BİLDİRİMİ',text)
        self.assertIn('Tahmin listesi teslimi: DOĞRULANMADI',text)
        self.assertIn('Yanıt mesajı gönderimi: SENT',text)
        self.assertIn('kuyruğunda bekleme',text)
