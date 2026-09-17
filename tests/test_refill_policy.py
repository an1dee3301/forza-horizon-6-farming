import copy
import unittest
from types import SimpleNamespace

from fh6.batching import funded_cars
from fh6.refill_control import force_exact_target
from fh6.refill_policy import MEGA, _legacy_plan, plan


def natural(gain=373, drive=916, *, before=0, **fields):
    return dict(share_code=MEGA, before_sp=before, after_sp=before + gain,
                gained_sp=gain, drive_seconds=drive, active_seconds=1100,
                capped=False, partial_timing=False, exit_reason='natural_completion', **fields)


def measured():
    # Paired observations from this mission. Native drive and whole-farm active
    # time are intentionally different. Historical missing profiles stay unknown.
    rows = [natural(373, 915.784, before=11),
            natural(379, 917.366, before=3),
            natural(372, 917.335, before=382)]
    rows[0].pop('share_code')
    for before, gain, drive in [(756, 242, 600.572), (754, 243, 600.338)]:
        row = natural(gain, drive, before=before)
        row.update(exit_reason='intentional_target_top_up', partial_timing=True)
        if before == 756:
            row.pop('share_code')
        rows.append(row)
    return rows


class RefillPolicyTests(unittest.TestCase):
    def test_terminal_reserve_overrides_convert_and_runs_a_bounded_topup(self):
        normal = plan(991, 999, measured())
        self.assertEqual(normal['mode'], 'convert')
        forced = force_exact_target(normal, 991, 999,
                                    SimpleNamespace(duration_seconds=900))
        self.assertEqual(forced['mode'], 'topup')
        self.assertEqual(forced['planned_exit'], 'target_top_up')
        self.assertGreaterEqual(forced['planned_drive_seconds'], 60)
        self.assertLessEqual(forced['planned_drive_seconds'], 900)
        self.assertEqual(forced['reason'], 'terminal_exact_target')

    def test_actual_first_two_runs_are_bulk(self):
        for before in (3, 382):
            result = plan(before, 987, measured())
            self.assertEqual(result['mode'], 'bulk')
            self.assertEqual(result['planned_drive_seconds'], 900)
            self.assertEqual(result['expected_yield_sp'], 375.5)
            self.assertEqual(result['safety_margin_sp'], 6)
            self.assertLessEqual(result['expected_yield_sp'] + result['safety_margin_sp'], result['headroom_sp'])

    def test_proven_754_topup_stays_600_and_partial_pairs_are_named(self):
        result = plan(754, 987, measured())
        self.assertEqual((result['mode'], result['planned_drive_seconds']), ('topup', 600))
        self.assertEqual(result['deadline_basis'], 'observed_600s_balance_pairs')
        self.assertEqual(result['top_up_calibration_samples'], 1)
        self.assertEqual(result['top_up_calibration_uncertainty'], 'single_verified_balance_pair')
        self.assertTrue(result['top_up_calibration_partial_timing'])
        self.assertEqual(result['native_yield_samples'], 2)
        self.assertEqual(result['yield_samples'], 2)
        self.assertTrue(result['yield_small_sample'])
        self.assertEqual(result['headroom_sp'], 245)

    def test_high_sp_deadline_can_shrink_below_old_420_floor(self):
        result = plan(850, 987, measured())
        self.assertEqual(result['mode'], 'topup')
        self.assertLess(result['planned_drive_seconds'], 420)
        self.assertLessEqual(result['planned_drive_seconds'], result['headroom_drive_limit_seconds'])
        fastest = max(r['gained_sp'] / r['drive_seconds'] for r in measured()[:3])
        projected = fastest * (result['planned_drive_seconds'] + result['exit_guard_seconds'])
        self.assertLessEqual(projected + result['top_up_safety_margin_sp'], result['headroom_sp'])

    def test_full_yield_that_cannot_fit_is_not_a_bulk_run(self):
        result = plan(620, 987, measured())
        self.assertGreater(result['expected_yield_sp'] + result['safety_margin_sp'], result['headroom_sp'])
        self.assertEqual(result['mode'], 'topup')
        self.assertLessEqual(result['planned_drive_seconds'], 900)
        self.assertLessEqual(result['planned_drive_seconds'], result['headroom_drive_limit_seconds'])

    def test_tiny_gap_converts_actual_funded_balance(self):
        result = plan(978, 987, measured())
        self.assertEqual((result['mode'], result['planned_exit'], result['planned_drive_seconds']),
                         ('convert', 'convert_existing', 0))
        self.assertEqual(result['funded_cars'], 46)
        self.assertEqual(funded_cars(978, 47, allow_partial=True), 46)

    def test_reserve_is_not_spendable_and_no_funded_car_still_refills(self):
        result = plan(40, 42, measured(), reserve_sp=21)
        self.assertEqual(result['funded_cars'], 0)
        self.assertEqual(result['mode'], 'topup')
        result = plan(63, 84, measured(), reserve_sp=21)
        self.assertEqual(result['mode'], 'convert')
        self.assertEqual(result['funded_cars'], 2)

    def test_target_already_funded_avoids_a_launch(self):
        result = plan(997, 987, measured())
        self.assertEqual(result['mode'], 'convert')
        self.assertEqual(result['needed_sp'], 0)

    def test_final_small_target_does_not_run_a_full_farm(self):
        result = plan(0, 21, measured())
        self.assertEqual(result['mode'], 'topup')
        self.assertLess(result['planned_drive_seconds'], 420)

    def test_legacy_active_seconds_never_mix_with_native_drive_rate(self):
        rows = measured()
        for _ in range(10):
            row = natural(370)
            row.pop('drive_seconds')
            row['active_seconds'] = 2000
            rows.append(row)
        result = plan(850, 987, rows)
        self.assertEqual(result['yield_timer_basis'], 'native_drive')
        self.assertAlmostEqual(result['estimated_sp_per_second'], (379 / 917.366 + 372 / 917.335) / 2)
        self.assertEqual(result['legacy_yield_samples'], 10)

    def test_one_native_plus_legacy_do_not_reach_two_native_samples(self):
        rows = measured()[1:2]
        for _ in range(3):
            row = natural(370)
            row.pop('drive_seconds')
            rows.append(row)
        result = plan(850, 987, rows)
        self.assertEqual(result['mode'], 'convert')
        self.assertIsNone(result['estimated_sp_per_second'])
        self.assertEqual(result['yield_timer_basis'], 'legacy_full_yield_only')
        self.assertEqual(result['expected_yield_sp'], 370)

    def test_profile_invalid_capped_partial_and_incoherent_rows_excluded(self):
        invalid = []
        for patch in [dict(share_code='169055890'), dict(share_code=None),
                      dict(capped=True), dict(partial_timing=True),
                      dict(exit_reason='interrupted'), dict(drive_seconds=100),
                      dict(drive_seconds=float('nan')), dict(drive_seconds=-1), dict(drive_seconds=False),
                      dict(after_sp=999), dict(after_sp=374), dict(gained_sp=True)]:
            row = natural()
            row.update(patch)
            invalid.append(row)
        result = plan(850, 987, measured() + invalid)
        self.assertEqual(result['native_yield_samples'], 2)
        self.assertEqual(result['legacy_yield_samples'], 0)

    def test_per_cohort_window_uses_ten_recent_samples(self):
        rows = [natural(300)] * 10 + [natural(400)] * 10
        result = plan(0, 987, rows)
        self.assertEqual(result['yield_samples'], 10)
        self.assertEqual(result['expected_yield_sp'], 400)

    def test_uncalibrated_funded_balance_converts_instead_of_guessing(self):
        result = plan(850, 987, [])
        self.assertEqual(result['mode'], 'convert')
        self.assertEqual(result['yield_timer_basis'], 'insufficient_samples')
        self.assertIsNone(result['expected_yield_sp'])
        self.assertEqual(plan(0, 987, [])['mode'], 'bulk')

    def test_mini_policy_is_unchanged(self):
        rows = []
        for _ in range(3):
            row = natural(132, 298)
            row['share_code'] = '169055890'
            rows.append(row)
        for before in (0, 850, 990):
            self.assertEqual(plan(before, 987, rows, 298, '169055890', reserve_sp=21),
                             _legacy_plan(before, 987, rows, 298, '169055890'))

    def test_planning_does_not_mutate_records_or_previous_plan(self):
        rows = measured()
        original = copy.deepcopy(rows)
        pinned = plan(754, 987, rows)
        saved = copy.deepcopy(pinned)
        plan(850, 987, rows)
        self.assertEqual(rows, original)
        self.assertEqual(pinned, saved)

    def test_estimates_never_authorize_a_47th_car(self):
        self.assertTrue(plan(754, 987, measured())['estimate_only'])
        self.assertEqual(funded_cars(986, 47, allow_partial=True), 46)
        self.assertEqual(funded_cars(987, 47, allow_partial=True), 47)

    def test_invalid_balances_fail_before_making_a_plan(self):
        for args in [(True, 987), (-1, 987), (1000, 987), (0, 1000)]:
            with self.assertRaises(ValueError):
                plan(*args, measured())

    def test_no_convert_skip_loop_when_reserve_leaves_no_spendable_car(self):
        with self.assertRaisesRegex(ValueError, 'no funded car'):
            plan(998, 999, measured(), reserve_sp=978)

    def test_unknown_profiles_cannot_train_or_calibrate(self):
        rows = measured()
        for row in rows:
            row.pop('share_code', None)
        result = plan(754, 987, rows)
        self.assertEqual(result['native_yield_samples'], 0)
        self.assertEqual(result['legacy_yield_samples'], 0)
        self.assertEqual(result['top_up_calibration_samples'], 0)
        self.assertEqual(result['mode'], 'convert')


if __name__ == '__main__':
    unittest.main()
