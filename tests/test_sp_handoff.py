"""Repeated planning must reuse only current, twice-verified SP evidence."""
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import forza_cycle as core
from fh6.farming import FarmNavigator
from fh6.points import recent_sp, remember_sp


class SPHandoffTests(unittest.TestCase):
    def setUp(self):
        self.clock = 10.
        self.nav = FarmNavigator(None, None, None, {}, 'Forza', Event())
        self.nav.check = Mock()
        self.nav.pause = Mock()
        self.first = SimpleNamespace(screen='car_mastery', frame=object())
        self.second = SimpleNamespace(screen='car_mastery', frame=object())
        self.nav.observe = Mock(return_value=self.first)
        def wait(*args, **kwargs):
            self.nav.last = self.second
            self.nav._ready = (self.second, self.clock)
            return self.second
        self.nav.wait = Mock(side_effect=wait)
        self.time_patch = patch('fh6.points.time.monotonic', side_effect=lambda: self.clock)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)

    def seed(self, points=552):
        self.nav.invalidate_ready()
        with patch('fh6.farming.read_points', side_effect=[points, points]) as reader:
            self.assertEqual(self.nav.available_sp(), points)
        self.assertEqual(reader.call_count, 2)
        self.assertIsNotNone(recent_sp(self.nav))

    def test_repeated_planning_keeps_original_two_frame_balance(self):
        self.seed()
        with patch('fh6.farming.read_points', side_effect=AssertionError('duplicate OCR')):
            self.assertEqual(self.nav.available_sp(), 552)
            self.assertEqual(self.nav.available_sp(), 552)
        self.assertEqual(self.nav.observe.call_count, 1)
        self.assertEqual(self.nav.wait.call_count, 1)

    def test_new_input_token_requires_two_new_reads(self):
        self.seed()
        self.nav.invalidate_ready()
        self.assertIsNone(recent_sp(self.nav))
        with patch('fh6.farming.read_points', side_effect=[531, 531]) as reader:
            self.assertEqual(self.nav.available_sp(), 531)
        self.assertEqual(reader.call_count, 2)

    def test_expiry_or_new_observation_cannot_reuse_balance(self):
        self.seed()
        self.clock += .751
        self.assertIsNone(recent_sp(self.nav))
        self.clock = 10.
        self.nav.last = self.first
        self.assertIsNone(recent_sp(self.nav))
        self.nav.last = self.second
        self.nav._ready = (self.second, self.clock)
        self.assertIsNone(recent_sp(self.nav))

    def test_f7_and_sync_failures_cannot_return_cached_sp(self):
        for error in [core.MasteryStopped('F7'), RuntimeError('sync pending')]:
            self.nav.check.side_effect = None
            self.seed()
            self.nav.check.side_effect = error
            with self.assertRaises(type(error)):
                self.nav.available_sp()

    def test_focus_restoration_invalidates_proof_during_check(self):
        self.seed()
        self.nav.check.side_effect = self.nav.invalidate_ready
        self.assertIsNone(recent_sp(self.nav))

    def test_slow_guard_check_cannot_extend_proof_lifetime(self):
        self.seed()
        def delayed_check():
            self.clock += .751
        self.nav.check.side_effect = delayed_check
        self.assertIsNone(recent_sp(self.nav))

    def test_disagreement_never_creates_or_preserves_sp_proof(self):
        self.seed()
        self.nav.invalidate_ready()
        with patch('fh6.farming.read_points', side_effect=[552, 553]):
            with self.assertRaisesRegex(RuntimeError, 'SP changed'):
                self.nav.available_sp()
        self.assertIsNone(recent_sp(self.nav))

    def test_saved_values_wrong_menus_and_invalid_balances_are_not_proofs(self):
        self.nav._verified_sp = dict(points=552, observed_at=self.clock)
        self.assertIsNone(recent_sp(self.nav))
        for points in [-1, 1000, True, '552']:
            remember_sp(self.nav, points)
            self.assertIsNone(recent_sp(self.nav))
        self.second.screen = 'cars'
        self.nav.last = self.second
        self.nav._ready = (self.second, self.clock)
        remember_sp(self.nav, 552)
        self.assertIsNone(recent_sp(self.nav))


if __name__ == '__main__':
    unittest.main()
