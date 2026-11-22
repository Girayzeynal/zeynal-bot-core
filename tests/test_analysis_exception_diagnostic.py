"""Sanitized error/30-minute PDF TTL distinction; never live Telegram delivery."""
import asyncio
import sqlite3
from unittest import TestCase

from hybrid_engine.analysis_exception_diagnostic import summarize,render


class AnalysisExceptionDiagnosticTests(TestCase):
    def test_timeout_not_mislabeled_as_archive_corruption(self):
        value=summarize(asyncio.TimeoutError('secret token=abc'),clock=lambda:1795306200)
        self.assertEqual(value['code'],'ANALYZE_TIMEOUT')
        self.assertEqual(value['stage'],'SERVICE_UNKNOWN')
        self.assertFalse(value['archive_corruption_verified'])
        self.assertEqual(value['status'],'EXCEPTION_NOT_ARCHIVE_VERDICT')
        text=render(value)
        self.assertIn('ANALYZE_TIMEOUT',text)
        self.assertNotIn('secret',text)
        self.assertNotIn('Arşiv durumu doğrulanamadı.',text)

    def test_sqlite_error_is_not_automatically_archive_corruption(self):
        value=summarize(sqlite3.OperationalError('database is locked /sensitive/path'))
        self.assertEqual(value['code'],'ANALYZE_DATABASE_OPERATION')
        self.assertFalse(value['archive_corruption_verified'])
        self.assertNotIn('sensitive',str(value)+render(value))

    def test_value_and_network_errors_have_independent_codes(self):
        self.assertEqual(summarize(ValueError('sensitive'))['code'],'ANALYZE_VALIDATION_ERROR')
        self.assertEqual(summarize(ConnectionError('secret'))['code'],'ANALYZE_NETWORK_CONNECTION')
        self.assertEqual(summarize(KeyError('api_key'))['code'],'ANALYZE_MISSING_REQUIRED_FIELD')
        self.assertEqual(summarize(RuntimeError('secret'))['code'],'ANALYZE_RUNTIME_ERROR')

    def test_known_code_origin_is_reported_without_exposing_exception_text(self):
        source=compile("raise ValueError('token=SECRET_CANNOT_LEAK')",
                       '/private/fixture/live_nba.py','exec')
        try:
            exec(source,{})
        except ValueError as exc:
            record=summarize(exc)
        self.assertEqual(record['stage'],'NBA_LIVE_MODEL')
        self.assertEqual(record['origin'],{'file':'live_nba.py','line':1})
        self.assertIn('Kod satırı: live_nba.py:1',render(record))
        self.assertNotIn('/private',str(record)+render(record))
        self.assertNotIn('SECRET_CANNOT_LEAK',str(record)+render(record))

    def test_external_source_file_is_never_disclosed(self):
        source=compile("raise ValueError('api-key=SENSITIVE')",
                       '/private/secret/unknown_source.py','exec')
        try:
            exec(source,{})
        except ValueError as exc:
            record=summarize(exc)
        self.assertIsNone(record['origin'])
        self.assertNotIn('/private',str(record)+render(record))
        self.assertNotIn('SENSITIVE',str(record)+render(record))

    def test_origin_is_a_code_location_not_a_time_based_ttl_verdict(self):
        record=summarize(ValueError('not the 30-minute PDF gate'))
        self.assertFalse(record['archive_corruption_verified'])
        self.assertNotIn('not the 30-minute',str(record)+render(record))
        self.assertEqual(record['code'],'ANALYZE_VALIDATION_ERROR')

    def test_unknown_and_malicious_codes_are_not_reflected(self):
        class SpecialError(Exception): pass
        value=summarize(SpecialError('<token>'))
        self.assertEqual(value['code'],'ANALYZE_UNEXPECTED_EXCEPTION')
        self.assertNotIn('<token>',render(value))
        value['stage']='<unsafe>'
        self.assertIn('SERVICE_UNKNOWN',render(value))
        self.assertNotIn('<unsafe>',render(value))
