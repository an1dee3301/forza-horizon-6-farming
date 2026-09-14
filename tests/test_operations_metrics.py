import tempfile
import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from fh6.operations_metrics import summarize,percentiles,failure_cause
from fh6.refill_policy import plan,refill_target
from fh6.batching import funded_cars
from fh6.transitions import TransitionProbe
from fh6.analytics import Tracker
from fh6.farming import Challenge
from fh6.ocr import Document,Text


class OperationsTests(unittest.TestCase):
    def test_percentiles_include_tail_and_exclude_missing(self):
        self.assertEqual(percentiles([None,1,2,3,100,float('nan')]),dict(n=4,p50=2.5,p90=100,p99=100))

    def test_rates_use_new_rewards_not_starting_inventory_and_weight_durations(self):
        goal=dict(rewards=10,active_seconds=3600,started_at='2026-09-12T00:00:00+00:00',starting_spins_counted=333)
        source=dict(cycles=[dict(elapsed_seconds=60),dict(elapsed_seconds=120)],
                    farms=[dict(share_code='155439962',before_sp=0,after_sp=100,gained_sp=100,active_seconds=1000),
                           dict(share_code='155439962',before_sp=100,after_sp=400,gained_sp=300,active_seconds=1000)])
        op=summarize(goal,source,datetime(2026,9,12,2,tzinfo=timezone.utc))
        self.assertEqual((op['sw_active_hour'],op['sw_wall_hour']),(10,5))
        self.assertEqual(op['conversion_capacity'],40)
        self.assertEqual(op['retained_sp_hour'],720)
        self.assertEqual(op['bottleneck'],'SP FARM')
        self.assertLess(op['combined_capacity'],op['farm_capacity'])

    def test_current_profile_boundary_precedes_eligibility_and_unknown_is_not_zero(self):
        def farm(code,gain,**kw):
            return dict(share_code=code,before_sp=0,after_sp=gain,gained_sp=gain,active_seconds=3600,**kw)
        rows=[farm('155439962',50),farm('169055890',900),farm('155439962',300),
              farm('155439962',999,partial_timing=True)]
        op=summarize({},dict(farms=rows))
        self.assertEqual(op['retained_sp_hour'],300)
        self.assertEqual(op['rate_coverage']['farm_n'],1)
        self.assertEqual(op['rate_coverage']['farm_total'],2)
        self.assertIsNone(summarize({},dict(farms=[farm(None,300)]))['retained_sp_hour'])

    def test_tax_is_weighted_versioned_residual_and_reports_excluded_coverage(self):
        def row(elapsed,residual,observed):
            return dict(elapsed_seconds=elapsed,transition_timing=dict(version=2,usable_count=2,
                        partial_count=1,unassigned_within_usable_seconds=residual,observed_usable_seconds=observed))
        rows=[row(50,5,40),row(100,2,80),row(10,8,20),dict(elapsed_seconds=100)]
        op=summarize({},dict(cycles=rows))
        self.assertAlmostEqual(op['forza_tax_percent_estimated'],700/150)
        self.assertEqual(op['forza_tax_coverage']['n'],2)
        self.assertEqual(op['forza_tax_coverage']['total'],4)
        self.assertEqual(op['forza_tax_coverage']['partial_count'],2)
        self.assertIsNone(summarize({},dict(cycles=rows,telemetry_dropped=1))['forza_tax_percent_estimated'])
        self.assertIsNone(summarize({},dict(cycles=[dict(elapsed_seconds=100)]))['attribution']['recovery'])

    def test_first_pass_and_cause_denominator_share_completed_cohort(self):
        cycles=[dict(batch_id='a',cycle=i,elapsed_seconds=50,recovery_tracking_version=2,recovery_events=int(i==2)) for i in [1,2]]
        source=dict(cycles=cycles,failures=[dict(batch_id='a',cycle=2,cause='choose_timeout',recovery_seconds=90),dict(batch_id='a',cycle=3,cause='choose_timeout',recovery_seconds=9)])
        op=summarize({},source)
        self.assertEqual(op['first_pass_yield'],50)
        self.assertEqual(op['failures']['choose_timeout']['per_100_cars'],50)
        self.assertEqual(op['failures']['choose_timeout']['recovery_seconds'],99)

    def test_incomplete_farm_timing_does_not_bias_rate(self):
        op=summarize({},dict(farms=[dict(gained_sp=999,active_seconds=1,partial_timing=True)]))
        self.assertIsNone(op['retained_sp_hour'])
        self.assertIsNone(op['cap_loss_sp_estimated'])

    def test_cap_loss_is_estimate_with_raw_denominator(self):
        op=summarize({},dict(farms=[dict(raw_estimated_sp=400,estimated_cap_loss_sp=160)]))
        self.assertEqual(op['cap_loss_percent_estimated'],40)

    def test_retry_taxonomy(self):
        for message,stage,cause in [('Timed out waiting for garage','choose','choose_timeout'),('Unexpected screen','return','unexpected_screen'),('Game focus lost','choose','focus_lost'),('Purchase receipt unclear','buy','purchase_fail'),('Could not read the available points','mastery','OCR_fail')]:
            self.assertEqual(failure_cause(message,stage),cause)

    def test_menu_focus_is_distinct_from_game_window_focus_and_timeout_uses_stage(self):
        self.assertEqual(failure_cause('Could not identify keyboard focus for Car Collection', 'return'),
                         'menu_focus_detection')
        self.assertEqual(failure_cause('Game focus lost (desktop)', 'return'), 'focus_lost')
        message = 'Timed out waiting for campaign, car_mastery, cars, mad_mike_mastery; no input retry'
        self.assertEqual(failure_cause(message, 'return'), 'return_timeout')
        self.assertEqual(failure_cause(message, 'choose'), 'choose_timeout')
        self.assertEqual(failure_cause('Timed out verifying owned mastery node', 'mastery'), 'mastery_detection')

    def test_probe_separates_change_and_usable_without_extra_captures(self):
        now=[0.];p=TransitionProbe(lambda:now[0]);frame=np.zeros((1080,1920,3),np.uint8)
        p.observe(frame,'cars');p.input('enter');now[0]=.2;p.observe(frame,'unknown');now[0]=1.;p.finish()
        self.assertEqual(p.rows[-1]['input_to_change'],.2)
        self.assertEqual(p.rows[-1]['change_to_usable'],.8)
        p.input('down');p.input('down');self.assertEqual(p.rows[-1]['outcome'],'superseded')
        self.assertIsNone(p.rows[-1]['input_to_usable'])

    def test_refill_targets_skip_unusable_tail_and_fund_final_target(self):
        self.assertEqual(refill_target(1000),987)
        self.assertEqual(refill_target(3,10),73)
        self.assertEqual(funded_cars(987,1000),47)
        self.assertEqual(funded_cars(986,1000),0)
        self.assertEqual(funded_cars(966,1000,allow_partial=True),46)
        self.assertEqual(funded_cars(63,3),3)

    def test_only_last_top_up_shortens_and_requires_measured_yield(self):
        farms=[dict(share_code='155439962',gained_sp=370,drive_seconds=900,
                    active_seconds=1000,exit_reason='natural_completion') for _ in range(5)]
        self.assertEqual(plan(12,987,farms)['planned_exit'],'natural_completion')
        top=plan(750,987,farms)
        self.assertEqual(top['planned_exit'],'target_top_up')
        self.assertTrue(420<=top['planned_drive_seconds']<=600)
        self.assertEqual(plan(750,987,[])['planned_exit'],'convert_existing')

    def test_failure_closes_at_checkpoint_advancement_not_retry_start(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[0.];t=Tracker(folder,lambda:now[0])
            t.event('activity',True);t.event('stage','choose')
            context=dict(batch_id='a',cycle=1,phase='choose')
            t.event('cycle_stage',context);now[0]=2
            t.event('failure',dict(stage='choose',message='Timed out waiting'))
            t.event('cycle_stage',context);self.assertIsNotNone(t.data.get('open_failure'))
            now[0]=12;t.event('cycle_stage',dict(context,phase='mastery'))
            self.assertEqual(t.data['failures'][0]['recovery_seconds'],10)

    def test_early_exit_never_confirms_an_unrelated_yes_dialog(self):
        nav=Mock();nav.is_roam.return_value=False;nav.is_home.return_value=False
        nav.observe.return_value=SimpleNamespace(screen='unknown',doc=Document([Text('Delete car',(0,0,100,20)),Text('Yes',(0,30,100,20)),Text('No',(0,60,100,20))]))
        with tempfile.TemporaryDirectory() as folder:
            c=Challenge(nav,path=folder+'/challenge.json')
            with self.assertRaisesRegex(RuntimeError,'Unexpected early-exit'):
                c.leave_early()
        nav.click_label.assert_not_called()


if __name__=='__main__': unittest.main()
