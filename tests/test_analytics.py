import json
import tempfile
import unittest
from pathlib import Path

from fh6.analytics import Tracker, forecast, export_csv, panel_data, read


class AnalyticsTests(unittest.TestCase):
    def test_forecast_uses_current_profile_paired_full_runs_without_selecting_fast_cars(self):
        def farm(code, seconds, gain=370, **kw):
            return dict(dict(goal_id='new', share_code=code, active_seconds=seconds,
                             before_sp=10, after_sp=10+gain, gained_sp=gain,
                             capped=False, partial_timing=False, exit_reason='natural_completion'), **kw)
        samples = dict(farms=[farm('155439962', 1800), farm('169055890', 400, 130),
                             farm('155439962', 990), farm('155439962', 1010),
                             farm('155439962', 620, 240, exit_reason='intentional_target_top_up'),
                             farm('155439962', 20, partial_timing=True)],
                       farm_seconds=[400], farm_yields=[130])
        data = forecast(self.goal(), {}, samples, [40, 50, 1260, float('nan')])
        self.assertEqual((data['farm_seconds'], data['sp_per_farm'], data['farm_samples']), (1000, 370, 2))
        self.assertEqual(data['forecast_farm_share_code'], '155439962')
        self.assertEqual((data['cycle_seconds'], data['cycle_samples']), (50, 3))
        samples['farms'].append(farm('169055890', 30, partial_timing=True))
        data = forecast(self.goal(), {}, samples, [])
        self.assertEqual(data['farm_samples'], 0)
        self.assertEqual(data['forecast_farm_share_code'], '169055890')
        self.assertIn('planning defaults', data['forecast_farm_basis'])

    def test_chart_points_keep_actual_sp_verification_time_and_reset_with_mission(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(folder)
            tracker.event('progress',self.goal(last_sp=999,sp_observed_at='2026-09-11T01:00:00'))
            tracker.event('progress',self.goal(last_sp=999,rewards=1,sp_observed_at='2026-09-11T01:00:00'))
            self.assertEqual(tracker.data['progress_points'][-1]['sp_at'],'2026-09-11T01:00:00')
            tracker.event('progress',self.goal(last_sp=999,rewards=1,sp_observed_at='2026-09-11T02:00:00'))
            self.assertEqual(len(tracker.data['progress_points']),3)
            tracker.event('progress',self.goal(id='another',last_sp=None))
            self.assertEqual(len(tracker.data['progress_points']),1)
            self.assertEqual(tracker.data['progress_points'][0]['earned'],0)

    def test_garage_cleanup_records_confirmed_removals_and_exports_them(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(folder)
            tracker.event('progress',self.goal())
            tracker.event('garage_cleanup_started',{'filter':'S1 + Drift Cars + Duplicates'})
            tracker.event('garage_removed',{'count':3})
            tracker.event('garage_removed',{'count':2})
            tracker.event('garage_cleanup_completed',{})
            cleanup=tracker.data['garage_cleanup']
            self.assertEqual(cleanup['removed'],5)
            self.assertFalse(cleanup['active'])
            rows=(Path(folder)/'analytics_garage_cleanup.jsonl').read_text().splitlines()
            self.assertEqual([json.loads(row)['count'] for row in rows],[3,2])
            self.assertTrue((export_csv(folder)/'garage_cleanup.csv').exists())

    def goal(self, **changes):
        return dict(dict(id='new',mode='Earn saved Super Wheelspins',phase='farm',limit=1000,
                         rewards=0,bought=0,last_sp=12,farm_runs=0,active_seconds=0),**changes)

    def test_fresh_target_excludes_old_reward_counts_and_models_full_refills(self):
        data=forecast(self.goal(),{},dict(prior_cycles=[54,56],prior_farm_seconds=[1020],prior_farm_yields=[370]),[])
        self.assertEqual(data['remaining'],1000)
        self.assertEqual(data['farms_remaining'],64)
        self.assertEqual(data['sp_required'],21000)
        self.assertEqual(data['credits_required'],95000000)
        self.assertTrue(data['prior_cycle_estimate'])
        self.assertEqual(data['eta_seconds'],1000*55+64*1020)
        self.assertEqual(forecast(self.goal(last_sp=999),{},dict(farm_yields=[370]),[])['farms_remaining'],61)

    def test_funded_tail_and_completed_target_do_not_add_farming(self):
        g=self.goal(limit=10,last_sp=210,bought=1,batch={'id':'batch'})
        data=forecast(g,{'id':'batch','limit':10,'rewards':0},{},[55])
        self.assertEqual(data['farms_remaining'],0)
        self.assertEqual(data['credits_required'],9*95000)
        done=forecast(self.goal(rewards=1000),{},{},[])
        self.assertEqual((done['eta_seconds'],done['eta_upper_seconds']),(0,0))

    def test_starting_balance_forecast_spends_available_points_before_refill(self):
        goal = self.goal(limit=41, last_sp=863, phase='inspect_sp',
                         account_baseline={'goal_id':'new','fields':{'sp':863}})
        data = forecast(goal, {}, {}, [55])
        self.assertEqual(data['farms_remaining'], 0)
        self.assertEqual(data['eta_seconds'], 41*55)
        goal['phase'] = 'farm'
        self.assertEqual(forecast(goal, {}, {}, [55])['farms_remaining'], 0)
        goal['phase'] = 'inspect_sp'
        goal['farm_runs'] = 1
        self.assertEqual(forecast(goal, {}, {}, [55])['farms_remaining'], 0)

    def test_farm_and_refill_records_deduplicate_and_exclude_capped_yield(self):
        with tempfile.TemporaryDirectory() as folder:
            clock=[0]
            t=Tracker(folder,clock=lambda:clock[0]);t.event('progress',self.goal())
            t.event('activity',True);t.event('stage','farm_prepare')
            for i,(before,after) in enumerate([(12,379),(379,751),(751,999)]):
                t.event('farm_started',{'id':str(i),'before_sp':before})
                t.event('stage','farm_drive');clock[0]+=1000
                row=dict(id=str(i),before_sp=before,after_sp=after,launch_attempts=1)
                t.event('farm_completed',row);t.event('farm_completed',row)
                t.event('progress',self.goal(last_sp=after,farm_runs=i+1))
            self.assertEqual(t.data['farm_yields'],[367,372])
            self.assertEqual(t.data['farm_seconds'],[1000,1000,1000])
            self.assertEqual(t.data['refills'][0]['run_count'],3)
            self.assertEqual(t.data['refills'][0]['active_seconds'],3000)
            self.assertEqual(t.data['refills'][0]['launch_count'],3)
            self.assertEqual(len((Path(folder)/'analytics_farms.jsonl').read_text().splitlines()),3)
            self.assertFalse((Path(folder)/'analytics_exports').exists())
            output=export_csv(folder)
            self.assertTrue((output/'farms.csv').exists())

    def test_car_step_timing_includes_failed_attempt_without_counting_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            clock=[0];t=Tracker(folder,clock=lambda:clock[0]);t.event('progress',self.goal())
            t.event('activity',True)
            context=dict(batch_id='batch',cycle=1,goal_id='new')
            t.event('cycle_stage',dict(context,phase='buy'));clock[0]=2
            t.event('activity',False);clock[0]=1000;t.event('activity',True)
            t.event('cycle_stage',dict(context,phase='buy'));clock[0]=1005
            t.event('cycle_stage',dict(context,phase='mastery'));clock[0]=1013
            t.event('cycle_stage',dict(context,phase='return'));clock[0]=1023
            t.event('cycle_complete',dict(context,elapsed_seconds=25))
            row=t.data['cycles'][0]
            self.assertEqual(row['steps'],{'buy':7,'mastery':8,'return':10})
            self.assertEqual(row['failed_attempts'],1)
            self.assertEqual(row['input_stage_seconds'],25)
            data=forecast(self.goal(),{},t.data,[25])
            self.assertIn('batch / 1',panel_data(data)['analytics_cars'])

    def test_reopening_tracker_does_not_count_offline_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            clock=[0];t=Tracker(folder,clock=lambda:clock[0]);t.event('progress',self.goal())
            t.event('activity',True);t.event('stage','farm_drive')
            t.event('farm_started',{'id':'one'});clock[0]=100;t.event('activity',False)
            clock[0]=10000;t=Tracker(folder,clock=lambda:clock[0])
            t.event('activity',True);t.event('stage','farm_drive');clock[0]+=100
            t.event('farm_completed',dict(id='one',before_sp=12,after_sp=379))
            self.assertEqual(t.data['farm_seconds'],[])
            self.assertEqual(t.data['farms'][0]['active_seconds'],200)
            self.assertTrue(t.data['farms'][0]['partial_timing'])

    def test_startup_and_sync_waits_are_measured_without_counting_user_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            clock=[0];t=Tracker(folder,clock=lambda:clock[0])
            t.event('stage','game_start');clock[0]=100
            t.event('stage','cloud_sync');clock[0]=150
            t.event('activity',False);clock[0]=1000;t.event('done',None)
            self.assertEqual(t.data['seconds'],{'recovery':100,'sync':50})

    def test_cycle_keeps_new_transition_diagnostic_separate_from_legacy_attribution(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = [0.]
            tracker = Tracker(folder, clock=lambda: clock[0])
            tracker.event('progress', self.goal())
            tracker.event('activity', True)
            context = dict(batch_id='batch', cycle=1, goal_id='new')
            tracker.event('cycle_stage', dict(context, phase='choose'))
            diagnostic = dict(version=2, observed_usable_seconds=18.,
                              polling_work_within_usable_seconds=12.,
                              programmed_pacing_within_usable_seconds=5.,
                              unassigned_within_usable_seconds=1.,
                              usable_count=1, causal_game_seconds=None)
            clock[0] = 20.
            tracker.event('cycle_complete', dict(context, elapsed_seconds=20.,
                          automation_decision_seconds=12., ui_wait_estimate_seconds=1.,
                          transition_timing=diagnostic))
            first = tracker.data['cycles'][0]
            self.assertEqual(first['transition_timing'], diagnostic)
            self.assertEqual(first['attribution']['waiting_loading_estimate'], 1.)
            self.assertEqual(first['forza_tax_percent_estimated'], 5.)
            self.assertEqual(first['attribution']['unattributed'], 7.)
            diagnostic['observed_usable_seconds'] = 999.
            self.assertEqual(first['transition_timing']['observed_usable_seconds'], 18.)

            context['cycle'] = 2
            tracker.event('cycle_stage', dict(context, phase='choose'))
            clock[0] = 40.
            tracker.event('cycle_complete', dict(context, elapsed_seconds=20.,
                          automation_decision_seconds=12., ui_wait_estimate_seconds=1.))
            stored = json.loads((Path(folder)/'analytics.json').read_text(encoding='utf-8'))['cycles']
            self.assertEqual(stored[0]['transition_timing']['observed_usable_seconds'], 18.)
            self.assertNotIn('transition_timing', stored[1])
            self.assertEqual(stored[0]['attribution'], stored[1]['attribution'])


if __name__=='__main__':unittest.main()
