"""Synthetic source/PIT adapter acceptance; never real lineup performance."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
from faz41_evidence import REGISTRY, fixture_identity
from faz41_faz40 import capture_announcement
from faz46_rosters import capture_listings
from faz47_lineup_view import lineup_view, validate_lineup_view
from tests.test_faz42_history import NOW, permitted_registry
from tests.test_faz42_prospective import test_model as synthetic_model
from tests.test_faz46_rosters import euro


TARGET = fixture_identity(league='NBA', season_end_year=2027, start_utc=NOW+3600,
                          home_team_id='19', away_team_id='2')


class LineupViewTests(TestCase):
    def setUp(self):
        timer = patch('time.time', return_value=NOW)
        self.clock = timer.start()
        self.addCleanup(timer.stop)
        self.registry = permitted_registry()
        self.model = synthetic_model()

    def options(self, **updates):
        options = dict(fixture=TARGET, cutoff_utc=NOW, model_manifest=self.model,
                       trusted_model_sha256=self.model['sha256'], registry=self.registry,
                       registry_pin=digest(self.registry))
        options.update(updates)
        return options

    def view(self, observations, **updates):
        return lineup_view(observations, **self.options(**updates))

    def announcement(self, team='19', players=None, fixture=TARGET, provider='NBA',
                     pid='0022600099', usage='SYNTHETIC_TEST', registry=None, created=NOW-1):
        players = [str(i) for i in range(1, 7)] if players is None else players
        raw = dict(format='EXPLICIT_TEAM_ANNOUNCEMENT_V1', fixture=fixture,
                   provider_fixture_id=pid, team_id=team, players=players,
                   starting_five=players[:5], status='CONFIRMED', published_at_utc=NOW-20)
        registry = self.registry if registry is None else registry
        url = 'https://cdn.nba.com/static/json/test/announcement.json' if provider == 'NBA' else \
              'https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games/99'
        with patch('time.time', return_value=created):
            return capture_announcement(raw, provider=provider, source_url=url,
                observed_at_utc=NOW-10, ingested_at_utc=created, usage=usage,
                registry=registry, registry_pin=digest(registry))

    def listings(self, league='EUROLEAGUE', five=False):
        raw, fixture, pid = euro(league)
        if five:
            for side, prefix in (('local', 'HOME'), ('road', 'AWAY')):
                template = deepcopy(raw['stats'][side]['players'][0])
                raw['stats'][side]['players'] = []
                for i in range(5):
                    row = deepcopy(template)
                    row['player']['person']['code'] = prefix + str(i)
                    row['stats']['startFive'] = True
                    row['player']['active'] = True
                    raw['stats'][side]['players'].append(row)
        with patch('time.time', return_value=NOW-1):
            rows, _ = capture_listings(raw, fixture=fixture, provider='EUROLEAGUE_LIVE', pid=pid,
                observed_at_utc=NOW-10, ingested_at_utc=NOW-5, usage='SYNTHETIC_TEST',
                registry=self.registry, registry_pin=digest(self.registry))
        return rows, fixture

    def test_no_evidence_is_unavailable_with_unknown_availability(self):
        result = self.view([])
        p = result['payload']
        self.assertEqual(p['evidence_usage'], 'NO_EVIDENCE')
        self.assertEqual(p['projected_adapter_status'], 'NOT_AVAILABLE')
        self.assertEqual(p['prospective_records_created'], 0)
        for team in p['teams'].values():
            self.assertEqual(team['status'], 'UNAVAILABLE')
            self.assertIsNone(team['starting_five'])
            for field in ('excluded', 'uncertain', 'active_for_target'):
                self.assertIsNone(team[field])
        self.assertEqual(result['sha256'], digest(p))

    def test_one_official_team_never_promotes_the_other_team(self):
        row = self.announcement()
        p = self.view([row])['payload']
        self.assertEqual(p['teams']['home']['status'], 'OFFICIAL')
        self.assertEqual(p['teams']['home']['starting_five'], row['payload']['claims']['starting_five'])
        self.assertEqual(p['teams']['away']['status'], 'UNAVAILABLE')
        self.assertIn('AWAY_CONFIRMED_LINEUP', p['missing'])
        self.assertIn('VERIFIED_INJURIES', p['missing'])
        self.assertEqual(p['evidence_usage'], 'SYNTHETIC_TEST')
        self.assertEqual(p['source_attestation'], 'NOT_INDEPENDENTLY_VERIFIED')

    def test_sources_and_model_keep_independent_pins_and_clocks(self):
        row = self.announcement()
        p = self.view([row])['payload']
        self.assertEqual(p['model_manifest'], self.model)
        self.assertEqual(p['model_sha'], self.model['payload']['git_sha'])
        self.assertEqual(p['trusted_model_sha256'], self.model['sha256'])
        self.assertEqual(p['model_binding'], 'PINNED_REFERENCE_NOT_EXECUTION_ATTESTATION')
        source = p['sources'][0]
        self.assertEqual(source['evidence_sha256'], row['sha256'])
        for field in ('provider', 'provider_fixture_id', 'source_url', 'raw_sha256',
                      'published_at_utc', 'observed_at_utc', 'ingested_at_utc', 'materialized_at_utc'):
            self.assertEqual(source[field], row['payload'][field])
        self.assertEqual(p['fixture'], TARGET)
        self.assertEqual(p['cutoff_utc'], NOW)
        self.assertLess(source['materialized_at_utc'], p['cutoff_utc'])

    def test_duplicate_and_reordered_evidence_are_idempotent(self):
        home = self.announcement()
        away = self.announcement(team='2', players=[str(i) for i in range(11, 17)])
        self.assertEqual(self.view([home, away]), self.view([away, home, home]))
        self.assertEqual(len(self.view([home, away])['payload']['sources']), 2)

    def test_views_do_not_mutate_or_alias_their_inputs(self):
        rows = [self.announcement()]
        before = deepcopy((rows, TARGET, self.model, self.registry))
        result = self.view(rows)
        result['payload']['teams']['home']['starting_five'].append('CHANGED')
        result['payload']['fixture']['home_team_id'] = 'CHANGED'
        result['payload']['model_manifest']['payload']['git_sha'] = '0'*40
        self.assertEqual((rows, TARGET, self.model, self.registry), before)

    def test_five_listed_players_and_active_flags_never_infer_projected_or_official(self):
        for league in ('EUROLEAGUE', 'EUROCUP'):
            with self.subTest(league=league):
                rows, fixture = self.listings(league, five=True)
                p = self.view(rows, fixture=fixture)['payload']
                for team in p['teams'].values():
                    self.assertEqual(team['status'], 'UNAVAILABLE')
                    self.assertIsNone(team['starting_five'])
                    self.assertEqual(len(team['unconfirmed_source_roster']['players']), 5)
                    self.assertEqual(team['reason'], 'ABSTAIN_SOURCE_LISTING_IS_NOT_STARTING_FIVE')

    def test_permitted_european_announcement_and_unconfirmed_listing_stay_separate(self):
        for league, code in (('EUROLEAGUE', 'E'), ('EUROCUP', 'U')):
            with self.subTest(league=league):
                rows, fixture = self.listings(league)
                raw_ids = [x.split(':', 1)[1] for x in rows[0]['payload']['claims']['players']]
                # A distinct explicit synthetic announcement, not an inference
                # from the listing, supplies a full five for the home team.
                ids = raw_ids + ['ANNOUNCED_EXTRA_' + str(i) for i in range(5-len(raw_ids))]
                row = self.announcement(team=fixture['home_team_id'], players=ids,
                    fixture=fixture, provider='EUROLEAGUE_LIVE', pid=code+'2026_99')
                p = self.view(rows+[row], fixture=fixture)['payload']
                self.assertEqual(p['teams']['home']['status'], 'OFFICIAL')
                self.assertIsNotNone(p['teams']['home']['unconfirmed_source_roster'])
                self.assertEqual(p['teams']['away']['status'], 'UNAVAILABLE')

    def test_unknown_permission_or_changed_policy_pin_is_refused(self):
        row = self.announcement(registry=REGISTRY)
        with self.assertRaisesRegex(ValueError, 'SOURCE_USAGE_NOT_ESTABLISHED'):
            self.view([row], registry=REGISTRY, registry_pin=digest(REGISTRY))
        with self.assertRaisesRegex(ValueError, 'TRUSTED_REGISTRY_PIN_MISMATCH'):
            self.view([], registry_pin='0'*64)

    def test_untrusted_origin_cannot_be_rehashed_into_official_proof(self):
        row = self.announcement()
        row['payload']['source_url'] = 'https://untrusted.example/announcement'
        row['sha256'] = digest(row['payload'])
        with self.assertRaisesRegex(ValueError, 'SOURCE_ORIGIN_NOT_ALLOWED'):
            self.view([row])

    def test_missing_future_or_post_tipoff_cutoff_is_refused(self):
        for cutoff in (None, NOW+1, TARGET['start_utc'], True):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                self.view([], cutoff_utc=cutoff)

    def test_materialization_at_cutoff_and_stale_sources_are_refused(self):
        equal = self.announcement(created=NOW)
        with self.assertRaisesRegex(ValueError, 'EVIDENCE_NOT_AVAILABLE_AT_CUTOFF'):
            self.view([equal])
        with self.assertRaisesRegex(ValueError, 'STALE_OBSERVATION'):
            self.view([self.announcement()], maximum_age_seconds=5)
        for age in (0, -1, True):
            with self.subTest(age=age), self.assertRaisesRegex(ValueError, 'INVALID_LINEUP_EVIDENCE_MAXIMUM_AGE'):
                self.view([], maximum_age_seconds=age)

    def test_rehashed_starting_five_or_status_claim_cannot_override_source(self):
        row = self.announcement()
        row['payload']['claims']['starting_five'] = ['2', '3', '4', '5', '6']
        row['sha256'] = digest(row['payload'])
        with self.assertRaisesRegex(ValueError, 'ANNOUNCEMENT_CLAIMS_CANNOT_REPLAY'):
            self.view([row])
        rows, fixture = self.listings()
        rows[0]['payload']['data_type'] = 'OFFICIAL_LINEUP'
        rows[0]['sha256'] = digest(rows[0]['payload'])
        with self.assertRaisesRegex(ValueError, 'EXPLICIT_TEAM_ANNOUNCEMENT_REQUIRED'):
            self.view(rows, fixture=fixture)

    def test_canonical_same_team_and_cross_team_aliases_fail_closed(self):
        row = self.announcement()
        for field in ('raw', 'claims'):
            row['payload'][field]['players'][1] = 'NBA:1'
            row['payload'][field]['starting_five'][1] = 'NBA:1'
        row['payload']['raw_sha256'] = digest(row['payload']['raw'])
        row['sha256'] = digest(row['payload'])
        with self.assertRaisesRegex(ValueError, 'ANNOUNCEMENT_PLAYER_ID_CONFLICT'):
            self.view([row])
        with self.assertRaisesRegex(ValueError, 'CROSS_TEAM_PLAYER_ID_CONFLICT'):
            self.view([self.announcement(), self.announcement(team='2', players=['NBA:'+str(i) for i in range(1, 7)])])

    def test_different_fixture_cannot_reuse_the_official_announcement(self):
        other = fixture_identity(league='NBA', season_end_year=2027, start_utc=NOW+3601,
                                 home_team_id='19', away_team_id='2')
        with self.assertRaisesRegex(ValueError, 'FIXTURE_OR_POLICY_BINDING_MISMATCH'):
            self.view([self.announcement()], fixture=other)

    def test_model_pin_chronology_and_usage_must_match(self):
        with self.assertRaisesRegex(ValueError, 'TRUSTED_LINEUP_MODEL_PIN_MISMATCH'):
            self.view([], trusted_model_sha256='0'*64)
        model = deepcopy(self.model)
        model['payload']['materialized_at_utc'] = NOW+1
        model['sha256'] = digest(model['payload'])
        with self.assertRaisesRegex(ValueError, 'MODEL_MANIFEST_MISMATCH'):
            self.view([], model_manifest=model, trusted_model_sha256=model['sha256'])
        model['payload']['materialized_at_utc'] = NOW-50
        model['payload']['purpose'] = 'EXPERIMENTAL_DRY_RUN'
        model['sha256'] = digest(model['payload'])
        with self.assertRaisesRegex(ValueError, 'LINEUP_MODEL_EVIDENCE_USAGE_MISMATCH'):
            self.view([self.announcement()], model_manifest=model, trusted_model_sha256=model['sha256'])

    def test_mixed_synthetic_and_real_tagged_evidence_is_refused(self):
        rows = [self.announcement(), self.announcement(team='2', players=[str(i) for i in range(11, 17)], usage='RETROSPECTIVE_RESEARCH')]
        with self.assertRaisesRegex(ValueError, 'MIXED_SYNTHETIC_REAL_EVIDENCE'):
            self.view(rows)

    def test_replay_after_tipoff_never_creates_a_new_prospective_record(self):
        row = self.announcement(usage='PROSPECTIVE_EVIDENCE')
        model = deepcopy(self.model)
        model['payload']['purpose'] = 'EXPERIMENTAL_DRY_RUN'
        model['sha256'] = digest(model['payload'])
        options = self.options(model_manifest=model, trusted_model_sha256=model['sha256'])
        before = lineup_view([row], **options)
        self.clock.return_value = TARGET['start_utc']+1000
        after = validate_lineup_view(before, [row], **options)
        self.assertEqual(before, after)
        self.assertEqual(after['payload']['prospective_records_created'], 0)
        self.assertEqual(after['payload']['purpose'], 'READ_ONLY_DEVELOPMENT_NOT_PREDICTION')

    def test_rehashed_output_status_model_or_source_is_not_accepted(self):
        row = self.announcement()
        view = self.view([row])
        for field in ('status', 'model', 'source', 'cutoff', 'unknown_injury', 'extra'):
            bad = deepcopy(view)
            p = bad['payload']
            if field == 'status': p['teams']['away']['status'] = 'PROJECTED'
            elif field == 'model': p['model_sha'] = '0'*40
            elif field == 'source': p['sources'][0]['observed_at_utc'] -= 1
            elif field == 'cutoff': p['cutoff_utc'] -= 1
            elif field == 'unknown_injury': p['teams']['home']['excluded'] = []
            else: p['caller_official'] = True
            bad['sha256'] = digest(p)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'LINEUP_VIEW_CANNOT_REPLAY'):
                validate_lineup_view(bad, [row], **self.options())

    def test_output_validation_checks_hash_and_exact_json_types(self):
        view = self.view([])
        view['payload']['schema_version'] = True  # True == 1 in Python, not in JSON.
        with self.assertRaisesRegex(ValueError, 'LINEUP_VIEW_CANNOT_REPLAY'):
            validate_lineup_view(view, [], **self.options())
        view['sha256'] = digest(view['payload'])
        with self.assertRaisesRegex(ValueError, 'LINEUP_VIEW_CANNOT_REPLAY'):
            validate_lineup_view(view, [], **self.options())

    def test_malformed_inputs_return_no_partial_view(self):
        for observations in (None, {}, [{}]):
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                self.view(observations)
        with self.assertRaisesRegex(ValueError, 'MALFORMED_LINEUP_VIEW_INPUT'):
            self.view([], model_manifest={})

    def test_no_network_database_or_model_execution(self):
        row = self.announcement()
        with patch('requests.sessions.Session.request', side_effect=AssertionError('NETWORK')), \
             patch('sqlite3.connect', side_effect=AssertionError('DATABASE')), \
             patch('faz40_research.project', side_effect=AssertionError('MODEL')), \
             patch('prematch_monte_carlo.PrematchMonteCarloEngine.simulate', side_effect=AssertionError('SIMULATION')):
            result = self.view([row])
        self.assertFalse(result['payload']['production_coefficients_changed'])
        self.assertEqual(result['payload']['storage_status'], 'NOT_ACTIVATED')
