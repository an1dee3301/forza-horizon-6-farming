"""Production countdown display checks; no game input or production mutations."""
import ast
import unittest
from pathlib import Path

from fh6.farm_notices import planned_farm_remaining


class FarmStatusClockTests(unittest.TestCase):
    def test_live_plan_600s_reports_planned_remaining(self):
        self.assertEqual(planned_farm_remaining(749,167,dict(planned_exit='target_top_up',planned_drive_seconds=600)),433)

    def test_native_timer_can_finish_before_planned_target(self):
        self.assertEqual(planned_farm_remaining(35,540,dict(planned_exit='target_top_up',planned_drive_seconds=600)),35)

    def test_completed_target_never_shows_negative_seconds(self):
        for elapsed in (600,620):
            self.assertEqual(planned_farm_remaining(317,elapsed,dict(planned_exit='target_top_up',planned_drive_seconds=600)),0)

    def test_natural_completion_uses_native_timer(self):
        for plan in (None,{},dict(planned_exit='natural_completion',planned_drive_seconds=600)):
            self.assertEqual(planned_farm_remaining(749,167,plan),749)

    def test_invalid_reporting_plan_does_not_guess(self):
        for planned in (None,True,float('nan'),float('inf'),-10,'600'):
            self.assertEqual(planned_farm_remaining(749,167,dict(planned_exit='target_top_up',planned_drive_seconds=planned)),749)

    def test_planned_remaining_is_used_only_in_farming_status(self):
        tree=ast.parse((Path(__file__).parents[1]/'fh6/farming.py').read_text(encoding='utf-8'))
        calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='planned_farm_remaining']
        self.assertEqual(len(calls),1)
        status_calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='emit' and len(node.args)>1 and isinstance(node.args[0],ast.Constant) and node.args[0].value=='status']
        self.assertTrue(any(calls[0] in list(ast.walk(node.args[1])) for node in status_calls))


if __name__=='__main__':unittest.main()
