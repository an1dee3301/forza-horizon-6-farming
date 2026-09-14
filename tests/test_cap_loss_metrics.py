"""Coverage and denominator regressions for one estimated farm-waste metric."""
from copy import deepcopy
import math
import unittest

from fh6.operations_metrics import cap_loss_metrics,recent_cap_loss_metrics,summarize


class CapLossMetricTests(unittest.TestCase):
    def row(self,index,**changes):
        row=dict(id=f'goal_{index}',share_code='155439962',before_sp=0,after_sp=100,
                 gained_sp=100,capped=False,partial_timing=False,active_seconds=1000,
                 drive_seconds=800,raw_estimated_sp=100,estimated_cap_loss_sp=0,
                 exit_reason='natural_completion')
        row.update(changes)
        return row

    def result(self,rows):
        return cap_loss_metrics(dict(id='goal'),dict(goal_id='goal',farms=rows))

    def test_weighted_rate_includes_supported_zero_runs_and_whole_farm_time(self):
        rows=[self.row(1,before_sp=799,after_sp=999,gained_sp=200,capped=True,
                       raw_estimated_sp=242,estimated_cap_loss_sp=42,active_seconds=600,drive_seconds=300),
              self.row(2,active_seconds=1200,drive_seconds=300)]
        op=self.result(rows)
        self.assertEqual(op['cap_loss_rate_sp_estimated'],42)
        self.assertEqual(op['cap_loss_rate_seconds'],1800)
        self.assertEqual(op['cap_loss_sp_farm_hour_estimated'],84)
        self.assertEqual(op['cap_loss_mazda_farm_hour_estimated'],4)
        self.assertEqual((op['cap_loss_rate_samples'],op['cap_loss_rate_total_runs']),(2,2))

    def test_partial_timing_retained_cumulatively_excluded_from_rate(self):
        rows=[self.row(1),self.row(2,before_sp=899,after_sp=999,partial_timing=True,raw_estimated_sp=150,
                                   estimated_cap_loss_sp=50,capped=True)]
        op=self.result(rows)
        self.assertEqual(op['cap_loss_sp_estimated'],50)
        self.assertEqual(op['cap_loss_rate_sp_estimated'],0)
        self.assertEqual(op['cap_loss_rate_seconds'],1000)
        self.assertEqual(op['cap_loss_rate_excluded']['partial_timing'],1)
        self.assertIsNone(op['cap_loss_sp_farm_hour_estimated'])
        self.assertEqual(op['cap_loss_covered_sp_farm_hour_estimated'],0)

    def test_unknown_capped_losses_never_produce_global_zero(self):
        rows=[self.row(1),self.row(2,share_code=None,capped=True,before_sp=799,after_sp=999,
                                   gained_sp=200,raw_estimated_sp=None,estimated_cap_loss_sp=None)]
        op=self.result(rows)
        self.assertEqual(op['cap_loss_unknown_capped_runs'],1)
        self.assertIsNone(op['cap_loss_sp_farm_hour_estimated'])
        self.assertIsNone(op['cap_loss_mazda_farm_hour_estimated'])
        self.assertEqual(op['cap_loss_covered_sp_farm_hour_estimated'],0)
        self.assertEqual(op['cap_loss_rate_coverage_percent'],50)

    def test_empty_or_no_usable_coverage_stays_unknown(self):
        for rows in ([],[self.row(1,raw_estimated_sp=None,estimated_cap_loss_sp=None)],
                     [self.row(1,active_seconds=0)],[self.row(1,active_seconds=float('nan'))]):
            op=self.result(rows)
            self.assertIsNone(op['cap_loss_sp_farm_hour_estimated'])
            self.assertIsNone(op['cap_loss_rate_sp_estimated'])
            self.assertEqual(op['cap_loss_rate_samples'],0)

    def test_malformed_loss_does_not_become_zero(self):
        for value in (None,float('nan'),float('inf'),-1,False,'0'):
            op=self.result([self.row(1,estimated_cap_loss_sp=value)])
            self.assertIsNone(op['cap_loss_sp_farm_hour_estimated'])
            self.assertEqual(op['cap_loss_rate_excluded']['unsupported_estimate'],1)

    def test_uncapped_actual_zero_does_not_fabricate_underpredicted_raw(self):
        op=self.result([self.row(1,before_sp=754,after_sp=997,gained_sp=243,
                                 raw_estimated_sp=213,estimated_cap_loss_sp=0)])
        self.assertEqual(op['cap_loss_sp_farm_hour_estimated'],0)
        self.assertEqual(op['cap_loss_samples'],1)
        self.assertEqual(op['cap_loss_raw_samples'],0)
        self.assertIsNone(op['cap_loss_percent_estimated'])
        self.assertEqual(op['cap_loss_estimation_sources'],{'verified_uncapped_zero':1})

    def test_inconsistent_actual_balance_does_not_rescue_invalid_estimate(self):
        op=self.result([self.row(1,before_sp=754,after_sp=997,gained_sp=240,
                                 raw_estimated_sp=213,estimated_cap_loss_sp=0)])
        self.assertIsNone(op['cap_loss_sp_farm_hour_estimated'])

    def test_different_profiles_never_supply_historical_cap_estimates(self):
        samples=[self.row(i,share_code='169055890') for i in range(3)]
        capped=self.row(9,before_sp=949,after_sp=999,gained_sp=50,capped=True,
                        raw_estimated_sp=None,estimated_cap_loss_sp=0)
        op=self.result(samples+[capped])
        self.assertEqual(op['cap_loss_unknown_capped_runs'],1)

    def test_drive_and_whole_farm_denominators_never_mix(self):
        samples=[self.row(i,drive_seconds=None) for i in range(3)]
        capped=self.row(9,before_sp=949,after_sp=999,gained_sp=50,capped=True,
                        raw_estimated_sp=None,estimated_cap_loss_sp=None)
        op=self.result(samples+[capped])
        self.assertEqual(op['cap_loss_unknown_capped_runs'],1)

    def test_matching_profile_and_timer_cohort_can_estimate_capped_row(self):
        samples=[self.row(i) for i in range(3)]
        capped=self.row(9,before_sp=949,after_sp=999,gained_sp=50,capped=True,
                        raw_estimated_sp=None,estimated_cap_loss_sp=0)
        op=self.result(samples+[capped])
        self.assertEqual(op['cap_loss_sp_estimated'],50)
        self.assertEqual(op['cap_loss_rate_seconds'],4000)
        self.assertEqual(op['cap_loss_sp_farm_hour_estimated'],45)
        self.assertEqual(op['cap_loss_unknown_capped_runs'],0)

    def test_legacy_unknown_codes_are_not_assigned_to_mega_or_pooled(self):
        samples=[self.row(i,share_code=None) for i in range(3)]
        capped=self.row(9,share_code=None,before_sp=949,after_sp=999,gained_sp=50,capped=True,
                        raw_estimated_sp=None,estimated_cap_loss_sp=None)
        self.assertEqual(self.result(samples+[capped])['cap_loss_unknown_capped_runs'],1)

    def test_cohort_does_not_promote_partial_or_intentional_samples(self):
        for field,value in [('partial_timing',True),('exit_reason','intentional_target_top_up')]:
            samples=[self.row(i,**{field:value}) for i in range(3)]
            capped=self.row(9,before_sp=949,after_sp=999,gained_sp=50,capped=True,
                            raw_estimated_sp=None,estimated_cap_loss_sp=None)
            self.assertEqual(self.result(samples+[capped])['cap_loss_unknown_capped_runs'],1)

    def test_foreign_mission_and_unfinished_rows_do_not_enter_coverage(self):
        rows=[self.row(1),self.row(2,id='old_goal_2'),self.row(3,goal_id='old_goal'),
              self.row(4,phase='drive')]
        op=self.result(rows)
        self.assertEqual((op['cap_loss_rate_samples'],op['cap_loss_rate_total_runs']),(1,1))

    def test_summarization_does_not_mutate_source_rows(self):
        rows=[self.row(i) for i in range(3)]
        before=deepcopy(rows)
        self.result(rows)
        self.assertEqual(rows,before)

    def test_public_summary_tolerates_missing_invalid_timing(self):
        op=summarize(dict(id='goal'),dict(goal_id='goal',farms=[self.row(1,active_seconds=None)]))
        self.assertIsNone(op['cap_loss_sp_farm_hour_estimated'])
        self.assertEqual(op['cap_loss_rate_excluded']['missing_or_invalid_timing'],1)

    def test_contradictory_cap_flag_does_not_support_a_positive_loss(self):
        op=self.result([self.row(1,capped=True,raw_estimated_sp=150,estimated_cap_loss_sp=50)])
        self.assertEqual(op['cap_loss_unknown_capped_runs'],1)

    def test_malformed_native_timer_does_not_join_legacy_timer_cohort(self):
        samples=[self.row(i,drive_seconds='bad') for i in range(3)]
        capped=self.row(9,drive_seconds=None,before_sp=949,after_sp=999,gained_sp=50,capped=True,
                        raw_estimated_sp=None,estimated_cap_loss_sp=None)
        self.assertEqual(self.result(samples+[capped])['cap_loss_unknown_capped_runs'],1)

    def recent(self,rows):
        return recent_cap_loss_metrics(dict(id='goal'),dict(goal_id='goal',farms=rows))

    def test_recent_segment_starts_after_last_different_profile_not_last_bad_run(self):
        rows=[self.row(1,capped=True,before_sp=899,after_sp=999,
                       raw_estimated_sp=None,estimated_cap_loss_sp=None),
              self.row(2,share_code='169055890'),self.row(3),self.row(4),
              self.row(5,partial_timing=True)]
        before=deepcopy(rows)
        op=self.recent(rows)
        self.assertEqual(op['recent_cap_loss_cohort_start_id'],'goal_3')
        self.assertEqual(op['recent_cap_loss_share_code'],'155439962')
        self.assertEqual(op['recent_cap_loss_total_runs'],3)
        self.assertEqual(op['recent_cap_loss_rate_samples'],2)
        self.assertEqual(op['recent_cap_loss_rate_seconds'],2000)
        self.assertEqual(op['recent_cap_loss_partial_timing_runs'],1)
        self.assertEqual(op['recent_cap_loss_sp_farm_hour_estimated'],0)
        self.assertEqual(op['recent_cap_loss_sp_estimated'],0)
        self.assertEqual(op['recent_cap_loss_samples'],3)
        self.assertEqual(rows,before)

    def test_recent_segment_keeps_unknown_profile_rows_before_between_and_after_mega(self):
        rows=[self.row(1,share_code='169055890'),self.row(2,share_code=None),
              self.row(3),self.row(4,share_code=None),self.row(5),
              self.row(6,share_code=None)]
        op=self.recent(rows)
        self.assertEqual(op['recent_cap_loss_cohort_start_id'],'goal_2')
        self.assertEqual(op['recent_cap_loss_rate_samples'],5)
        self.assertEqual(op['recent_cap_loss_total_runs'],5)
        self.assertEqual(op['recent_cap_loss_rate_seconds'],5000)

    def test_recent_unknown_profile_capped_run_suppresses_zero_without_dropping_it(self):
        rows=[self.row(1,share_code='169055890'),self.row(2),
              self.row(3,share_code=None,before_sp=949,after_sp=999,gained_sp=50,
                       capped=True,raw_estimated_sp=None,estimated_cap_loss_sp=None),
              self.row(4)]
        op=self.recent(rows)
        self.assertEqual(op['recent_cap_loss_total_runs'],3)
        self.assertEqual(op['recent_cap_loss_unknown_capped_runs'],1)
        self.assertIsNone(op['recent_cap_loss_sp_farm_hour_estimated'])
        self.assertIsNone(op['recent_cap_loss_mazda_farm_hour_estimated'])
        self.assertEqual(op['recent_cap_loss_rate_samples'],2)
        self.assertEqual(op['recent_cap_loss_samples'],2)

    def test_recent_missing_outcome_stays_in_segment_and_suppresses_rate(self):
        rows=[self.row(1),self.row(2,after_sp=None,gained_sp=None,capped=None,
                                   raw_estimated_sp=None,estimated_cap_loss_sp=None),self.row(3)]
        op=self.recent(rows)
        self.assertEqual(op['recent_cap_loss_cohort_start_id'],'goal_1')
        self.assertEqual(op['recent_cap_loss_total_runs'],3)
        self.assertEqual(op['recent_cap_loss_rate_samples'],2)
        self.assertIsNone(op['recent_cap_loss_sp_farm_hour_estimated'])

    def test_recent_profile_boundary_is_selected_before_outcome_validation(self):
        rows=[self.row(1),self.row(2,share_code='169055890',after_sp=None,gained_sp=None,
                                   raw_estimated_sp=None,estimated_cap_loss_sp=None),self.row(3)]
        op=self.recent(rows)
        self.assertEqual(op['recent_cap_loss_cohort_start_id'],'goal_3')
        self.assertEqual(op['recent_cap_loss_total_runs'],1)

    def test_recent_mini_or_no_explicit_profile_never_reuses_old_mega_rate(self):
        for rows in ([],[self.row(1,share_code=None)],
                     [self.row(1),self.row(2,share_code='169055890'),self.row(3,share_code=None)]):
            self.assertTrue(all(value is None for value in self.recent(rows).values()))

    def test_recent_new_regime_after_later_mini_excludes_previous_mega_regime(self):
        rows=[self.row(1,share_code='169055890'),self.row(2),self.row(3),
              self.row(4,share_code='169055890'),self.row(5,share_code=None),self.row(6)]
        op=self.recent(rows)
        self.assertEqual(op['recent_cap_loss_cohort_start_id'],'goal_5')
        self.assertEqual(op['recent_cap_loss_total_runs'],2)

    def test_recent_rate_has_same_covered_loss_numerator_and_whole_farm_denominator(self):
        rows=[self.row(1,share_code='169055890'),
              self.row(2,before_sp=799,after_sp=999,gained_sp=200,capped=True,
                       raw_estimated_sp=242,estimated_cap_loss_sp=42,active_seconds=600,drive_seconds=300),
              self.row(3,active_seconds=1200,drive_seconds=300)]
        op=self.recent(rows)
        self.assertEqual(op['recent_cap_loss_rate_seconds'],1800)
        self.assertEqual(op['recent_cap_loss_sp_farm_hour_estimated'],84)
        self.assertEqual(op['recent_cap_loss_mazda_farm_hour_estimated'],4)

    def test_recent_capped_partial_timing_suppresses_rate_even_when_loss_known(self):
        op=self.recent([self.row(1),self.row(2,before_sp=899,after_sp=999,capped=True,
                       partial_timing=True,raw_estimated_sp=150,estimated_cap_loss_sp=50)])
        self.assertEqual(op['recent_cap_loss_partial_timing_runs'],1)
        self.assertEqual(op['recent_cap_loss_unknown_capped_runs'],0)
        self.assertIsNone(op['recent_cap_loss_sp_farm_hour_estimated'])

    def test_recent_mission_scope_does_not_let_foreign_mini_reset_boundary(self):
        op=self.recent([self.row(1),self.row(2,id='foreign_2',share_code='169055890')])
        self.assertEqual(op['recent_cap_loss_cohort_start_id'],'goal_1')
        self.assertEqual(op['recent_cap_loss_total_runs'],1)

    def test_summary_adds_recent_fields_without_changing_any_mission_loss_field(self):
        rows=[self.row(1,share_code=None,before_sp=899,after_sp=999,capped=True,
                       raw_estimated_sp=None,estimated_cap_loss_sp=None),
              self.row(2,share_code='169055890'),self.row(3),self.row(4,partial_timing=True)]
        goal=dict(id='goal'); source=dict(goal_id='goal',farms=rows)
        mission=cap_loss_metrics(goal,source)
        op=summarize(goal,source)
        self.assertEqual({key:op[key] for key in mission},mission)
        self.assertIsNone(op['cap_loss_sp_farm_hour_estimated'])
        self.assertEqual(op['recent_cap_loss_sp_farm_hour_estimated'],0)


if __name__=='__main__':unittest.main()
