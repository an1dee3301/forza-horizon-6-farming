import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from fh6.reporting import read_json, write_json
from fh6.mission_reset import reset_target
from fh6.session import Session


class ResetTests(unittest.TestCase):
    def test_invalid_target_cannot_end_or_archive_mission(self):
        with patch('fh6.mission_reset.WorkerLease') as lease:
            for value in [0,10001,'bad',True]:
                with self.assertRaises(ValueError):
                    reset_target(value)
            lease.assert_not_called()

    def test_reset_archives_measurements_and_keeps_forecasts_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); root = base/'runs'; root.mkdir()
            write_json(root/'session.json', {'phase':'complete'})
            write_json(root/'goal.json', {'id':'20260911_014620_313216','phase':'farm','limit':1000,'rewards':517})
            write_json(root/'analytics.json', {'goal_id':'old','cycles':[{'elapsed_seconds':53}],
                'farm_seconds':[1000],'farm_yields':[370]})
            write_json(root/'account_observed.json', {'credits':12345})
            with patch('fh6.mission_reset.core.BASE',base), \
                 patch('fh6.mission_reset.WorkerLease'), \
                 patch('fh6.mission_reset.core.PurchaseLedger'), \
                 patch('fh6.mission_reset.Session',lambda:Session(root/'session.json')):
                goal = reset_target(1000)
            self.assertEqual((goal['rewards'],goal['bought'],goal['farm_runs']),(0,0,0))
            self.assertNotEqual(goal['id'],'old')
            self.assertEqual(read_json(Path(goal['reset_archive'])/'goal.json')['rewards'],517)
            analytics = read_json(root/'analytics.json')
            self.assertEqual(analytics['goal_id'],goal['id'])
            self.assertEqual(analytics.get('cycles',[]),[])
            self.assertEqual(analytics['prior_cycles'],[53])
            self.assertEqual(read_json(root/'account_observed.json')['credits'],12345)
            self.assertFalse(read_json(root/'report_runtime.json')['active'])

    def test_unfinished_car_blocks_reset(self):
        with patch('fh6.mission_reset.WorkerLease'), \
             patch('fh6.mission_reset.core.PurchaseLedger'), \
             patch('fh6.mission_reset.Session',return_value=Mock(data={'phase':'mastery'})):
            with self.assertRaisesRegex(RuntimeError,'Finish the saved purchased car'):
                reset_target(1000)


if __name__ == '__main__':
    unittest.main()
