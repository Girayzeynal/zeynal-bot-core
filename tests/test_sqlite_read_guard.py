from unittest import TestCase
from unittest.mock import Mock,patch
import sqlite3
import time
from contextlib import closing
from hybrid_engine.sqlite_read_guard import bounded_rows,error_reason,retry_read

class SQLiteReadGuardTests(TestCase):
    def test_lock_retry_and_nontransient_fail_closed(self):
        fn=Mock(side_effect=[sqlite3.OperationalError('database is locked'),42])
        with patch('hybrid_engine.sqlite_read_guard.time.sleep'):
            self.assertEqual(retry_read(fn),42)
        self.assertEqual(fn.call_count,2)
        fn=Mock(side_effect=sqlite3.OperationalError('no such table: secret'))
        with self.assertRaises(sqlite3.OperationalError):retry_read(fn)
        self.assertEqual(fn.call_count,1)
    def test_safe_codes(self):
        self.assertEqual(error_reason(sqlite3.OperationalError('interrupted')),'SQLITE_QUERY_INTERRUPTED')
        self.assertEqual(error_reason(sqlite3.OperationalError('database is locked')),'SQLITE_BUSY')
        self.assertEqual(error_reason(sqlite3.OperationalError('no such table: private')),'SQLITE_SCHEMA_MISSING')
    def test_validation_pause_not_sql_budget(self):
        with closing(sqlite3.connect(':memory:')) as db:
            rows=bounded_rows(db,'SELECT 1 UNION ALL SELECT 2',budget=.1)
            self.assertEqual(next(rows),(1,))
            time.sleep(.15)
            self.assertEqual(next(rows),(2,))
            self.assertEqual(list(rows),[])
