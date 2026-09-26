"""Offline proof that faster recognition does not weaken mastery evidence."""
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from forza_cycle import MasteryStopped, NODES, mastery_once, similarity


class SimilaritySpeedTests(unittest.TestCase):
    def test_bgr_fast_path_preserves_absolute_color_error(self):
        random = np.random.default_rng(6)
        for shape in [(1, 1, 3), (36, 440, 3), (86, 610, 3)]:
            a = random.integers(0, 256, shape, dtype=np.uint8)
            b = random.integers(0, 256, shape, dtype=np.uint8)
            expected = 1 - float(np.abs(a.astype(np.float64) - b).mean()) / 255
            self.assertAlmostEqual(similarity(a, b), expected, places=14)
            self.assertEqual(similarity(a, a), 1)
        self.assertEqual(similarity(np.zeros((2, 3, 3), np.uint8),
                                    np.ones((2, 3, 3), np.uint8) * 255), 0)

    def test_non_bgr_and_invalid_shapes_keep_existing_behavior(self):
        for dtype in [np.uint8, np.float32]:
            a = np.array([[0, 50], [100, 200]], dtype=dtype)
            b = np.zeros_like(a)
            self.assertAlmostEqual(similarity(a, b), 1 - 87.5 / 255)
        self.assertEqual(similarity(np.zeros((1, 2, 3)), np.zeros((2, 1, 3))), 0)
        self.assertEqual(similarity(np.zeros((0, 0, 3)), np.zeros((0, 0, 3))), 0)


class MasteryFreshnessTests(unittest.TestCase):
    def run_cycle(self, *, stop_before_claim=False, aged=False, owned_flicker=False,
                  unknown_reads=(), known_screen_at=None, expect_error=False, fast=True):
        running = Event()
        running.set()
        state = dict(clock=0.0, owned=0, selected=0, epoch=0, observations=[],
                     actions=[], owned_reads=0, guards=0)

        def check():
            state['guards'] += 1

        running.input_guard = check

        def inspect(frame):
            state['clock'] += .001
            index = len(state['observations']) + 1
            if index in unknown_reads or index == known_screen_at:
                result = dict(screen='cars' if index == known_screen_at else 'unknown')
                state['observations'].append(dict(result=result, epoch=state['epoch']))
                return result
            nodes = {name: dict(state='owned' if i < state['owned'] else
                               'available' if i == state['owned'] else 'unavailable')
                     for i, (name, *_) in enumerate(NODES)}
            if state['owned']:
                state['owned_reads'] += 1
                if owned_flicker and state['owned_reads'] == 3:
                    nodes[NODES[state['owned'] - 1][0]]['state'] = 'unknown'
            result = dict(screen='mad_mike_mastery', nodes=nodes,
                          selection=dict(name=NODES[state['selected']][0]),
                          mastery_path_owned=all(n['state'] == 'owned' for n in nodes.values()))
            state['observations'].append(dict(result=result, epoch=state['epoch']))
            if stop_before_claim and len(state['observations']) == 3:
                running.clear()
            return result

        def assert_owned():
            if state['owned']:
                prior = NODES[state['owned'] - 1][0]
                self.assertTrue(all(o['result']['nodes'][prior]['state'] == 'owned'
                                    for o in state['observations'][-3:]))

        def down(key):
            self.assertTrue(running.is_set())
            self.assertGreater(state['guards'], 0)
            if key == 'enter':
                current = NODES[state['selected']][0]
                proofs = state['observations'][-3:]
                self.assertEqual(len(proofs), 3)
                for proof in proofs:
                    self.assertEqual(proof['epoch'], state['epoch'])
                    self.assertEqual(proof['result']['selection']['name'], current)
                    self.assertEqual(proof['result']['nodes'][current]['state'], 'available')
                state['owned'] += 1
                state['owned_reads'] = 0
            else:
                assert_owned()
                self.assertEqual(key, 'right' if state['selected'] < 2 else 'up')
                state['selected'] += 1
            state['actions'].append(key)
            state['epoch'] += 1

        def sleep(seconds):
            state['clock'] += seconds

        def perf_counter():
            # Model an observation becoming stale before it can be reused.
            state['clock'] += .09 if aged else 0
            return state['clock']

        fake = SimpleNamespace(moveTo=lambda *a, **k: None, keyDown=down,
                               keyUp=lambda key: None)
        with patch.dict('sys.modules', {'pyautogui': fake}), \
             patch('forza_cycle.foreground_title', return_value='Forza Horizon 6'), \
             patch('forza_cycle.time.sleep', side_effect=sleep), \
             patch('forza_cycle.time.monotonic', side_effect=lambda: state['clock']), \
             patch('forza_cycle.time.perf_counter', side_effect=perf_counter), \
             patch('builtins.print'):
            try:
                mastery_once(SimpleNamespace(inspect=inspect),
                             SimpleNamespace(grab=lambda _: np.zeros((1, 1, 3), np.uint8)),
                             dict(left=0, top=0), 'Forza Horizon 6', running, fast=fast)
            except MasteryStopped:
                state['stopped'] = True
            except RuntimeError as exc:
                if not expect_error:
                    raise
                state['error'] = str(exc)
        if not stop_before_claim and not expect_error:
            assert_owned()
        return state

    def test_every_enter_has_three_distinct_current_selection_proofs(self):
        state = self.run_cycle()
        self.assertEqual(state['actions'].count('enter'), 6)
        self.assertEqual(len(state['observations']), 36)

    def test_aged_frames_are_recaptured(self):
        state = self.run_cycle(aged=True)
        self.assertEqual(state['actions'].count('enter'), 6)
        self.assertGreater(len(state['observations']), 36)

    def test_f7_after_third_selection_proof_prevents_enter(self):
        state = self.run_cycle(stop_before_claim=True)
        self.assertTrue(state['stopped'])
        self.assertEqual(state['actions'], [])

    def test_owned_flicker_requires_three_new_consecutive_owned_reads(self):
        state = self.run_cycle(owned_flicker=True)
        self.assertEqual(state['actions'].count('enter'), 6)
        self.assertGreater(len(state['observations']), 36)

