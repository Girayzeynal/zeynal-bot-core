"""Guard against sending a newly computed forecast when archive insertion fails."""
import ast
from pathlib import Path
import unittest


class PrematchArchiveGateTests(unittest.TestCase):
    def test_analyze_requires_successful_new_insert_before_reply(self):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        analyze = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                       and node.name == "analyze_command")
        bridge_assignments = [
            node for node in ast.walk(analyze)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "record_faz13_for_espn_fixture"
        ]
        self.assertEqual(len(bridge_assignments), 1)
        assignment = bridge_assignments[0]
        self.assertEqual([t.id for t in assignment.targets if isinstance(t, ast.Name)], ["inserted"])
        guards = [
            node for node in ast.walk(analyze)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "inserted"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.IsNot)
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value is True
            and any(isinstance(child, ast.Raise) for child in node.body)
        ]
        self.assertEqual(len(guards), 1)
        self.assertGreater(guards[0].lineno, assignment.lineno)


if __name__ == "__main__":
    unittest.main()
