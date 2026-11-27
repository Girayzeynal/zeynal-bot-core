"""Synthetic receipts exercise earliest-clock selection and fail-closed conflicts."""
from copy import deepcopy
import time
from unittest import TestCase
from unittest.mock import patch
from types import SimpleNamespace

from core.team_identity import digest
from hybrid_engine.overtime_archive_audit import earliest_rows,audit,render
from tests.test_overtime_research import cohort

class OvertimeArchiveAuditTests(TestCase):
    def test_earliest_receipt_and_conflict_exclusion(self):
        now=int(time.time());rows=cohort(now)
        later=deepcopy(rows)
        for batch in later:
            batch[0]['observed_at_utc']=now-1
            batch[0]['ingested_at_utc']=now
        later[0][0]['periods']['home'][-1]+=1
        later[0][0]['final_scores'][0]+=1
        docs=[dict(ingested_at_utc=now,catalog=dict(payload=dict(fixtures=['later']),sha256='b'*64),rows=later),
              dict(ingested_at_utc=now,catalog=dict(payload=dict(fixtures=['early']),sha256='a'*64),rows=rows)]
        refs=[dict(index=i,fixtures_sha256=digest(doc['catalog']['payload']['fixtures'])) for i,doc in enumerate(docs)]
        store=SimpleNamespace(references=lambda league,year:refs,read_source=lambda ref:docs[ref['index']])
        with patch('hybrid_engine.overtime_archive_audit.native_catalog',side_effect=lambda doc,*args:doc['catalog']),patch(
                'hybrid_engine.overtime_archive_audit.historical_rows',side_effect=lambda c:later if c[0][0]['sha256']=='b'*64 else rows):
            found,n,conflicts=earliest_rows(store,'NBA',2026,now,deadline=time.monotonic()+10)
            self.assertEqual((len(found),n,conflicts),(11,2,1))
            self.assertTrue(all(v[0]['ingested_at_utc']<now for v in found))
            report=audit(store,'NBA',2026)
            self.assertEqual(report['ot_games'],11)
            self.assertEqual(report['walk_forward']['n'],5)
            self.assertFalse(report['live_market_admission'])
            self.assertIn('NOT_CALIBRATED',render(report))

    def test_empty_archive_is_not_a_successful_fit(self):
        store=SimpleNamespace(references=lambda *args:[])
        report=audit(store,'EUROCUP',2026)
        self.assertEqual(report['fit_status'],'OVERTIME_NATIVE_HISTORY_EMPTY')
        self.assertIsNone(report['walk_forward'])
