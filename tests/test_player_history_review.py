"""Historical fitting status must never be sold as a live injury adjustment."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import Mock,patch

from hybrid_engine.player_history_review import HistoricalPlayerReview
from hybrid_engine.research_diagnostics import ResearchCycle


def fitted():
    return dict(status='REAL_HISTORICAL_BOX_MODEL_FITTED_RESEARCH_ONLY',verified_player_box_games=70,
        historical_player_training_games=70,fitted_players=200,estimated_parameters=262,
        player_coefficients_not_individually_identified=True,
        retrospective_validation=dict(strict=dict(status='NO_SUFFICIENT_PRETEST_SOURCE_OBSERVATIONS',matched_test_games=0)))


class PlayerHistoricalReviewTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1795550000;timer=patch('time.time',side_effect=lambda:self.now)
        timer.start();self.addCleanup(timer.stop);self.reader=Mock(return_value=fitted())
        self.review=HistoricalPlayerReview(self.tmp.name,self.reader)

    def test_unobserved_is_not_zero_and_render_cannot_fit(self):
        self.assertEqual(self.review.snapshot()['status'],'NOT_OBSERVED_NOT_ZERO')
        self.assertIn('sıfır sayılmaz',self.review.render());self.reader.assert_not_called()

    def test_cached_background_study_keeps_clock_and_does_not_load_sources_again(self):
        first=self.review.tick();self.now+=60
        second=self.review.tick(case_loader=Mock(side_effect=AssertionError('NO_CASE_READ')))
        self.assertEqual(first,second);self.reader.assert_called_once()
        text=self.review.render();self.assertIn('70',text);self.assertIn('güncel maç öncesi',text)
        self.assertFalse(self.review.snapshot()['live_player_effect_applied'])
        self.assertFalse(list(Path(self.tmp.name).rglob('*')))

    def test_imminent_publication_defers_optional_fit_then_recovers(self):
        result=self.review.tick(cases=[dict(target=dict(fixture_start_utc=self.now+301))])
        self.assertIn('DEFERRED',result['status']);self.reader.assert_not_called()
        self.assertEqual(self.review.snapshot()['status'],'NOT_OBSERVED_NOT_ZERO')
        self.now+=61;self.review.tick(cases=[]);self.reader.assert_called_once()

    def test_bad_report_or_read_error_is_not_zero_training_or_live_success(self):
        self.reader.return_value={'status':'private-token-value'}
        report=self.review.tick();self.assertEqual(report['status'],'HISTORICAL_PLAYER_READ_FAILED')
        self.assertNotIn('private-token',self.review.render())
        self.now+=301;self.reader.side_effect=ValueError('private details')
        self.assertEqual(self.review.tick()['status'],'HISTORICAL_PLAYER_READ_FAILED')
        self.assertNotIn('private details',self.review.render())

    def test_real_readonly_missing_archive_does_not_create_any_data(self):
        observer=HistoricalPlayerReview(self.tmp.name)
        self.assertEqual(observer.tick()['status'],'INPUT_ARCHIVE_NOT_PRESENT')
        self.assertFalse(list(Path(self.tmp.name).rglob('*')))


class HistoryCycleTests(IsolatedAsyncioTestCase):
    async def test_auxiliary_failure_cannot_erase_current_model_metrics(self):
        state={'performance':{'n':7}};assessment=SimpleNamespace(last_report=state)
        cycle=ResearchCycle(SimpleNamespace(),None,assessment)
        def failure():raise ValueError('PLAYER_READINESS_UNKNOWN')
        app=SimpleNamespace(bot_data={})
        await cycle._stage('player_shadow',failure,app)
        self.assertIs(assessment.last_report,state)
        self.assertEqual(app.bot_data['last_player_shadow_poll']['status'],'ABSTAIN')

    async def test_history_runs_after_time_sensitive_current_and_existing_research(self):
        order=[]
        async def v2():order.append('v2');return {'status':'CHECKED'}
        def job(name):
            def run(**kwargs):order.append(name);return {'status':'CHECKED'}
            return run
        worker=SimpleNamespace(tick=v2,cases=lambda:[])
        cycle=ResearchCycle(worker,SimpleNamespace(tick=job('v3')),
            SimpleNamespace(tick=job('current')),SimpleNamespace(tick=job('history')))
        await cycle.once(SimpleNamespace(bot_data={}))
        self.assertEqual(order,['current','v2','v3','history'])
