"""Temporary protocol fixtures. Default legacy CLI must not bypass source gates."""
from contextlib import redirect_stdout
from io import StringIO
import json
from unittest import TestCase
from unittest.mock import patch

import faz40_archive_audit as audit
from tests import test_faz40_archive_audit as original


class LegacySourceGateTests(TestCase):
    setUp=original.ReadonlyAuditTests.setUp

    def test_default_real_archive_inventory_never_calls_unbound_backtest(self):
        before=self.path.read_bytes()
        with patch('faz40_archive_audit.walk_forward',side_effect=AssertionError('unbound model path')) as model:
            out=audit.run(self.path)
        model.assert_not_called();self.assertEqual(out['status'],'ABSTAIN_SOURCE_BOUND_HISTORY_REQUIRED');self.assertEqual(self.path.read_bytes(),before)
        for league,modes in out['reports'].items():
            for report in modes.values():self.assertEqual(report['evaluated_games'],0);self.assertIsNone(report['metrics'])

    def test_real_archive_cli_returns_explicit_abstention_without_model_call(self):
        before=self.path.read_bytes();stream=StringIO()
        with patch('sys.argv',['faz40_archive_audit',str(self.path)]),redirect_stdout(stream),patch('faz40_archive_audit.walk_forward',side_effect=AssertionError('unbound model path')):
            self.assertEqual(audit.main(),0)
        self.assertEqual(json.loads(stream.getvalue())['status'],'ABSTAIN_SOURCE_BOUND_HISTORY_REQUIRED');self.assertEqual(self.path.read_bytes(),before)

    def test_explicit_synthetic_research_remains_available_and_clearly_labelled(self):
        out=audit.run(self.path,usage='SYNTHETIC_TEST')
        self.assertEqual(out['status'],'READ_ONLY_RESEARCH_AUDIT_COMPLETE');self.assertEqual(out['usage'],'SYNTHETIC_TEST');self.assertEqual(out['prospective_records_created'],0)
