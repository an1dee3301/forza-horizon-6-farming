import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fh6.target import include_starting_inventory, totals
from fh6.analytics import forecast
from fh6.reporting import snapshot, report_due
from fh6.report_charts import cycle_summary


class TargetTests(unittest.TestCase):
    def test_performance_summary_uses_current_target(self):
        text = cycle_summary({'cycles':[{'elapsed_seconds':49},{'elapsed_seconds':52}]},50)
        self.assertIn('1/2 below 50s',text)

    def test_including_inventory_preserves_pending_car_and_earned_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            goal = dict(id='mission',limit=1000,rewards=164,bought=165,completed=164,
                        phase='convert',batch={'id':'cars','cycles':47,'rewards_seen':23},
                        account_baseline={'goal_id':'mission','fields':{'super_wheelspins':333}})
            (root/'goal.json').write_text(json.dumps(goal))
            (root/'session.json').write_text('{"id":"cars","phase":"mastery","rewards":23}')
            car_bytes = (root/'session.json').read_bytes()
            old = snapshot(root,active=False)
            with patch('fh6.target.WorkerLease'):
                updated = include_starting_inventory(root,1000,333)
            self.assertEqual(updated['limit'],667)
            self.assertEqual(updated['rewards'],164)
            self.assertEqual(updated['batch'],goal['batch'])
            self.assertEqual((root/'session.json').read_bytes(),car_bytes)
            self.assertEqual(totals(updated)['total_progress'],497)
            data = snapshot(root,active=False)
            self.assertEqual((data['remaining'],data['total_target'],data['unprocessed']),(503,1000,1))
            self.assertFalse(report_due(old,data,3600,0))
            self.assertEqual(forecast(updated,{}, {},[])['sp_required'],503*21)

    def test_rejects_unverified_inventory_or_already_committed_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            goal = dict(id='m',limit=1000,rewards=164,bought=165,
                        batch={'cycles':47,'rewards_seen':23},
                        account_baseline={'goal_id':'m','fields':{'super_wheelspins':333}})
            path = root/'goal.json'
            path.write_text(json.dumps(goal))
            before=path.read_bytes()
            with patch('fh6.target.WorkerLease'):
                for target,starting in [(1000,334),(500,333)]:
                    with self.assertRaises(ValueError):
                        include_starting_inventory(root,target,starting)
            self.assertEqual(path.read_bytes(),before)
