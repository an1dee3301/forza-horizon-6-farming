import unittest
from fh6.runtime_limits import RunSignal
from fh6.supervision import RetryDelay


class RunPermissionTests(unittest.TestCase):
    def test_retry_delay_has_no_attempt_limit_and_resets_only_on_progress(self):
        retry = RetryDelay()
        retry.observe('stage', 'collection')
        retry.observe('progress', dict(id='mission1', phase='convert', rewards=117, bought=117))
        self.assertEqual([retry.next() for _ in range(6)], [3, 6, 12, 15, 15, 15])
        retry.observe('stage', 'collection')
        retry.observe('progress', dict(id='mission1', phase='convert', rewards=117, bought=117, active_seconds=100))
        self.assertEqual(retry.next(), 15)
        for _ in range(100):
            self.assertEqual(retry.next(), 15)
        retry.observe('progress', dict(id='mission1', phase='convert', rewards=118, bought=118))
        self.assertEqual(retry.next(), 3)
        retry.observe('stage', 'choose')
        self.assertEqual(retry.next(), 3)

    def test_legacy_expired_deadline_cannot_stop_running_mission(self):
        run = RunSignal()
        run.set()
        run.configure(dict(end_at_deadline=True, deadline_utc='2026-09-10T00:00:00+00:00'))
        self.assertTrue(run.is_set())
        run.clear()
        self.assertFalse(run.is_set())

    def test_reload_cannot_override_f7(self):
        run = RunSignal()
        run.configure(dict(end_at_deadline=True, deadline_utc='2020-01-01T00:00:00+00:00'))
        run.configure({})
        self.assertFalse(run.is_set())
        run.set()
        self.assertTrue(run.is_set())
        run.clear()
        run.configure({})
        self.assertFalse(run.is_set())
