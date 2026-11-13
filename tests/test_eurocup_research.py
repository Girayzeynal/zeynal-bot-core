"""EuroCup remains a distinct research competition; no production model is enabled."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from historical_research import historical_rows
from hybrid_engine.audit import source_audit
from hybrid_engine.boxes import url_for
from hybrid_engine.archive_sources import euro_public_games
from season_archive_inventory import archive_catalog, validate_catalog
from tests.test_season_archive_audit import euro, NOW


class EuroCupArchiveTests(TestCase):
    def public(self, **changes):
        import json
        g=dict(code=1,utc='2026-10-01T17:00:00Z',home='HOM',away='AWY',score=[80,76],quarters=[[20]*4,[19]*4],pred=[999,999,.99])
        g.update(changes)
        return ('const SEASON = "2026-27";\nconst GAMES = '+json.dumps([g])+';\nconst MODEL = (() => {throw Error("never execute")})();\n').encode()

    def test_public_archive_ignores_third_party_predictions_and_executable_js(self):
        a=list(euro_public_games(self.public(),competition='U',year=2026))
        b=list(euro_public_games(self.public(pred=[1,1,.01]),competition='U',year=2026))
        self.assertEqual(a,b);self.assertEqual(a[0]['pid'],'U2026_1');self.assertNotIn('pred',a[0])

    def test_public_archive_requires_explicit_utc_and_same_season(self):
        with self.assertRaises(ValueError):list(euro_public_games(self.public(utc='2026-10-01T17:00:00'),competition='U',year=2026))
        with self.assertRaises(ValueError):list(euro_public_games(self.public(),competition='U',year=2025))

    def test_public_archive_cannot_be_cast_to_euroleague_or_forge_final_periods(self):
        with self.assertRaises(ValueError):list(euro_public_games(self.public(),competition='E',year=2026))
        with self.assertRaises(ValueError):list(euro_public_games(self.public(score=[100,76]),competition='U',year=2026))

    def setUp(self):
        p=patch('time.time',return_value=NOW);p.start();self.addCleanup(p.stop)

    def game(self,phase='RS'):
        g=euro();g['identifier']='U2026_1';g['season'].update(code='U2026',competitionCode='U');g['phaseType']['code']=phase
        return g

    def test_native_cup_playoff_codes_are_filtered_without_casting_to_euroleague(self):
        rows=[self.game()]
        for i,phase in enumerate(('8F','4F','2F','Final'),2):
            g=self.game(phase);g.update(identifier='U2026_'+str(i),gameCode=i);rows.append(g)
        b=archive_catalog(dict(total=5,data=rows),provider='EUROLEAGUE_LIVE',competition_code='U',
            observed_at_utc=NOW-1,ingested_at_utc=NOW,regular_season_filter=True)
        p=validate_catalog(b,trusted_sha256=b['sha256'])
        self.assertEqual(p['league'],'EuroCup');self.assertEqual(p['completed_fixtures'],1)
        self.assertEqual(len(p['excluded_non_regular_ids']),4)

    def test_cup_phase_cannot_silently_become_euroleague_phase(self):
        g=euro();g['phaseType']['code']='Final'
        with self.assertRaisesRegex(ValueError,'unknown_euroleague_season_phase'):
            archive_catalog(dict(total=1,data=[g]),provider='EUROLEAGUE_LIVE',observed_at_utc=NOW-1,ingested_at_utc=NOW,regular_season_filter=True)

    def test_cup_stats_uri_uses_same_competition_and_season_identity(self):
        row=dict(league='EuroCup',provider='EUROLEAGUE_LIVE',provider_fixture_ids=['U2025_1'],season='2025/2026')
        self.assertIn('/competitions/U/seasons/U2025/games/1/stats',url_for(row))
        row['league']='EuroLeague'
        with self.assertRaises(ValueError):url_for(row)

    def test_current_retrieval_does_not_create_historical_cup_training_samples(self):
        b=archive_catalog(dict(total=1,data=[self.game()]),provider='EUROLEAGUE_LIVE',competition_code='U',observed_at_utc=NOW-1,ingested_at_utc=NOW)
        c=historical_rows([(b,b['sha256'])]);r=source_audit(c,dict(fixture_knowledge=[]))
        self.assertEqual(r['cohorts']['EuroCup 2026/2027']['strict_joint_eligible'],0)
