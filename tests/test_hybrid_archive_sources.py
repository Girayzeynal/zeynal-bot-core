"""Synthetic archive contracts; these tests are never accuracy evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase

from hybrid_engine.archive_sources import github_blob, nba_periods, wiki_games, wiki_revision
from hybrid_engine.availability import certify, effective_time
from hybrid_engine.data import STRICT, available_at, prior_rows, regulation
from hybrid_engine.walkforward import label_at
from hybrid_engine.root_cause import verify_predictions
from tests.test_hybrid_models import synthetic_cohort, example


def witnessed(row, at, scope='CORE'):
    return certify(row, scope=scope, at=at, source_sha256='synthetic-source',
        evidence_id='synthetic-contract', authority='SYNTHETIC_TEST_ONLY')


class ArchiveAvailabilityTests(TestCase):
    def test_local_retrieval_is_preserved_and_json_claim_is_not_authority(self):
        row = synthetic_cohort(1)[0][0]; original = deepcopy(row)
        row['observed_at_utc'] += 999999; row['ingested_at_utc'] += 999999
        proof = witnessed(row, original['ingested_at_utc'])
        self.assertEqual(proof['observed_at_utc'], row['observed_at_utc'])
        self.assertEqual(available_at(proof, STRICT), original['ingested_at_utc'])
        plain = json.loads(json.dumps(proof))
        self.assertEqual(available_at(plain, STRICT), row['ingested_at_utc'])
        self.assertEqual(effective_time(proof, 'FIXTURE'), row['ingested_at_utc'])

    def test_verified_fields_cannot_be_mutated_or_moved_between_teams(self):
        for key,value in [('home_team_id','C'),('season','OTHER'),('observed_at_utc',1)]:
            proof = witnessed(synthetic_cohort(1)[0][0], 1735700401)
            proof[key] = value
            with self.assertRaisesRegex(ValueError, 'CHANGED_AFTER_VERIFICATION'): available_at(proof, STRICT)
        proof = witnessed(synthetic_cohort(1)[0][0], 1735700401)
        proof['periods']['home'][0] += 1
        with self.assertRaises(ValueError): available_at(proof, STRICT)

    def test_future_witness_is_excluded_and_latest_available_revision_wins(self):
        c = synthetic_cohort(5); original = deepcopy(c[0][0]); start=original['fixture_start_utc']
        original['observed_at_utc'] += 9999999; original['ingested_at_utc'] += 9999999
        a = deepcopy(original); b=deepcopy(original); b['periods']['home'][0] += 5
        c[0] = [original, witnessed(a,start+100), witnessed(b,start+172900), witnessed(deepcopy(a),start+345700)]
        self.assertEqual(regulation(prior_rows(c,c[1][0])[0]),regulation(a))
        self.assertEqual(regulation(prior_rows(c,c[2][0])[0]),regulation(b))
        self.assertEqual(regulation(prior_rows(c,c[3][0])[0]),regulation(a))

    def test_training_label_uses_fit_time_version_not_later_correction(self):
        c=synthetic_cohort(20); e=example(c,10,'TRAIN'); old=deepcopy(e['row']); new=deepcopy(old)
        new['periods']['home'][0] += 10; new['observed_at_utc'] += 999999; new['ingested_at_utc'] += 999999
        old=witnessed(old,old['fixture_start_utc']+100)
        e['label_versions']=[old,new]; cutoff=old['fixture_start_utc']+200
        chosen=label_at(e,cutoff,'TRAIN')
        self.assertEqual(chosen['label'],regulation(old)); self.assertNotEqual(chosen['label'],regulation(new))
        self.assertIsNone(label_at(e,old['fixture_start_utc'],'TRAIN'))

    def test_final_clock_cannot_precede_game(self):
        r=synthetic_cohort(1)[0][0]
        with self.assertRaises(ValueError): witnessed(r,r['fixture_start_utc'])
        self.assertEqual(effective_time(witnessed(r,r['fixture_start_utc']-100,'FIXTURE'),'FIXTURE'),r['fixture_start_utc']-100)


class NativeArchiveParserTests(TestCase):
    def test_numpy_period_repr_is_parsed_without_executing_code(self):
        text="[{'value': 20.0}\n {'value': 21.0}\n {'value': 22.0}\n {'value': 23.0}]"
        self.assertEqual(nba_periods(text),[20,21,22,23])
        for bad in ["__import__('os').getcwd()", "[{'value': 20.5}]*4", "[{'value': True}]*4"]:
            with self.assertRaises((ValueError,SyntaxError)): nba_periods(bad)

    def test_wiki_nested_links_report_season_and_dst_are_explicit(self):
        def box(day,pid):
            return ('{{basketballbox collapsible|id=x|date='+day+'|time=19:45|teamA=[[Club|Home]] {{bkaicon|TUR}}'
                '|teamB=[[Away]]|scoreA=80|scoreB=76|Q1=20–19|Q2=20–19|Q3=20–19|Q4=20–19'
                '|report=https://www.euroleaguebasketball.net/en/euroleague/game-center/x/E2025/'+str(pid)+'/}}')
        rows=list(wiki_games(box('30 September 2025',1)+box('30 December 2025',2),2025))
        self.assertEqual(rows[0]['home_name'],'Home')
        self.assertEqual(rows[0]['pid'],'E2025_1')
        self.assertEqual(datetime.fromtimestamp(rows[0]['fixture_start_utc'],timezone.utc).hour,17)
        self.assertEqual(datetime.fromtimestamp(rows[1]['fixture_start_utc'],timezone.utc).hour,18)
        self.assertEqual(rows[0]['periods']['home'],[20]*4)
        self.assertEqual(list(wiki_games(box('30 September 2025',1),2026)),[])

    def test_native_revision_hash_and_server_time_must_match(self):
        text='Central European Time Central European Summer Time'
        revision=dict(revid=123,timestamp='2025-10-01T00:00:00Z',sha1=hashlib.sha1(text.encode()).hexdigest(),slots={'main':{'*':text}})
        receipt=dict(source_url='https://en.wikipedia.org/w/api.php?action=query',observed_at_utc=1790000000,
            document={'query':{'pages':{'1':dict(title='2025–26 EuroLeague regular season',revisions=[revision])}}})
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'revision.json'
            def item():
                p.write_text(json.dumps(receipt)); return dict(year=2025,data=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
            self.assertIn('oldid=123',wiki_revision(item())[1]['evidence_id'])
            revision['sha1']='0'*40
            with self.assertRaisesRegex(ValueError,'NATIVE_REVISION_HASH'):wiki_revision(item())
            revision['sha1']=hashlib.sha1(text.encode()).hexdigest();receipt['observed_at_utc']=1
            with self.assertRaisesRegex(ValueError,'FUTURE_ARCHIVE'):wiki_revision(item())

    def test_github_blob_is_bound_to_server_run_head_not_author_date(self):
        raw=b'actual immutable bytes'; repo='sample/archive'; commit='a'*40
        run=dict(id=7,head_sha=commit,head_branch='main',repository={'full_name':repo},conclusion='success',created_at='2025-10-01T00:00:00Z')
        witness=dict(source_url='https://api.github.com/repos/'+repo+'/actions/runs',retrieved_at_utc=1790000000,document={'workflow_runs':[run]})
        entry=dict(path='nba/file',type='file',size=len(raw),sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())
        listing=dict(source_url='https://api.github.com/repos/'+repo+'/contents/nba?ref='+commit,document=[entry])
        with tempfile.TemporaryDirectory() as tmp:
            def pin(name,data):
                p=Path(tmp)/name;p.write_bytes(data);return dict(path=str(p),sha256=hashlib.sha256(data).hexdigest())
            def item():return dict(repo=repo,commit=commit,run_id=7,repo_file='nba/file',kind='NBA_SCHEDULE',observed_at_utc=1790000000,
                witness=pin('run.json',json.dumps(witness).encode()),listing=pin('listing.json',json.dumps(listing).encode()),data=pin('data',raw))
            self.assertEqual(github_blob(item())[0],raw)
            run['head_sha']='b'*40
            with self.assertRaisesRegex(ValueError,'SERVER_WITNESS_CONFLICT'):github_blob(item())
            run['head_sha']=commit;entry['sha']='0'*40
            with self.assertRaisesRegex(ValueError,'NATIVE_BLOB_HASH'):github_blob(item())


class BacktestEvidenceAuditTests(TestCase):
    def report(self):
        trace=dict(data_time_utc=9,prediction_utc=10,model_version='synthetic',model_digest='model',
            source_version='code',input_digest='inputs',fixture_source={'source':'synthetic'})
        row=dict(start_utc=11,trace=trace,line_grid=[dict(confidence_index=None,probabilities=dict(under=.4,push=.1,over=.5))])
        fold=dict(training_ids=['train'],validation_ids=['val'],test_ids=['test'],validation_cutoff=8,test_cutoff=10,
            label_version_pins=dict(train=[dict(available_utc=7)],validation=[dict(available_utc=9)]),ensemble=None)
        return dict(cohorts={'SYNTHETIC':dict(folds=[fold],model_rows={'FAZ13_MC':[row]})})

    def test_complete_trace_and_past_label_pins_pass(self):
        self.assertEqual(verify_predictions(self.report())['status'],'PASS')

    def test_future_fit_label_or_predictor_fails(self):
        r=self.report();r['cohorts']['SYNTHETIC']['folds'][0]['label_version_pins']['train'][0]['available_utc']=9
        with self.assertRaisesRegex(ValueError,'FIT_LABEL_AFTER_CUTOFF'):verify_predictions(r)
        r=self.report();r['cohorts']['SYNTHETIC']['model_rows']['FAZ13_MC'][0]['trace']['data_time_utc']=12
        with self.assertRaisesRegex(ValueError,'PREDICTOR_CLOCK_LEAK'):verify_predictions(r)

    def test_overlapping_test_blocks_or_future_ensemble_members_fail(self):
        r=self.report();c=r['cohorts']['SYNTHETIC'];c['folds'].append(deepcopy(c['folds'][0]))
        with self.assertRaisesRegex(ValueError,'FOLD_ID_OVERLAP'):verify_predictions(r)
        r=self.report();r['cohorts']['SYNTHETIC']['folds'][0]['ensemble']=dict(fit_cutoff=10,validation_ids=['test'])
        with self.assertRaisesRegex(ValueError,'ENSEMBLE_NOT_VALIDATION_ONLY'):verify_predictions(r)

    def test_invalid_probability_or_unverified_confidence_fails(self):
        for change in [dict(confidence_index=99),dict(probabilities=dict(under=.5,push=.5,over=.5))]:
            r=self.report();r['cohorts']['SYNTHETIC']['model_rows']['FAZ13_MC'][0]['line_grid'][0].update(change)
            with self.assertRaises(ValueError):verify_predictions(r)
