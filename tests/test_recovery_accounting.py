import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

from fh6.analytics import Tracker
from fh6.performance import Performance


def proof(**changes):
    value=dict(id='goal_1',proof='two_fresh_native_countdown_frames',guard_current=True,
               previous_remaining_seconds=917.0,remaining_seconds=916.4)
    value.update(changes)
    return value


class RecoveryAccountingTests(unittest.TestCase):
    def setup_tracker(self,folder,bound=False):
        self.clock=[0.]
        tracker=Tracker(folder,lambda:self.clock[0])
        tracker.event('activity',True)
        tracker.event('stage','choose' if bound else 'inspect_sp')
        if bound:
            tracker.event('cycle_stage',dict(batch_id='batch',cycle=1,phase='choose'))
        self.clock[0]=2
        tracker.event('failure',dict(stage='choose' if bound else 'inspect_sp',message='Expected upgrades; found home_tab'))
        self.clock[0]=4
        tracker.event('farm_started',dict(id='goal_1',before_sp=10))
        self.clock[0]=5
        tracker.event('stage','farm_drive')
        return tracker

    def test_only_native_active_proof_ends_unbound_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=self.setup_tracker(folder)
            self.assertIsNotNone(tracker.data.get('open_failure'))
            self.clock[0]=10
            tracker.event('farm_active',proof())
            self.assertIsNone(tracker.data.get('open_failure'))
            saved=copy.deepcopy(tracker.data['failures'][0])
            self.assertEqual(saved['recovery_seconds'],8)
            self.assertEqual(saved['recovery_end_version'],1)
            self.clock[0]=920
            tracker.event('farm_completed',dict(id='goal_1',before_sp=10,after_sp=380))
            self.assertEqual(tracker.data['failures'],[saved])
            self.assertEqual(tracker.data['farms'][0]['gained_sp'],370)

    def test_launch_stage_or_status_text_alone_do_not_end_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=self.setup_tracker(folder)
            self.clock[0]=10
            tracker.event('status','Farming SP — 00:00 elapsed')
            self.assertIsNotNone(tracker.data.get('open_failure'))

    def test_wrong_id_stale_equal_timer_and_bad_evidence_reject(self):
        changes=[dict(id='other'),dict(guard_current=False),dict(proof='one_frame'),
                 dict(remaining_seconds=917),dict(remaining_seconds=918),
                 dict(remaining_seconds=float('nan')),dict(previous_remaining_seconds=True)]
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                tracker=self.setup_tracker(folder)
                self.clock[0]=10
                tracker.event('farm_active',proof(**change))
                self.assertIsNotNone(tracker.data.get('open_failure'))

    def test_bound_car_failure_still_requires_car_checkpoint_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=self.setup_tracker(folder,bound=True)
            self.clock[0]=10
            tracker.event('farm_active',proof())
            self.assertIsNotNone(tracker.data.get('open_failure'))

    def test_historical_failure_rows_are_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=self.setup_tracker(folder)
            old=dict(stage='inspect_sp',recovery_seconds=1077.219,ended_at='historical')
            tracker.data['failures']=[copy.deepcopy(old)]
            self.clock[0]=10
            tracker.event('farm_active',proof())
            self.assertEqual(tracker.data['failures'][0],old)
            self.assertEqual(len(tracker.data['failures']),2)

    def test_background_delivery_delay_does_not_inflate_active_recovery_cost(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=self.setup_tracker(folder)
            self.clock[0]=500
            tracker.event('farm_active',proof(),event_time=10)
            self.assertEqual(tracker.data['failures'][0]['recovery_seconds'],8)

    def test_performance_clears_only_matching_unbound_farm_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            performance=Performance('goal',path=Path(folder)/'performance.json')
            performance.event('failure',dict(stage='inspect_sp'))
            performance.event('farm_started',dict(id='goal_1'))
            performance.event('stage','farm_drive')
            performance.event('farm_active',proof(id='other'))
            self.assertEqual(performance.failed_stage,'inspect_sp')
            performance.event('farm_active',proof())
            self.assertIsNone(performance.failed_stage)
            self.assertEqual(performance.probe.context,{})

    def test_performance_keeps_bound_car_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            performance=Performance('goal',path=Path(folder)/'performance.json')
            performance.event('cycle_stage',dict(batch_id='batch',cycle=1,phase='choose'))
            performance.event('failure',dict(stage='choose'))
            performance.event('farm_started',dict(id='goal_1'))
            performance.event('stage','farm_drive')
            performance.event('farm_active',proof())
            self.assertEqual(performance.failed_stage,'choose')


if __name__=='__main__':
    unittest.main()
