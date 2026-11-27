"""Synthetic publication controls for the read-only device audit."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.adaptive_research import FORMAT
from hybrid_engine.boxes import publish_json
from hybrid_engine.current_assessment import AssessmentRegistry, VERSION as CURRENT_VERSION
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.paired_archive_audit import audit, render


def score(home, away, name):
    return dict(model=name, home=home, away=away, total=home+away, margin=home-away,
                home_handicap=away-home, quarters=[[home/4,away/4]]*4,
                halves=[[home/2,away/2]]*2, scope='REGULATION_ONLY')


class ArchiveAuditTests(TestCase):
    def setUp(self):
        folder=TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.labels = []

    def read(self,league,_):
        return dict(status='VERIFIED_LIVE_REPORT',forecasts=self.labels if league=='NBA' else [])

    def fixture(self, fixture_id):
        return dict(league='NBA',season='2026/2027',canonical_id=fixture_id,
                    fixture_id=fixture_id, start_ts_utc=10000, fixture_start_utc=10000,
                    provider_fixture_ids=['401'+fixture_id],home_team_id='1',away_team_id='2')

    def label(self, fid, **changes):
        row=dict(league='NBA',season='2026/2027',fixture_id=fid,snapshot_sha256=digest(fid),
                 model_version='FROZEN_NBA',model_digest='b'*64,provider_fixture_ids=['401'+fid],
                 first_archived_at_utc=1000,prediction_generated_at_utc=950,
                 fixture_start_utc=10000, label_available_utc=12000,
                 prediction=[100,92], actual=[100,108], final_with_ot=[110,123],
                 predicted_quarters=[[25,23]]*4, predicted_halves=[[50,46]]*2,
                 actual_periods=dict(home=[25,25,25,25,10],away=[27,27,27,27,15]))
        self.labels.append(dict(row,**changes))

    def plan(self, family, scope):
        root=self.root/'research-protocols'/family/scope
        root.mkdir(parents=True)
        policy=dict(version='REGISTERED_V3',automatic_promotion=False)
        body=dict(format=FORMAT,registered_at_utc=900,source_pins={'model.py':digest(scope)},policy=policy)
        plan=dict(payload=body,sha256=digest(body))
        name='plan-'+plan['sha256']+'.json' if family=='adaptive-v2' else 'plan.json'
        publish_json(root/name,plan)
        return root,plan

    def capture(self, family, root, plan, fid, home, away, *, candidate_at=2000):
        registry=ForwardRegistry(root/'forecasts')
        target=self.fixture(fid)
        original=digest(fid)
        pin=plan['sha256']
        admitted={k: v for k, v in target.items() if k not in ('canonical_id', 'start_ts_utc')}
        admission=dict(target=admitted,protocol_sha256=pin,original_snapshot_sha256=original,admitted_at_utc=1500)
        if family=='adaptive-v2':
            key=dict(protocol=pin,fixture=fid,league='NBA')
        else:
            key=dict(plan=pin,fixture=fid)
        publish_json(root/('admit-'+digest(key)+'.json'),dict(payload=admission,sha256=digest(admission)))
        asset=registry.asset('source',{'fixture':fid})
        p=dict(fixture=target,actual=None,assets=[asset],production_enabled=False,
               version=pin if family=='adaptive-v2' else 'REGISTERED_V3',
               record_type='ADAPTIVE_V2_SEPARATE_RESEARCH_NOT_ACTIVE_MODEL',
               protocol_sha256=pin,original_snapshot_sha256=original,original_model_digest='b'*64,
               prediction_generated_at_utc=candidate_at,source_available_max_utc=1800)
        if family=='adaptive-v2':
            p['components']={'PACE_EFFICIENCY':dict(status='FORECAST_CREATED',prediction=score(home,away,'PACE_EFFICIENCY'))}
        else:
            p['candidate']=score(home,away,'V3')
        with patch('time.time',return_value=candidate_at+1):
            registry.record(p)
        return registry

    def test_archived_protocols_stay_separate_and_three_way_metrics_use_same_fixtures(self):
        v2, plan2=self.plan('adaptive-v2','protocol-v2')
        v3, plan3=self.plan('nba-v3','protocol-v3-old')
        for fid in ('1','2','3'):
            self.label(fid)
        self.capture('adaptive-v2',v2,plan2,'1',100,104)
        self.capture('adaptive-v2',v2,plan2,'2',120,120)
        self.capture('nba-v3',v3,plan3,'1',108,108)
        self.capture('nba-v3',v3,plan3,'3',100,100)
        before={f.relative_to(self.root):f.read_bytes() for f in self.root.rglob('*.json')}
        report=audit(self.root,self,now=13000)
        self.assertEqual([p['status'] for p in report['protocols']],['PAIRED','PAIRED'])
        self.assertEqual([p['groups'][0]['n'] for p in report['protocols']],[2,2])
        shared,=report['common_fixtures']
        self.assertEqual((shared['n'],shared['original_total_mae'],shared['v2_total_mae'],
                          shared['candidate_total_mae']),(1,16,4,8))
        self.assertIn('16.00 / 4.00 / 8.00',render(report))
        self.assertEqual(before,{f.relative_to(self.root):f.read_bytes() for f in self.root.rglob('*.json')})

    def test_late_original_and_late_candidate_do_not_become_pairs(self):
        v2, plan=self.plan('adaptive-v2','protocol-v2')
        self.label('1',first_archived_at_utc=2500)
        self.label('2')
        self.capture('adaptive-v2',v2,plan,'1',100,104)
        self.capture('adaptive-v2',v2,plan,'2',100,104,candidate_at=9800)
        result,=audit(self.root,self,now=13000)['protocols']
        self.assertEqual(result['status'],'NO_MATCHED_PUBLICATIONS')
        self.assertEqual(result['exclusions']['UNPROVEN_TIMELINE_OR_LABEL_AVAILABILITY'],2)

    def test_tampered_receipt_is_reported_without_hiding_other_protocol(self):
        self.label('1')
        v2, plan2=self.plan('adaptive-v2','protocol-v2')
        v3, plan3=self.plan('nba-v3','protocol-v3')
        reg=self.capture('adaptive-v2',v2,plan2,'1',100,104)
        self.capture('nba-v3',v3,plan3,'1',100,104)
        next(reg.root.glob('source-*.json')).write_text('{}')
        p2,p3=audit(self.root,self,now=13000)['protocols']
        self.assertEqual(p2['status'],'FAILED')
        self.assertEqual(p3['status'],'PAIRED')

    def test_current_assessment_uses_only_first_verified_commit_per_fixture(self):
        self.label('1')
        root=self.root/'current-assessments-v1'
        registry=AssessmentRegistry(root/'records')
        body=dict(registered_at_utc=900,source_pins={'model.py':digest('old')},
                  policy=dict(version=CURRENT_VERSION,automatic_promotion=False))
        pin=digest(body)
        publish_json(root/'policy.json',dict(payload=body,sha256=pin))
        asset=registry.asset('source',{'fixture':'1'})
        for candidate_at,away in ((2000,104),(5600,108)):
            p=dict(fixture=self.fixture('1'),actual=None,assets=[asset],production_enabled=False,
                   record_type=CURRENT_VERSION,version=f'{pin}:{candidate_at//3600}',protocol_sha256=pin,
                   original_snapshot_sha256=digest('1'),original_model_digest='b'*64,
                   prediction_generated_at_utc=candidate_at,source_available_max_utc=1800,
                   parameter_fit_cutoff_utc=1000,candidate=score(100,away,'V3'))
            with patch('time.time',return_value=candidate_at+1):
                registry.record(p)
        result,=audit(self.root,self,now=13000)['protocols']
        group,=result['groups']
        self.assertEqual(result['publications'],2)
        self.assertEqual(group['n'],1)
        self.assertEqual(group['candidate_total']['mae'],4)
        self.assertEqual(group['diagnostics']['parameter_age_range_seconds'],[1000,1000])

    def test_missing_storage_does_not_create_directories(self):
        root=self.root/'absent'
        report=audit(root,self,now=13000)
        self.assertFalse(root.exists())
        self.assertEqual(report['protocols'],[])
