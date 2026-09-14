import unittest

from fh6.farm_polling import active_countdown_only
from fh6.farming import FARM_FULL_AUDIT_SECONDS, remaining_seconds
from fh6.ocr import Document, Text


class FarmPollingTests(unittest.TestCase):
    def test_complete_farm_safety_scan_remains_frequent(self):
        self.assertLessEqual(FARM_FULL_AUDIT_SECONDS, 1.5)

    def document(self, value='04:32.165', extra=()):
        return Document([
            Text('Time Remaining', (50, 50, 170, 28)),
            Text(value, (240, 50, 110, 28)),
            *(Text(label, (50, 980, 180, 24)) for label in extra),
        ])

    def test_active_refined_countdown_skips_only_secondary_refinements(self):
        doc = self.document()
        self.assertTrue(active_countdown_only(doc, remaining_seconds(doc)))

    def test_missing_ambiguous_or_invalid_timer_keeps_full_refinement(self):
        for doc in (
            Document([]),
            self.document('04:72'),
            self.document('04:32 04:31'),
            self.document('unreadable'),
        ):
            self.assertFalse(active_countdown_only(doc, remaining_seconds(doc)))
        for value in (None, True, float('inf'), float('nan'), -1):
            self.assertFalse(active_countdown_only(self.document(), value))

    def test_partial_result_or_pause_overlay_never_uses_active_only_path(self):
        for label in ('Retry', 'Quit Event', 'Continue', 'Exit', 'Try Again',
                      'Restart Event', 'Resume', 'Paused', 'Challenge Failed',
                      'Success', 'Challenge Completed'):
            with self.subTest(label=label):
                doc = self.document(extra=(label,))
                self.assertFalse(active_countdown_only(doc, remaining_seconds(doc)))

    def test_near_expiry_keeps_result_refinement_before_timer_disappears(self):
        for value in ('00:00', '00:01.500', '00:02.000'):
            doc = self.document(value)
            self.assertFalse(active_countdown_only(doc, remaining_seconds(doc)))


if __name__ == '__main__':
    unittest.main()
