import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from fh6.performance import Performance
from fh6.transitions import TransitionProbe, summarize_transition_timing


class TransitionTimingTests(unittest.TestCase):
    def test_long_load_keeps_polling_inside_observed_latency(self):
        now = [0.]
        costs = [100., 50.]
        probe = TransitionProbe(lambda: now[0])
        probe.costs = lambda: tuple(costs)
        frame = np.zeros((1080, 1920, 3), np.uint8)
        probe.observe(frame, 'car_action')
        probe.input('enter')
        now[0] = .4
        probe.observe(frame, 'unknown')
        now[0] = 20.
        costs[:] = [112., 57.8]
        probe.finish()

        row = probe.rows[-1]
        self.assertEqual(row['observed_transition_seconds'], 20.)
        self.assertEqual(row['change_to_usable'], 19.6)
        self.assertEqual(row['polling_work_seconds'], 12.)
        self.assertAlmostEqual(row['programmed_pacing_seconds'], 7.8)
        self.assertAlmostEqual(row['unassigned_transition_seconds'], .2)
        self.assertAlmostEqual(row['ui_wait_estimate_seconds'], .2)
        self.assertIsNone(row['causal_game_seconds'])
        self.assertFalse(row['cost_accounting_clipped'])
        self.assertEqual(row['timing_basis'], 'input_to_observed_usable_includes_polling')

    def test_cost_accounting_drift_cannot_overfill_interval(self):
        now = [0.]
        costs = [0., 0.]
        probe = TransitionProbe(lambda: now[0])
        probe.costs = lambda: tuple(costs)
        probe.input('enter')
        now[0] = 1.
        costs[:] = [.8, .5]
        probe.finish()
        row = probe.rows[-1]
        self.assertAlmostEqual(sum(row[k] for k in (
            'polling_work_seconds', 'programmed_pacing_seconds',
            'unassigned_transition_seconds')), row['observed_transition_seconds'])
        self.assertTrue(row['cost_accounting_clipped'])

    def test_partial_and_legacy_rows_do_not_become_usable_coverage(self):
        now = [0.]
        probe = TransitionProbe(lambda: now[0])
        probe.input('enter')
        now[0] = 4.
        probe.finish('failed')
        probe.input('down')
        now[0] = 5.
        probe.input('down')  # Supersedes the previous interval.
        now[0] = 7.
        probe.finish()
        legacy = dict(outcome='usable', input_to_usable=30., ui_wait_estimate_seconds=.2)
        result = summarize_transition_timing([legacy, *probe.rows])
        self.assertEqual(result['usable_count'], 1)
        self.assertEqual(result['partial_count'], 2)
        self.assertEqual(result['legacy_count'], 1)
        self.assertEqual(result['observed_usable_seconds'], 2.)
        self.assertEqual(result['unassigned_within_usable_seconds'], 2.)
        self.assertIsNone(result['causal_game_seconds'])
        self.assertIsNone(probe.rows[0]['observed_transition_seconds'])
        self.assertIsNone(probe.rows[1]['observed_transition_seconds'])
        self.assertEqual(legacy, dict(outcome='usable', input_to_usable=30., ui_wait_estimate_seconds=.2))

    def test_unchanged_visual_still_has_latency_without_known_game_cause(self):
        now = [0.]
        probe = TransitionProbe(lambda: now[0])
        frame = np.zeros((1080, 1920, 3), np.uint8)
        probe.observe(frame, 'cars')
        probe.input('down')
        now[0] = .5
        probe.observe(frame, 'cars')
        probe.finish()
        self.assertEqual(probe.rows[-1]['observed_transition_seconds'], .5)
        self.assertIsNone(probe.rows[-1]['input_to_change'])
        self.assertIsNone(probe.rows[-1]['causal_game_seconds'])

    def test_cycle_summary_excludes_other_cycles_and_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            performance = Performance('goal', Path(folder) / 'performance.json')
            now = [0.]
            performance.probe.clock = lambda: now[0]
            performance.event('cycle_stage', dict(batch_id='batch', cycle=1, phase='choose'))
            performance.probe.input('enter')
            now[0] = 10.
            performance.decision_seconds = 6.
            performance.pacing_seconds = 3.
            performance.probe.finish()
            good = dict(performance.probe.rows[-1])
            performance.probe.rows.extend([
                dict(good, cycle=2),
                dict(good, batch_id='other'),
                dict(good, during_recovery=True),
            ])
            performance.cycle_decision['batch:1'] = 6.
            completed = dict(batch_id='batch', cycle=1)
            performance.event('cycle_complete', completed)
            self.assertEqual(completed['automation_decision_seconds'], 6.)
            self.assertEqual(completed['ui_wait_estimate_seconds'], 1.)
            diagnostic = completed['transition_timing']
            self.assertEqual(diagnostic['usable_count'], 1)
            self.assertEqual(diagnostic['observed_usable_seconds'], 10.)
            self.assertEqual(diagnostic['polling_work_within_usable_seconds'], 6.)
            self.assertEqual(diagnostic['programmed_pacing_within_usable_seconds'], 3.)
            self.assertEqual(diagnostic['unassigned_within_usable_seconds'], 1.)
            self.assertIsNone(diagnostic['causal_game_seconds'])
            self.assertFalse((Path(folder) / 'performance.json').exists())

    def test_cycle_aggregation_can_run_after_input_thread_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            performance = Performance('goal', Path(folder) / 'performance.json')
            performance.mark_event('cycle_stage',
                dict(batch_id='batch',cycle=1,phase='choose'))
            performance.cycle_decision['batch:1'] = 4.
            completed = dict(batch_id='batch',cycle=1)
            performance.mark_event('cycle_complete', completed)
            self.assertNotIn('automation_decision_seconds', completed)
            self.assertIsNone(performance.cycle_key)
            performance.enrich_event('cycle_complete', completed)
            self.assertEqual(completed['automation_decision_seconds'], 4.)
            self.assertIn('transition_timing', completed)

    def test_background_direct_snapshot_keeps_queue_health(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'performance.json'
            performance = Performance('goal', path)
            stream = SimpleNamespace(queue=SimpleNamespace(qsize=lambda: 3),
                                     dropped=1,errors=2)
            performance.flush(stream=stream,direct=True)
            import json
            saved=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['diagnostic_queue'],
                             {'pending':3,'dropped':1,'errors':2})

    def test_measurement_aggregation_is_queued_off_control_thread(self):
        class Stream:
            def __init__(self): self.items = []
            def submit(self, action, *args):
                self.items.append((action, args))
                return True
        with tempfile.TemporaryDirectory() as folder:
            stream = Stream()
            performance = Performance('goal', Path(folder) / 'performance.json',
                                      stream=stream)
            performance.mark_event('cycle_stage',
                dict(batch_id='batch', cycle=7, phase='choose'))
            performance.mark_event('stage', 'choose')
            self.assertEqual(performance.measure('capture', lambda: 42), 42)
            self.assertEqual(performance.totals, {})
            self.assertNotIn('batch:7', performance.cycle_decision)
            self.assertEqual(len(stream.items), 1)

            action, args = stream.items.pop(0)
            action(*args)
            self.assertEqual(performance.totals['choose/capture']['count'], 1)
            self.assertGreaterEqual(performance.cycle_decision['batch:7'], 0)


if __name__ == '__main__':
    unittest.main()
