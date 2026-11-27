"""Status observation preserves research policies and reports score blockers."""
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from hybrid_engine.research_diagnostics import ObservedResearch


class ResearchDiagnosticsTests(TestCase):
    def test_startup_does_not_report_unknown_archive_counters_as_zero(self):
        base=SimpleNamespace(last_report=None,render=Mock(return_value='Kabul edilen maç 0'))
        text=ObservedResearch(base).render()
        self.assertIn('sıfır olarak yorumlanmaz',text)
        self.assertNotIn('Kabul edilen maç 0',text);base.render.assert_not_called()

    def test_idle_tick_does_not_hide_last_score_failure_behind_calibration_gate(self):
        first=dict(observed_at_utc=100,captures=[dict(status='ABSTAIN',
            reason='DYNAMIC_RECENT_TEAM_HISTORY_REQUIRED',fixture_id='private-fixture')],
            shadow_captures=[dict(status='ABSTAIN',reason='SHADOW_HUNDRED_NATIVE_SETTLED_ORIGINALS_REQUIRED')])
        idle=dict(observed_at_utc=160,captures=[],shadow_captures=[])
        original=deepcopy(first)
        base=SimpleNamespace(tick=Mock(side_effect=[first,idle]),render=Mock(return_value='V3 original'),last_report=None)
        observed=ObservedResearch(base)
        self.assertIs(observed.tick(),first);observed.tick()
        text=observed.render()
        self.assertIn('V3 skor denemesi engeli: DYNAMIC_RECENT_TEAM_HISTORY_REQUIRED',text)
        self.assertIn('V3 kalibrasyon denemesi engeli: SHADOW_HUNDRED',text)
        self.assertNotIn('private-fixture',text);self.assertEqual(first,original)
        self.assertEqual(base.tick.call_count,2)

    def test_delegated_objects_errors_and_last_report_assignment_remain_original(self):
        error=ValueError('source failure');registry=object()
        base=SimpleNamespace(tick=Mock(side_effect=error),render=Mock(return_value='unchanged'),
            registry=registry,last_report=None)
        observed=ObservedResearch(base);self.assertIs(observed.registry,registry)
        with self.assertRaises(ValueError) as raised:observed.tick()
        self.assertIs(raised.exception,error)
        report=dict(status='ABSTAIN',reason='ISSUE90_PLAN_CHANGED_REQUIRES_NEW_STUDY')
        observed.last_report=report;self.assertIs(base.last_report,report)
        self.assertIn('V3 kontrol engeli: ISSUE90_PLAN_CHANGED',observed.render())

    def test_observation_retains_bounded_safe_metadata_and_never_creates_scores(self):
        report=dict(observed_at_utc=100,captures=[dict(status='ABSTAIN',
            reason='https://private.invalid/token')]*100,shadow_captures=[])
        base=SimpleNamespace(tick=lambda:report,render=lambda:'original',last_report=None)
        observed=ObservedResearch(base);observed.tick()
        self.assertEqual(len(observed.score_attempt[1]),32)
        self.assertNotIn('private.invalid',observed.render())
        self.assertIn('UNCLASSIFIED_RESEARCH_BLOCK',observed.render())
        self.assertNotIn('ARCHIVED',observed.render())


def test_score_attempt_precedes_shadow_threshold_and_label_errors(tmp_path,monkeypatch):
    from hybrid_engine.data import Abstain
    from hybrid_engine.issue90_research import Research
    import sqlite3
    stage=[]
    case=dict(code='NBA',target=dict(fixture_id='game',fixture_start_utc=10000000000,season='2026/2027'),
              snapshot=dict(model_digest='a'*64))
    worker=SimpleNamespace(cases=lambda:[case], labels=Mock(side_effect=sqlite3.OperationalError()),
                           nba=SimpleNamespace(ledger=SimpleNamespace(path=tmp_path/'nba'),assets=tmp_path))
    study=Research(tmp_path/'v3',worker)
    monkeypatch.setattr(study,'plan',lambda:{'sha256':'b'*64})
    monkeypatch.setattr(study,'admit',lambda *args:None)
    monkeypatch.setattr(study,'fit',lambda season:({},True))
    monkeypatch.setattr(study,'capture',lambda *args:(stage.append('score') or {'sample':1},True))
    def audit(*args,**kwargs):
        stage.append('shadow')
        return {}
    monkeypatch.setattr('hybrid_engine.issue90_research.audit_ledger',audit)
    monkeypatch.setattr('hybrid_engine.issue90_research.shadow_learning.fit',
                        Mock(side_effect=Abstain('SHADOW_HUNDRED_NATIVE_SETTLED_ORIGINALS_REQUIRED')))
    report=study.tick()
    assert stage==['score','shadow']
    assert report['captures'][0]['status']=='ARCHIVED'
    assert report['shadow_captures'][0]['reason']=='SHADOW_HUNDRED_NATIVE_SETTLED_ORIGINALS_REQUIRED'
    assert report['performance_issue']=='SQLITE_OTHER'
