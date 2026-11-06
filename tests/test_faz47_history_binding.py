"""Synthetic source protocols only, including research-tagged fake histories."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
from faz40_archive import seal_game
from faz41_adapters import capture
from faz41_evidence import REGISTRY,fixture_identity
from faz41_faz40 import research_with_context,capture_announcement
from faz47_history_binding import materialize_research_archive
from tests.test_faz42_history import NOW,history,permitted_registry

TARGET=fixture_identity(league='NBA',season_end_year=2027,start_utc=NOW+3600,home_team_id='19',away_team_id='2')


def pair(registry,usage='RETROSPECTIVE_RESEARCH'):
    proof=[];records=[]
    for row in history(registry):
        p=row['payload'];f=p['fixture']
        with patch('time.time',return_value=p['materialized_at_utc']):
            proof.append(capture(p['raw'],provider='ESPN',league='NBA',season_end_year=2027,
                observed_at_utc=p['observed_at_utc'],ingested_at_utc=p['ingested_at_utc'],usage=usage,registry=registry,registry_pin=digest(registry)))
            records.append(seal_game(p['raw'],league='NBA',season_end_year=2027,source_observed_utc=p['observed_at_utc'],
                ingested_utc=p['ingested_at_utc'],team_ids=['19','2'],usage=usage))
    return records,proof


class SourceBoundResearchTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.clock=self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.records,self.proof=pair(self.registry)

    def run_research(self,records=None,context=None,**kw):
        options=dict(target=TARGET,cutoff_utc=NOW,registry=self.registry,registry_pin=digest(self.registry),
                     minimum_team_games=2,simulations=10000,mode='ARCHIVED_SOURCE_CLOCK');options.update(kw)
        return research_with_context(self.records if records is None else records,context or [],**options)['payload']

    def context(self):
        raw=dict(format='EXPLICIT_TEAM_ANNOUNCEMENT_V1',fixture=TARGET,provider_fixture_id='0022600099',team_id='19',
                 players=['1','2','3','4','5','6'],starting_five=['1','2','3','4','5'],status='CONFIRMED',published_at_utc=NOW-20)
        with patch('time.time',return_value=NOW-1):return capture_announcement(raw,provider='NBA',source_url='https://cdn.nba.com/static/json/test/announcement.json',
            observed_at_utc=NOW-10,ingested_at_utc=NOW-5,usage='PROSPECTIVE_EVIDENCE',registry=self.registry,registry_pin=digest(self.registry))

    def test_real_archive_without_source_evidence_cannot_use_legacy_source_clock(self):
        with self.assertRaisesRegex(ValueError,'SOURCE_BOUND_HISTORY_REQUIRED'):self.run_research()

    def test_default_unknown_rights_cannot_be_bypassed_via_empty_prematch_context(self):
        self.registry=deepcopy(REGISTRY);self.records,self.proof=pair(self.registry)
        with self.assertRaisesRegex(ValueError,'SOURCE_BOUND_HISTORY_REQUIRED'):self.run_research(mode='INGESTION_TIME')

    def test_mixed_real_context_and_synthetic_history_reject_before_model_call(self):
        records,_=pair(self.registry,'SYNTHETIC_TEST')
        with patch('faz40_research.project',return_value=dict(usage='SYNTHETIC_TEST')) as model:
            with self.assertRaisesRegex(ValueError,'MIXED_SYNTHETIC_REAL_EVIDENCE'):self.run_research(records=records,context=[self.context()])
        model.assert_not_called()

    def test_source_bound_real_history_and_prospective_context_keep_original_labels(self):
        out=self.run_research(context=[self.context()],history_evidence=self.proof)
        self.assertEqual(out['reference']['status'],'PROJECTED_RESEARCH');self.assertEqual(out['reference']['usage'],'RETROSPECTIVE_RESEARCH')
        self.assertEqual(out['evidence']['payload']['usage'],'PROSPECTIVE_EVIDENCE');self.assertEqual(out['history_source_binding']['bound_games'],10)
        self.assertFalse(out['evidence_applied_to_coefficients']);self.assertEqual(out['prospective_records_created'],0)

    def test_bound_unknown_rights_return_abstain_without_simulation(self):
        self.registry=deepcopy(REGISTRY);self.records,self.proof=pair(self.registry)
        with patch('prematch_monte_carlo.PrematchMonteCarloEngine.simulate') as sim:
            out=self.run_research(history_evidence=self.proof)
        sim.assert_not_called();r=out['reference'];self.assertEqual(r['status'],'ABSTAIN');self.assertIsNone(r['prediction']);self.assertIsNone(r['simulation'])
        self.assertEqual(r['excluded']['SOURCE_USAGE_NOT_ESTABLISHED'],10)

    def test_late_v2_materialization_cannot_use_early_legacy_source_clock(self):
        late=[]
        for o in self.proof:
            p=o['payload']
            with patch('time.time',return_value=NOW-1):late.append(capture(p['raw'],provider='ESPN',league='NBA',season_end_year=2027,
                observed_at_utc=p['observed_at_utc'],ingested_at_utc=NOW-2,registry=self.registry,registry_pin=digest(self.registry)))
        for mode in ('INGESTION_TIME','ARCHIVED_SOURCE_CLOCK'):
            out=self.run_research(history_evidence=late,cutoff_utc=NOW-10,mode=mode)['reference']
            self.assertEqual(out['status'],'ABSTAIN');self.assertIsNone(out['prediction']);self.assertEqual(out['excluded']['UNAVAILABLE_AT_CUTOFF'],10)

    def test_permission_expiry_is_checked_at_cutoff_not_at_old_observation(self):
        self.registry['ESPN']['expires_at_utc']=NOW-1;self.records,self.proof=pair(self.registry)
        out=self.run_research(history_evidence=self.proof)['reference']
        self.assertIsNone(out['prediction']);self.assertEqual(out['excluded']['PERMISSION_NOT_VALID_AT_CUTOFF'],10)

    def test_valid_legacy_alias_without_matching_provider_proof_is_refused(self):
        records=deepcopy(self.records);p=records[0]['payload'];raw=deepcopy(p['raw']);raw['header']['id']=raw['header']['competitions'][0]['id']='401999999'
        records[0]=seal_game(raw,league='NBA',season_end_year=2027,source_observed_utc=p['source_observed_utc'],ingested_utc=p['ingested_utc'],team_ids=['19','2'])
        with self.assertRaisesRegex(ValueError,'ALIAS_MISMATCH'):self.run_research(records=records,history_evidence=self.proof)

    def test_valid_legacy_score_conflict_cannot_be_hidden_by_matching_identity(self):
        records=deepcopy(self.records);p=records[0]['payload'];raw=deepcopy(p['raw']);t=next(t for t in raw['header']['competitions'][0]['competitors'] if t['homeAway']=='home')
        t['score']=str(int(t['score'])+1);t['linescores'][0]['value']+=1;t['linescores'][0]['displayValue']=str(t['linescores'][0]['value'])
        records[0]=seal_game(raw,league='NBA',season_end_year=2027,source_observed_utc=p['source_observed_utc'],ingested_utc=p['ingested_utc'],team_ids=['19','2'])
        with self.assertRaisesRegex(ValueError,'FACT_CONFLICT'):self.run_research(records=records,history_evidence=self.proof)

    def test_missing_or_extra_source_universe_is_not_silently_ignored(self):
        for records,proof in [(self.records,self.proof[:-1]),(self.records[:-1],self.proof)]:
            with self.assertRaisesRegex(ValueError,'UNIVERSE_MISMATCH'):self.run_research(records=records,history_evidence=proof)

    def test_rehashed_legacy_claim_still_requires_semantic_replay(self):
        records=deepcopy(self.records);records[0]['payload']['facts']['final_home']+=1;records[0]['sha256']=digest(records[0]['payload'])
        with self.assertRaisesRegex(ValueError,'SEMANTIC_MISMATCH'):self.run_research(records=records,history_evidence=self.proof)

    def test_self_declared_permission_cannot_replace_pinned_policy(self):
        self.registry=deepcopy(REGISTRY);self.records,self.proof=pair(self.registry)
        self.proof[0]['payload']['usage_status']='PERMITTED';self.proof[0]['sha256']=digest(self.proof[0]['payload'])
        with self.assertRaisesRegex(ValueError,'SEMANTIC_MISMATCH'):self.run_research(history_evidence=self.proof)

    def test_materialization_today_does_not_overwrite_original_evidence_clocks(self):
        before=deepcopy(self.proof);records=materialize_research_archive(self.proof,registry=self.registry,registry_pin=digest(self.registry))
        self.assertTrue(all(r['payload']['ingested_utc']==NOW and r['payload']['materialized_utc']==NOW for r in records))
        out=self.run_research(records=records,history_evidence=self.proof)
        self.assertEqual(out['reference']['status'],'PROJECTED_RESEARCH');self.assertTrue(out['history_source_binding']['legacy_clocks_not_used_for_eligibility'])
        self.assertEqual(self.proof,before)

    def test_duplicate_records_sources_and_order_cannot_inflate_games(self):
        first=self.run_research(history_evidence=self.proof)
        second=self.run_research(records=list(reversed(self.records))*2,history_evidence=list(reversed(self.proof))*2)
        self.assertEqual(first['reference']['prediction'],second['reference']['prediction']);self.assertEqual(first['history_source_binding'],second['history_source_binding'])

    def test_correlation_and_seed_are_retained_in_the_existing_monte_carlo_model(self):
        a=self.run_research(history_evidence=self.proof);b=self.run_research(history_evidence=self.proof,score_correlation=.4,seed=123)
        self.assertEqual(a['reference']['prediction'],b['reference']['prediction']);self.assertEqual(b['reference']['simulation']['score_correlation'],.4)
        self.assertEqual(b['reference']['simulation']['simulations'],10000);self.assertAlmostEqual(sum(b['reference']['simulation']['probabilities']),1)
        for value in (True,float('nan'),-1,1):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'INVALID_SCORE_CORRELATION'):
                self.run_research(history_evidence=self.proof,score_correlation=value)

    def test_unsupported_options_and_invalid_modes_are_rejected_explicitly(self):
        for options in [dict(fake_option=1),dict(mode='SKIP_TIME_CHECKS')]:
            with self.subTest(options=options),self.assertRaises(ValueError):self.run_research(history_evidence=self.proof,**options)

    def test_empty_archive_has_no_forecast_or_new_prospective_record(self):
        out=self.run_research(records=[]);self.assertIsNone(out['reference']['prediction']);self.assertEqual(out['prospective_records_created'],0)

    def test_synthetic_abstention_never_becomes_real_research_when_nothing_is_permitted(self):
        self.registry=deepcopy(REGISTRY);self.records,self.proof=pair(self.registry,'SYNTHETIC_TEST')
        out=self.run_research(history_evidence=self.proof)['reference'];self.assertIsNone(out['prediction']);self.assertEqual(out['usage'],'SYNTHETIC_TEST')
