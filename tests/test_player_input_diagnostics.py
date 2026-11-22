"""Read-only real player input collection evidence, separate from synthetic smoke."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.player_inputs import recent_collection_diagnostics


class RealPlayerInputDiagnosticsTests(TestCase):
    def test_reports_latest_pinned_blocker_without_medical_names_or_network(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            base=dict(format='PLAYER_INPUT_COLLECTION_V1',fixture_id='fixture-1',
                provider_fixture_ids=['401910027'],completed_at_utc=1795305600,
                status='BLOCKED',reason='ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS',
                projection=None,
                roster_diagnostics=dict(missing_absence_count=4,
                    official_expected_matchup='NOP@SAS',official_fixture_rows=12,
                    missing_absence_corroboration=[dict(player='PRIVATE_PATIENT_NAME',
                        status='Out',note='PRIVATE_MEDICAL_NOTE')]),
                official_only_diagnostic=dict(status='BLOCKED_NOT_ARCHIVED',
                    downstream_reason='CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY'),
                rotation_diagnostics=dict(home=dict(missing_history_count=2),
                    away=dict(missing_history_count=1)))
            first=dict(base,completed_at_utc=1795305000,
                reason='CURRENT_ROSTER_SOURCE_REVIEW_REQUIRED')
            for body in (first,base):
                wrapped=dict(payload=body,sha256=digest(body))
                publish_json(root/('collection-'+digest(body)+'.json'),wrapped)
            result=recent_collection_diagnostics(root)
            self.assertEqual(result['status'],'ARCHIVED_COLLECTION_ATTEMPTS')
            self.assertEqual(len(result['items']),1)
            item=result['items'][0]
            self.assertEqual(item['reason'],'ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS')
            self.assertEqual(item['official_expected_matchup'],'NOP@SAS')
            self.assertEqual(item['rotation_missing_history_counts'],{'home':2,'away':1})
            self.assertEqual(item['diagnostic_downstream_reason'],
                             'CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY')
            self.assertEqual(item['missing_absence_corroboration_count'],4)
            self.assertEqual(result['source_calls'],0)
            self.assertFalse(result['scores_recomputed'])
            self.assertNotIn('PRIVATE_PATIENT_NAME',json.dumps(result))
            self.assertNotIn('PRIVATE_MEDICAL_NOTE',json.dumps(result))

    def test_tampered_collection_is_ignored(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            payload=dict(format='PLAYER_INPUT_COLLECTION_V1',
                fixture_id='any',completed_at_utc=1795305600,status='BLOCKED')
            publish_json(root/('collection-'+digest(payload)+'.json'),
                         dict(payload=payload,sha256='0'*64))
            report=recent_collection_diagnostics(root)
            self.assertEqual(report['status'],'NO_COLLECTION_ATTEMPTS')
            self.assertEqual(report['items'],[])

    def test_no_archive_is_not_mislabeled_as_prospective_game(self):
        with TemporaryDirectory() as temp:
            report=recent_collection_diagnostics(Path(temp)/'not-created')
            self.assertEqual(report['status'],'NO_COLLECTION_ATTEMPTS')
            self.assertTrue(report['read_only'])
            self.assertEqual(report['items'],[])
