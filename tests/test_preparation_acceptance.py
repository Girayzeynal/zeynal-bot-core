"""Acceptance contracts; synthetic reports are not resource or accuracy evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.team_identity import digest
from historical_research import historical_rows
from hybrid_engine.acceptance import verified_runtime
from hybrid_engine.data import load_manifest
from hybrid_engine.preparation import model_identity
from tests.test_historical_research import cohort


class CombinedAcceptanceTests(TestCase):
    def test_forecast_inputs_do_not_change_model_identity(self):
        from types import SimpleNamespace
        a=SimpleNamespace(model='SYNTHETIC',metadata=dict(method='MC',seed=1,elapsed_seconds=1,input_digest='game-A'))
        b=SimpleNamespace(model='SYNTHETIC',metadata=dict(method='MC',seed=1,elapsed_seconds=99,input_digest='game-B'))
        self.assertEqual(model_identity(a,'code'),model_identity(b,'code'))

    def test_code_or_trained_artifact_changes_model_identity(self):
        from types import SimpleNamespace
        a=SimpleNamespace(model='SYNTHETIC',metadata=dict(artifact_digest='trained-A'))
        b=SimpleNamespace(model='SYNTHETIC',metadata=dict(artifact_digest='trained-B'))
        self.assertNotEqual(model_identity(a,'code'),model_identity(b,'code'))
        self.assertNotEqual(model_identity(a,'code'),model_identity(a,'other-code'))

    def report(self):
        return dict(status='PASS',address_space_limit_bytes=[268435456]*2,peak_rss_mib=150,
            requests=25,analyze_replies=22,health_ready={'ready':True},accuracy_replies=1,compare_replies=1,
            actual_v1_analysis=True,reports_read_only_verified=True,legacy_records_preserved=True,
            isolated_ledger_integrity={'snapshots':2},cpu_affinity=[0],v1_cache_serialized_bytes=16*1024*1024,
            native_ml_libraries_loaded=[],runtime_source_pins={'code':'synthetic'},
            v1_decisions=[dict(league='NBA',status='ANALYSIS_OK')]*20+
                [dict(league='EUROLEAGUE',status='ANALYSIS_OK'),dict(league='EUROCUP',status='ABSTAIN')])

    def test_current_four_command_contract_requires_all_source_pins(self):
        r=self.report();self.assertTrue(verified_runtime(r,{'code':'synthetic'}))
        self.assertFalse(verified_runtime(r,{'code':'different'}))

    def test_older_shadow_only_or_incomplete_workload_is_not_accepted(self):
        for key,value in [('actual_v1_analysis',False),('compare_replies',0),('reports_read_only_verified',False),
                          ('legacy_records_preserved',False),('address_space_limit_bytes',[-1,-1]),('cpu_affinity',[0,1])]:
            r=self.report();r[key]=value;self.assertFalse(verified_runtime(r,{'code':'synthetic'}))

    def test_unsupported_cup_cannot_be_claimed_as_successful_production_analysis(self):
        r=self.report();r['v1_decisions'][-1]['status']='ANALYSIS_OK'
        self.assertFalse(verified_runtime(r,{'code':'synthetic'}))

    def test_native_box_is_retained_when_archive_versions_are_added_later(self):
        b,pin=cohort(n=1)[0];row=historical_rows([(b,pin)])[0][0]
        source=dict(observed_at_utc=row['observed_at_utc'],ingested_at_utc=row['ingested_at_utc'])
        box={k:row[k] for k in ('league','fixture_id','season','fixture_start_utc','home_team_id','away_team_id')}
        box.update(source=source,source_digest=digest(source),teams={s:dict(points=row['final_scores'][i]) for i,s in enumerate(('home','away'))})
        with TemporaryDirectory() as tmp:
            def file(name,value,kind):
                p=Path(tmp)/name;p.write_text(json.dumps(value));return dict(kind=kind,path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            manifest=dict(format='HYBRID_DATASET_MANIFEST_V1',files=[file('catalog.json',b,'CATALOG'),file('box.json',dict(format='HYBRID_BOX_ARCHIVE_V1',games=[box]),'BOX_STATISTICS')])
            path=Path(tmp)/'manifest.json';path.write_text(json.dumps(manifest));c,_=load_manifest(path)
            native=c[0][0]['box'];c[0][0]['box_versions'].append({'older':'archive'})
            self.assertEqual(c[0][0]['box_versions'][0],native)
