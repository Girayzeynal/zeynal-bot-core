import math
import unittest
from faz22_engine.faz22_engine import Faz22Engine

class TestFaz22FiniteGuard(unittest.TestCase):
    def test_invalid_numbers(self):
        e = Faz22Engine()
        for value in (float("nan"), float("inf"), float("-inf"), "abc", None):
            with self.subTest(value=str(value)):
                self.assertIsNone(e._sf(value))

    def test_valid_numbers(self):
        e = Faz22Engine()
        for value, expected in (("12.5", 12.5), (0, 0.0), (-3, -3.0)):
            with self.subTest(value=value):
                self.assertEqual(e._sf(value), expected)

    def test_invalid_segment_values(self):
        e = Faz22Engine()
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=str(value)):
                self.assertIsNone(e._eval_segment("MS", e._sf(value), 220.0, 10.0, 70.0, []))
