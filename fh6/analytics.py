"""Local mission measurements and display-only forecasts; never authorize spending."""
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

import forza_cycle as core
from .batching import funded_cars, starting_balance_allowed
from .target import totals
from .recovery_evidence import valid_farm_active
from .operations_metrics import summarize, percentiles, failure_cause, fmt

ROOT = core.BASE/'runs'


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


class Tracker:
    def __init__(self, root=ROOT, clock=time.monotonic):
        self.root, self.clock = Path(root), clock
        self.data = read(self.root/'analytics.json')
        self.data.setdefault('legacy_retry_count',self.data.get('retries',0))
        if self.data.get('open_farm'):
            self.data['open_farm']['timing_interrupted'] = True
        self.last = clock()
        self.category = 'idle'
        self.stage = None
        self.active = False
        self.span = None
        if isinstance(self.data.get('open_system_window'),dict):
            self.data['open_system_window']['interrupted']=True
        self.open_boundaries={}
        # Removal events are journaled before the large aggregate is saved.
        # Restore the exact counter after a crash or fast shutdown.
        cleanup_log = self.root/'analytics_garage_cleanup.jsonl'
        if cleanup_log.exists():
            try:
                with cleanup_log.open('rb') as stream:
                    stream.seek(0, 2)
                    end = stream.tell()
                    stream.seek(max(0, end-8192))
                    rows = stream.read().decode('utf-8', errors='ignore').splitlines()
                latest = json.loads(rows[-1]) if rows else {}
                recorded = latest.get('removed_total')
                if type(recorded) is int:
                    cleanup = self.data.setdefault('garage_cleanup', {})
                    cleanup['removed'] = max(cleanup.get('removed', 0), recorded)
            except (OSError, ValueError, TypeError):
                pass

    def append(self, name, row):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root/name).open('a', encoding='utf-8') as file:
            file.write(json.dumps(row)+'\n')

    def close_span(self, success):
        if self.span:
            row = {k:v for k,v in self.span.items() if k != 'clock'}
            row.update(seconds=max(0,self.last-self.span['clock']), success=success,
                       ended_at=datetime.now().isoformat(timespec='seconds'))
            self.append('analytics_steps.jsonl', row)
            key = row['batch_id']+':'+str(row['cycle'])
            cycle = self.data.setdefault('cycle_work', {}).setdefault(key, {'steps':{}, 'failed_attempts':0})
            cycle['steps'][row['phase']] = cycle['steps'].get(row['phase'],0)+row['seconds']
            if not success:
                cycle['failed_attempts'] += 1
            self.span = None

    def event(self, kind, value, event_time=None):
        if kind not in {'progress', 'stage', 'activity', 'status', 'done',
                        'cycle_stage', 'cycle_complete', 'farm_started', 'farm_completed','farm_skipped','farm_active','failure','refill_ready',
                        'boundary_started','boundary_completed',
                        'garage_cleanup_started','garage_removed','garage_duplicates_disabled','garage_cleanup_completed'}:
            return
        now = self.clock() if event_time is None else event_time
        seconds = self.data.setdefault('seconds', {})
        if self.category != 'idle':
            seconds[self.category] = seconds.get(self.category, 0)+max(0, now-self.last)
        self.last = now
        detail = None
        if kind=='boundary_started':
            if isinstance(value,dict) and isinstance(value.get('id'),str) and isinstance(value.get('name'),str):
                self.open_boundaries[value['id']]=dict(value,clock=now,started_at=datetime.now().isoformat(timespec='seconds'))
        elif kind=='boundary_completed':
            opened=self.open_boundaries.pop(value.get('id'),None) if isinstance(value,dict) else None
            if opened:
                row={k:v for k,v in opened.items() if k!='clock'}
                row.update(seconds=max(0,now-opened['clock']),success=value.get('success') is True,
                           ended_at=datetime.now().isoformat(timespec='seconds'))
                self.append('analytics_boundaries.jsonl',row)
                self.data.setdefault('boundaries',[]).append(row)
                self.data['boundaries']=self.data['boundaries'][-1000:]
        elif kind == 'garage_cleanup_started':
            cleanup = self.data.setdefault('garage_cleanup', {})
            was_active = cleanup.get('active') is True
            active_filter = ('S1 + Drift Cars' if cleanup.get('duplicates_disabled') else
                             (value or {}).get('filter', 'S1 + Drift Cars + Duplicates'))
            cleanup.update(active=True,
                           filter=active_filter,
                           removed=cleanup.get('removed', 0), error=None, verified_empty=False)
            if not was_active:
                cleanup['started_at'] = ((value or {}).get('started_at') or
                                         datetime.now().isoformat(timespec='seconds'))
                cleanup['session_start_removed'] = cleanup['removed']
            detail = {'garage_cleanup': 'started', 'removed': cleanup['removed']}
        elif kind == 'garage_removed':
            cleanup = self.data.setdefault('garage_cleanup', {})
            amount = value.get('count', 1) if isinstance(value, dict) else 1
            amount = amount if type(amount) is int and amount > 0 else 1
            cleanup['removed'] = cleanup.get('removed', 0) + amount
            cleanup.update(active=True, last_removed_at=datetime.now().isoformat(timespec='seconds'))
            recent = cleanup.setdefault('recent_removed_at', [])
            recent.append(cleanup['last_removed_at'])
            cleanup['recent_removed_at'] = recent[-40:]
            detail = {'garage_cleanup': 'removed', 'removed': cleanup['removed'], 'count': amount}
            self.append('analytics_garage_cleanup.jsonl',
                        {'at': cleanup['last_removed_at'], 'goal_id': self.data.get('goal_id'),
                         'count': amount, 'removed_total': cleanup['removed']})
        elif kind == 'garage_duplicates_disabled':
            cleanup = self.data.setdefault('garage_cleanup', {})
            cleanup.update(active=True, duplicates_disabled=True,
                           filter='S1 + Drift Cars')
            detail = {'garage_cleanup': 'duplicates_disabled',
                      'removed': cleanup.get('removed', 0)}
        elif kind == 'garage_cleanup_completed':
            cleanup = self.data.setdefault('garage_cleanup', {})
            cleanup.update(active=False, ended_at=datetime.now().isoformat(timespec='seconds'),
                           error=(value or {}).get('error') if isinstance(value, dict) else None,
                           verified_empty=bool((value or {}).get('verified_empty')) if isinstance(value, dict) else False)
            if cleanup['verified_empty']:
                cleanup['bought_at_verified_empty'] = (self.data.get('progress') or {}).get('bought', 0)
                cleanup['removed_at_verified_empty'] = cleanup.get('removed', 0)
            try:
                cleanup['elapsed_seconds'] = max(0, (datetime.now()-datetime.fromisoformat(cleanup['started_at'])).total_seconds())
            except (KeyError, TypeError, ValueError):
                cleanup['elapsed_seconds'] = None
            detail = {'garage_cleanup': 'completed', 'removed': cleanup.get('removed', 0),
                      'error': cleanup.get('error')}
        elif kind=='failure':
            self.finish_failure()
            context={k:v for k,v in (self.span or {}).items() if k in ('batch_id','cycle','goal_id')}
            self.data['open_failure']=dict(context,stage=value.get('stage'),cause=failure_cause(value['message'],value.get('stage','')),
                started_at=datetime.now().isoformat(),message=value['message'],seconds_start=sum(seconds.values()))
            if self.span:
                key=self.span['batch_id']+':'+str(self.span['cycle'])
                work=self.data.setdefault('cycle_work',{}).setdefault(key,{'steps':{},'failed_attempts':0})
                work['recovery_events']=work.get('recovery_events',0)+1
        elif kind == 'cycle_stage':
            failure=self.data.get('open_failure')
            if failure and value.get('phase')!=failure.get('stage'):
                self.finish_failure()
            self.close_span(True)
            self.span = dict(value, clock=now, started_at=datetime.now().isoformat(timespec='seconds'))
        elif kind == 'cycle_complete':
            self.finish_failure()
            self.close_span(True)
            key = value['batch_id']+':'+str(value['cycle'])
            cycle = self.data.setdefault('cycle_work', {}).pop(key, {'steps':{}, 'failed_attempts':0})
            row = dict(value, **cycle, ended_at=datetime.now().isoformat(timespec='seconds'))
            if isinstance(row.get('transition_timing'), dict):
                # Preserve only the diagnostic supplied by this live event.
                # Do not reconstruct versioned latency for historical cycles
                # or mix its overlapping polling interval into attribution.
                row['transition_timing'] = dict(row['transition_timing'])
            row['recovery_tracking_version']=2
            recovery=sum(r.get('recovery_seconds',0) for r in self.data.get('failures',[])
                         if r.get('batch_id')==row['batch_id'] and r.get('cycle')==row['cycle'])
            elapsed=row.get('elapsed_seconds',0) or 0
            recovery=min(elapsed,recovery)
            decision=min(max(0,elapsed-recovery),row.get('automation_decision_seconds',0))
            ui_wait=min(max(0,elapsed-recovery-decision),row.get('ui_wait_estimate_seconds',0))
            row['attribution']=dict(recovery=recovery,automation_decision=decision,
                                    waiting_loading_estimate=ui_wait,
                                    unattributed=max(0,elapsed-recovery-decision-ui_wait),mandatory_ui=None)
            row['forza_tax_percent_estimated']=100*ui_wait/elapsed if elapsed>0 else None
            row['input_stage_seconds'] = sum(cycle['steps'].values())
            self.append('analytics_cycles.jsonl', row)
            self.data.setdefault('cycles', []).append(row)
            self.data['cycles'] = self.data['cycles'][-1000:]
        elif kind == 'farm_started':
            if (self.data.get('open_farm') or {}).get('id') != value['id']:
                self.data['open_farm'] = dict(value, started_at=datetime.now().isoformat(timespec='seconds'),
                    seconds_start=seconds.get('farming',0))
            if not self.data.get('open_refill'):
                self.data['open_refill'] = dict(started_at=datetime.now().isoformat(timespec='seconds'),
                    farms=[], seconds_start=sum(seconds.values()))
        elif kind == 'farm_active':
            failure = self.data.get('open_failure')
            if (valid_farm_active(value) and self.stage == 'farm_drive' and
                    (self.data.get('open_farm') or {}).get('id') == value['id'] and
                    failure and not failure.get('batch_id') and failure.get('cycle') is None):
                # A successful countdown proves productive farming resumed.
                # Stage/launch intents do not. Preserve every historical row.
                failure['recovery_end_evidence'] = dict(value)
                failure['recovery_end_version'] = 1
                self.finish_failure()
        elif kind == 'farm_skipped':
            if (self.data.get('open_farm') or {}).get('id')==value['id']:
                self.data['open_farm']=None
                # A balance recheck is not a completed farm. Keep any actual
                # earlier farms in the refill, including their time and gain.
                if not (self.data.get('open_refill') or {}).get('farms'):
                    self.data['open_refill']=None
            detail={'farm_skipped':dict(value)}
        elif kind == 'farm_completed':
            self.finish_failure()
            recorded = self.data.setdefault('completed_farm_ids', [])
            if value['id'] not in recorded:
                opened = self.data.get('open_farm') or {}
                row = dict(value, active_seconds=max(0,seconds.get('farming',0)-opened.get('seconds_start',seconds.get('farming',0))),
                    started_at=opened.get('started_at'), ended_at=datetime.now().isoformat(timespec='seconds'))
                row['gained_sp'] = max(0, row['after_sp']-row['before_sp']) if isinstance(row['before_sp'],int) else 0
                row['capped'] = row['after_sp'] == 999
                row['partial_timing'] = bool(opened.get('timing_interrupted')) or opened.get('id') != value['id'] or not isinstance(row['before_sp'],int)
                row['run_type']=('intentional_top_up' if row.get('exit_reason')=='intentional_target_top_up' else
                                 'interrupted' if row['partial_timing'] else 'natural_completion')
                recorded.append(value['id'])
                self.append('analytics_farms.jsonl', row)
                self.data.setdefault('farms', []).append(row)
                if not row['partial_timing'] and row['active_seconds'] >= 60 and row['run_type']=='natural_completion':
                    self.data.setdefault('farm_seconds', []).append(row['active_seconds'])
                if not row['capped'] and row['gained_sp'] > 0 and row['run_type']=='natural_completion':
                    self.data.setdefault('farm_yields', []).append(row['gained_sp'])
                refill = self.data.get('open_refill') or dict(started_at=row['started_at'],farms=[],seconds_start=sum(seconds.values()))
                refill['farms'].append(row)
                if row['after_sp'] >= row.get('target_sp',999):
                    refill.update(ended_at=row['ended_at'],run_count=len(refill['farms']),
                        launch_count=sum(r.get('launch_attempts',0) for r in refill['farms']),
                        active_seconds=max(0,sum(seconds.values())-refill.pop('seconds_start')),
                        before_sp=refill['farms'][0]['before_sp'],after_sp=row['after_sp'])
                    self.append('analytics_refills.jsonl', refill)
                    self.data.setdefault('refills', []).append(refill)
                    self.data['open_refill'] = None
                else:
                    self.data['open_refill'] = refill
                self.data['open_farm'] = None
        elif kind=='refill_ready':
            refill=self.data.get('open_refill')
            if refill and refill.get('farms'):
                refill.update(ended_at=datetime.now().isoformat(timespec='seconds'),run_count=len(refill['farms']),
                    launch_count=sum(r.get('launch_attempts',0) for r in refill['farms']),
                    active_seconds=max(0,sum(seconds.values())-refill.pop('seconds_start')),
                    before_sp=refill['farms'][0]['before_sp'],after_sp=value['after_sp'],funded_cars=value['cars'])
                self.append('analytics_refills.jsonl',refill)
                self.data.setdefault('refills',[]).append(refill)
                self.data['open_refill']=None
        elif kind == 'progress':
            if value.get('mode') != 'Earn saved Super Wheelspins':
                return
            identifier = value.get('id')
            if self.data.get('goal_id') != identifier:
                self.data = {'goal_id': identifier, 'seconds': {}, 'farm_seconds': [], 'farm_yields': [],
                             'retries': 0, 'crashes': 0}
            previous = self.data.get('progress', {})
            detail = {k:value.get(k) for k in ('id','phase','limit','rewards','bought','farm_runs','last_sp','sp_observed_at')}
            if detail == previous:
                detail = None
            else:
                self.data['progress'] = detail
                points = self.data.setdefault('progress_points', [])
                point = {'at': datetime.now().isoformat(timespec='seconds'),
                         'earned': value.get('rewards', 0), 'sp': value.get('last_sp'),
                         'sp_at': value.get('sp_observed_at')}
                if not points or any(points[-1].get(k) != point[k] for k in ('earned','sp','sp_at')):
                    points.append(point)
                    self.data['progress_points'] = points[-10000:]
        elif kind == 'stage':
            self.stage = value
            detail = {'stage': value}
        elif kind in {'activity', 'done'}:
            self.active = bool(value) if kind == 'activity' else False
            if kind=='activity' and self.active:
                previous=(self.data.get('progress') or {}).get('rewards')
                self.data['open_system_window']=dict(
                    started_at=datetime.now().isoformat(timespec='seconds'),
                    seconds_start=sum(seconds.values()),
                    rewards_start=previous if type(previous) is int and previous>=0 else None,
                    current_rewards=previous if type(previous) is int and previous>=0 else None,
                    active_seconds=0,interrupted=False)
            elif not self.active and isinstance(self.data.get('open_system_window'),dict):
                window=self.data['open_system_window']
                window['active_seconds']=max(0,sum(seconds.values())-window.get('seconds_start',sum(seconds.values())))
                window['ended_at']=datetime.now().isoformat(timespec='seconds')
                self.data.setdefault('system_windows',[]).append(window)
                self.data['system_windows']=self.data['system_windows'][-100:]
                self.data['open_system_window']=None
            if not self.active:
                self.close_span(False)
        elif kind == 'status':
            if value.startswith('Retrying saved step'):
                self.data['retries'] = self.data.get('retries', 0)+1
                self.category = 'recovery'
                detail = {'retry': self.data['retries']}
            elif value.startswith('Game crashed'):
                self.data['crashes'] = self.data.get('crashes', 0)+1
                self.category = 'recovery'
                detail = {'crash': self.data['crashes']}
        if kind == 'stage' and value in {'game_start', 'game_restart', 'cloud_sync'}:
            self.category = 'sync' if value == 'cloud_sync' else 'recovery'
        elif kind != 'status':
            self.category = ('sync' if self.stage == 'cloud_sync' else
                'farming' if str(self.stage).startswith('farm') else 'conversion') if self.active else 'idle'
        window=self.data.get('open_system_window')
        if isinstance(window,dict):
            window['active_seconds']=max(0,sum(seconds.values())-window.get('seconds_start',sum(seconds.values())))
            rewards=(self.data.get('progress') or {}).get('rewards')
            if type(rewards) is int and rewards>=0:window['current_rewards']=rewards
        self.data['updated_at'] = datetime.now().isoformat(timespec='seconds')
        # The append-only cleanup journal above is the durable per-car record.
        # Checkpoint the multi-megabyte aggregate every ten cars so reporting
        # cannot stall the destructive UI loop.
        checkpoint = not (kind == 'garage_removed' and
                          self.data.get('garage_cleanup', {}).get('removed', 0) % 10)
        if checkpoint:
            save(self.root/'analytics.json', self.data)
        if detail:
            with (self.root/'analytics_events.jsonl').open('a', encoding='utf-8') as file:
                file.write(json.dumps({'at': self.data['updated_at'], 'goal_id': self.data.get('goal_id'), **detail})+'\n')

    def finish_failure(self):
        row=self.data.pop('open_failure',None)
        if row:
            row['recovery_wall_seconds']=max(0,(datetime.now()-datetime.fromisoformat(row['started_at'])).total_seconds())
            row['recovery_seconds']=max(0,sum(self.data.get('seconds',{}).values())-row.pop('seconds_start',0))
            row['ended_at']=datetime.now().isoformat()
            self.data.setdefault('failures',[]).append(row)
            self.append('analytics_failures.jsonl',row)


def forecast_farm_samples(goal, samples):
    """Paired full-run observations from the current explicit farm regime."""
    from .operations_metrics import _mission_farm_rows, _actual_farm_balance, numeric
    rows = _mission_farm_rows(goal, samples)
    explicit = [(i, r['share_code']) for i, r in enumerate(rows)
                if isinstance(r.get('share_code'), str) and len(r['share_code']) == 9
                and r['share_code'].isascii() and r['share_code'].isdigit()]
    if explicit:
        code = explicit[-1][1]
        start = max((i + 1 for i, c in explicit if c != code), default=0)
        eligible = [r for r in rows[start:] if r.get('share_code') == code
                    and r.get('phase') in (None, 'complete')
                    and not r.get('partial_timing') and _actual_farm_balance(r)
                    and r.get('capped') is False and r['after_sp'] < 999
                    and r.get('exit_reason') == 'natural_completion'
                    and r['gained_sp'] > 0 and numeric(r.get('active_seconds'))
                    and r['active_seconds'] > 0][-20:]
        return ([r['active_seconds'] for r in eligible], [r['gained_sp'] for r in eligible],
                code, 'current profile; latest 20 complete uncapped full runs' if eligible
                else 'no eligible current-profile full runs; planning defaults')
    # Old records lack challenge identity. Keep them explicitly labeled and do
    # not fall back to them once an explicit current profile is known.
    times = [x for x in samples.get('farm_seconds', []) if numeric(x) and 0 < x]
    yields = [x for x in samples.get('farm_yields', []) if numeric(x) and 0 < x <= 999]
    times = times or [x for x in samples.get('prior_farm_seconds', []) if numeric(x) and x > 0]
    yields = yields or [x for x in samples.get('prior_farm_yields', []) if numeric(x) and 0 < x <= 999]
    return times, yields, None, 'legacy samples without profile identity' if times or yields else 'planning defaults'


def forecast(goal, cars, samples, cycles, now=None):
    now = now or datetime.now()
    remaining = max(0, goal.get('limit', 0)-goal.get('rewards', 0))
    from .operations_metrics import numeric
    current_cycles = [x for x in cycles if numeric(x) and x > 0]
    cycle_values = current_cycles or [x for x in samples.get('prior_cycles', []) if numeric(x) and x > 0]
    farm_values, yields, farm_code, farm_basis = forecast_farm_samples(goal, samples)
    cycle = median(cycle_values) if cycle_values else 60
    farm = median(farm_values) if farm_values else 18*60
    gain = median(yields) if yields else 350
    points = max(0, min(999, goal.get('last_sp') or 0))
    left, farms = remaining, 0
    batch = goal.get('batch') or {}
    if batch.get('id') == cars.get('id') and batch:
        funded = min(left, max(0, cars.get('limit',0)-cars.get('rewards',0)))
        points = max(0, points-funded*21)
        left -= funded
    elif goal.get('phase') != 'farm' and starting_balance_allowed(goal):
        funded = funded_cars(points, left, goal.get('reserve_sp', 0), allow_partial=True)
        points -= funded*21
        left -= funded
    while left:
        count = min(left, 47)
        target = min(999, count*21+goal.get('reserve_sp',0))
        runs = max(0, math.ceil((target-points)/gain))
        farms += runs
        points = min(999, points+runs*gain)
        points -= count*21
        left -= count
    modeled = remaining*cycle+farms*farm
    # Include historical retries and transition delays in the upper estimate.
    earned = goal.get('rewards', 0)
    observed = remaining*goal.get('active_seconds', 0)/earned if earned else 0
    upper = max(modeled*1.25, observed) if remaining else 0
    unclaimed = max(0, goal.get('bought',0)-earned)
    return dict(**totals(goal), cycle_target_seconds=goal.get('cycle_target_seconds',55),
                remaining=remaining, earned=goal.get('rewards',0), target=goal.get('limit',0),
                bought=goal.get('bought',0), last_sp=goal.get('last_sp'), account_baseline=goal.get('account_baseline',{}),
                active_seconds=goal.get('active_seconds',0), farm_runs=goal.get('farm_runs',0),
                cycle_seconds=cycle, cycle_samples=len(cycle_values),
                farm_seconds=farm, farm_samples=len(farm_values), sp_per_farm=gain,
                forecast_farm_share_code=farm_code, forecast_farm_basis=farm_basis,
                yield_samples=len(yields), farms_remaining=farms, sp_required=remaining*21,
                credits_required=max(0,remaining-unclaimed)*95000,
                eta_seconds=modeled, eta_upper_seconds=upper,
                finish_earliest=(now+timedelta(seconds=modeled)).strftime('%b %d %H:%M'),
                finish_latest=(now+timedelta(seconds=upper)).strftime('%b %d %H:%M'),
                spins_per_hour=earned*3600/goal.get('active_seconds',1) if goal.get('active_seconds',0)>0 else None,
                retries=samples.get('retries',0), crashes=samples.get('crashes',0),
                refill_count=len(samples.get('refills',[])),
                average_runs_per_refill=(sum(r['run_count'] for r in samples['refills'])/len(samples['refills'])) if samples.get('refills') else None,
                average_refill_seconds=(sum(r['active_seconds'] for r in samples['refills'])/len(samples['refills'])) if samples.get('refills') else None,
                recent_cycles=samples.get('cycles',[]),
                recent_farms=samples.get('farms',[]),
                recent_refills=samples.get('refills',[]),
                prior_cycle_estimate=not bool(current_cycles),
                prior_farm_estimate=not bool(farm_values) or farm_code is None,
                measured_seconds=samples.get('seconds', {}),
                assumptions='Use available starting SP first, then 987 SP for 47 cars plus reserve; final batch fits remaining goal. Conservative full-run timing until shortened top-ups are measured. Median observed timing; pauses, recovery and yield changes can extend this range.')


def current(root=ROOT, goal=None):
    root = Path(root)
    goal = goal if goal is not None else read(root/'goal.json')
    cars = read(root/'session.json')
    records = {cars.get('id'): cars}
    for path in (root/'history').glob('*.json'):
        record = read(path)
        if (record.get('funding') or {}).get('goal_id') == goal.get('id'):
            records[record.get('id')] = record
    cycles = []
    for record in sorted(records.values(), key=lambda d:d.get('id','')):
        if (record.get('funding') or {}).get('goal_id') == goal.get('id'):
            cycles.extend(record.get('cycle_seconds', []))
    data = read(root/'analytics.json')
    if data.get('goal_id') != goal.get('id'):
        data = {}
    result = forecast(goal, cars, data, cycles[-40:])
    performance = read(root/'performance.json')
    result['performance'] = performance if performance.get('goal_id') == goal.get('id') else {}
    result['operations']=summarize(goal,dict(data,transitions=result['performance'].get('transitions',[])))
    result['garage_cleanup'] = data.get('garage_cleanup', {})
    review = read(root/'optimization_review.json')
    result['optimization_review'] = review if goal.get('id') and review.get('goal_id') == goal['id'] else {}
    return result


def display(data):
    rate = data['spins_per_hour']
    base = ('EXPECTED TIME  %.1f–%.1f hours\nFINISH WINDOW  %s – %s (local)\n\n'
        'CAR CYCLE      %.1f seconds median (%d samples)\nFARM RUN       %.1f minutes median (%d samples)\n'
        'FARM YIELD     %.0f SP per uncapped run (%d samples)\n\n'
        'STILL NEEDED   %d spins / %s SP\nFARM RUNS      about %d\nCAR PURCHASES  %s CR required\n'
        'OBSERVED PACE  %s spins/hour of active farming and car work\n\n'
        'SINCE TRACKING %d retries / %d crashes\n\n%s') % (
        data['eta_seconds']/3600, data['eta_upper_seconds']/3600, data['finish_earliest'],data['finish_latest'],
        data['cycle_seconds'],data['cycle_samples'],data['farm_seconds']/60,data['farm_samples'],
        data['sp_per_farm'],data['yield_samples'],data['remaining'],f"{data['sp_required']:,}",
        data['farms_remaining'],f"{data['credits_required']:,}",f'{rate:.1f}' if rate is not None else '—',
        data['retries'],data['crashes'],data['assumptions'])
    refills = ('No completed refills in this run yet.' if data['average_runs_per_refill'] is None else
        f"BATCH SP REFILLS  {data['average_runs_per_refill']:.2f} runs / {data['average_refill_seconds']/60:.1f} min average ({data['refill_count']} refills)")
    stages = {}
    for cycle in data['recent_cycles']:
        for stage, seconds in cycle.get('steps',{}).items():
            stages.setdefault(stage,[]).append(seconds)
    detail = '\n'.join(f'{stage.upper():14} {sum(values)/len(values):.2f} sec average' for stage,values in stages.items())
    prior = 'Initial estimates use prior verified timings until this fresh run has samples.' if data['prior_cycle_estimate'] or data['prior_farm_estimate'] else 'Estimates use measurements from this run.'
    return base+'\n\n'+refills+'\n\nSTEP TIMINGS (completed cars in this run)\n'+(detail or 'Waiting for the first completed car.')+'\n\n'+prior+'\nMeasurements stay in the app; CSV export is available on the Analytics page.'


def export_csv(root=ROOT):
    import csv
    root = Path(root)
    output = root/'analytics_exports'/datetime.now().strftime('%Y%m%d_%H%M%S')
    output.mkdir(parents=True, exist_ok=True)
    for category in ('events','steps','cycles','farms','refills','failures','garage_cleanup'):
        source = root/f'analytics_{category}.jsonl'
        if not source.exists():
            continue
        rows = []
        for line in source.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            steps = row.pop('steps', {})
            row.update({f'step_{k}_seconds':v for k,v in steps.items()})
            rows.append({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
        if rows:
            with (output/f'{category}.csv').open('w',encoding='utf-8-sig',newline='') as file:
                writer = csv.DictWriter(file, fieldnames=sorted(set().union(*(row.keys() for row in rows))))
                writer.writeheader()
                writer.writerows(rows)
    rows=read(root/'performance.json').get('transitions',[])
    if rows:
        with (output/'transitions.csv').open('w',encoding='utf-8-sig',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=sorted(set().union(*(r.keys() for r in rows))))
            writer.writeheader();writer.writerows(rows)
    return output


def optimization_rows(review, now=None):
    """Compact native-panel rows; old evidence is labeled, not shown as live."""
    now = now or datetime.now().astimezone()
    if not isinstance(review, dict) or not review:
        return [['CONTINUOUS REVIEW', 'Waiting', 'No matching mission review available']], 'Review: waiting for current mission evidence.'
    def age(value):
        try:
            observed = datetime.fromisoformat(value)
            if observed.tzinfo is None:
                observed = observed.astimezone()
            return (now - observed).total_seconds()
        except (TypeError, ValueError):
            return None
    elapsed, source_age = age(review.get('reviewed_at')), age(review.get('source_updated_at'))
    if elapsed is None or source_age is None or min(elapsed, source_age) < 0 or max(elapsed, source_age) > 120:
        label = f'Last review {elapsed:.0f}s ago' if elapsed is not None and elapsed >= 0 else 'Review timestamp unavailable'
        return [['CONTINUOUS REVIEW', 'Unavailable / stale', label]], f'Review unavailable: {label.lower()}.'
    latest, previous = review.get('latest') or {}, review.get('previous') or {}
    comparison = review.get('comparison') or {}
    rows = [['CONTINUOUS REVIEW', f'{elapsed:.0f}s ago',
             f"{latest.get('cars',0)}/20 latest + {previous.get('cars',0)}/20 previous full cars; all outliers retained"]]
    if comparison.get('available'):
        newer, older = latest.get('cycle_seconds') or {}, previous.get('cycle_seconds') or {}
        rows.append(['CAR TREND P50 / P90', f"{fmt(newer.get('p50'))} / {fmt(newer.get('p90'))} s",
                     f"Previous {fmt(older.get('p50'))} / {fmt(older.get('p90'))} s; disjoint 20-car cohorts"])
        flags = comparison.get('regressions') or []
        rows.append(['REGRESSION FLAGS', len(flags), 'P50/P90 increases of at least 10%; investigate, not automatic tuning'])
    farm = review.get('farm_review') or {}
    if farm.get('status') == 'observing':
        overall = farm.get('overall_trial') or {}
        short, longer = farm.get('last3_uncapped_complete') or {}, farm.get('last10_uncapped_complete') or {}
        rows.extend([
            ['MINI TRIAL / MEGA', f"{fmt(overall.get('retained_sp_hour'))} / {fmt(farm.get('frozen_mega_sp_hour'))} SP/h",
             f"{fmt(farm.get('overall_gain_vs_frozen_mega_percent'))}% provisional; {overall.get('runs',0)} runs, all wall costs"],
            ['MINI LAST 3 / 10', f"{fmt(short.get('retained_sp_hour'))} / {fmt(longer.get('retained_sp_hour'))} SP/h",
             f"{short.get('runs',0)} / {longer.get('runs',0)} uncapped complete runs; diagnostic subsets"],
            ['MINI NON-DRIVE WALL P50', fmt((short.get('non_drive_wall_seconds') or {}).get('p50'),' s'),
             f"{short.get('drive_timing_coverage',0)}/{short.get('runs',0)} runs; includes menus, loading, recovery and pauses"]])
        trend = farm.get('comparison') or {}
        if trend.get('available'):
            rows.append(['MINI RECENT TREND', fmt(trend.get('retained_sp_hour_change_percent'),'%'),
                         'Latest 3 vs previous 3 uncapped runs; provisional, existing trial controls decide'])
    return rows, f'Continuous review {elapsed:.0f}s ago; observed trends, no automatic retuning.'


def panel_data(data):
    """Simple numeric tables for the native Windows panel, no filesystem export."""
    cycles = data['recent_cycles']
    table_cycles = []
    stages = {}
    for row in cycles:
        steps = row.get('steps',{})
        table_cycles.append([f"{row['batch_id'][-6:]} / {row['cycle']}",
            f"{row.get('elapsed_seconds') or row.get('input_stage_seconds',0):.1f}",
            *(f"{steps.get(k,0):.1f}" for k in ('buy','choose','mastery','return')),row.get('failed_attempts',0)])
        for phase,value in steps.items():
            stages.setdefault(phase,[]).append(value)
    tables = {
        'overview':[
            ['Total goal',f"{data.get('total_progress',data['earned'])} / {data.get('total_target',data['target'])}",'Starting inventory plus verified new reward nodes'],
            ['Starting spins counted',data.get('starting_spins',0),'User-approved starting inventory; not new earnings'],
            ['Car median target',f"{data.get('cycle_target_seconds',55)} seconds",'Consecutive completed cycles, including interruptions'],
            ['Saved spins',f"{data['earned']} / {data['target']}",'New owned Super Wheelspin nodes'],
            ['Cars bought',data['bought'],'Purchased cars remain in your garage'],
            ['Observed SP',data['last_sp'] if data['last_sp'] is not None else 'Reading','Last verified in-game balance'],
            ['Active time',f"{data['active_seconds']/3600:.2f} h",'Excludes stopped/offline time'],
            ['Observed pace',f"{data['spins_per_hour']:.1f} / h" if data['spins_per_hour'] else 'Measuring','Active farming and car work'],
            ['Farm runs',data['farm_runs'],'Completed challenges this mission'],
            ['SP gained',sum(r['gained_sp'] for r in data['recent_farms']),'Verified retained gain; capped at 999'],
            ['Batch SP refills',data['refill_count'],'Completed refill groups; targets may vary'],
            *[[k.title()+' time',f'{v/60:.1f} min','Measured active time'] for k,v in data['measured_seconds'].items()]
        ],
        'cars':table_cycles,
        'farms':[[i+1,r.get('before_sp'),r['after_sp'],r['gained_sp'],f"{r['active_seconds']/60:.1f}",r.get('launch_attempts',0),(r.get('run_type','interrupted' if r.get('partial_timing') else 'natural_completion')+(' / CAP' if r['capped'] else ''))] for i,r in enumerate(data['recent_farms'])],
        'refills':[[i+1,r['before_sp'],r['after_sp'],r['run_count'],f"{r['active_seconds']/60:.1f}",r.get('launch_count',0),r['ended_at'][11:19]] for i,r in enumerate(data['recent_refills'])],
        'steps':[[k,fmt(percentiles(v)['p50']),fmt(percentiles(v)['p90']),fmt(percentiles(v)['p99']),len(v),'All recorded','Nearest rank'] for k,v in stages.items()]}
    op=data.get('operations',{})
    if op:
        tables['steps']=[[k,fmt(v['p50']),fmt(v['p90']),fmt(v['p99']),v['n'],'Last 20 cars','Nearest rank'] for k,v in op['stage_percentiles'].items()]
        tables['overview']=[
            ['NEW SW / ACTIVE HOUR',fmt(op['sw_active_hour']),'Verified new nodes / all active mission time'],
            ['NEW SW / WALL HOUR',fmt(op['sw_wall_hour']),'Verified new nodes / elapsed mission time, including stops'],
            ['FARM CAPACITY',fmt(op['farm_capacity'],' cars/h'),'Retained SP/hour divided by 21; complete timing only'],
            ['CONVERSION CAPACITY',fmt(op['conversion_capacity'],' cars/h'),'3600 / mean completed cycle time including recovery'],
            ['BOTTLENECK',op['bottleneck'],'Lower standalone capacity; stages run sequentially'],
            ['LINE IMBALANCE',fmt(op['imbalance_percent'],'%'),'1 - lower capacity / higher capacity'],
            ['COMBINED CAPACITY',fmt(op['combined_capacity'],' cars/h'),'Sequential rate: 1 / (1/farm + 1/conversion)'],
            ['RETAINED SP / FARM H',fmt(op['retained_sp_hour']),f"{op['farm_rate_samples']} fully timed challenges"],
            ['FIRST-PASS YIELD',fmt(op['first_pass_yield'],'%'),f"{op['first_pass_samples']} cars with detailed recovery coverage"],
            ['UNASSIGNED OVERHEAD',fmt(op['forza_tax_percent_estimated'],'%'),'Polling/pacing excluded; actual causal Forza share unmeasured'],
            ['CAP LOSS (ESTIMATE)',fmt(op['cap_loss_sp_estimated'],' SP'),fmt(op['cap_loss_percent_estimated'],'% of estimated raw SP')],
            ['Time attribution','Observed, not causal','Mandatory UI vs animation cannot be identified from screenshots alone'],
        ]+tables['overview']
        tables['failures']=[[k,v['count'],fmt(v['per_100_cars']),fmt(v['recovery_seconds']),fmt(v['cost']['p50']),fmt(v['cost']['p90']),v['cost']['n']] for k,v in op['failures'].items()]
        tables['transitions']=[[k,fmt(v['input_to_change']['p50']),fmt(v['input_to_change']['p90']),fmt(v['change_to_usable']['p50']),fmt(v['change_to_usable']['p90']),fmt(v['input_to_usable']['p99']),v['input_to_usable']['n']] for k,v in op['transition_stages'].items()]
        tables['attribution']=[['unassigned overhead' if k=='waiting_loading_estimate' else k,fmt(v),
                               'Polling/pacing excluded; not causal game time' if k=='waiting_loading_estimate' else
                               'Measured seconds' if k!='unattributed' else 'UI/load/pacing/uninstrumented; cause unknown','','','','']
                              for k,v in op['attribution'].items()]
        tables['attribution'].append(['Mandatory UI','Unknown','Cannot identify a mandatory minimum from screen changes','','','',''])
    baseline = data.get('account_baseline') or {}
    performance = data.get('performance') or {}
    queue = performance.get('account_queue') or {}
    if queue:
        tables['overview'].append(['Background account reading',
            f"{queue.get('processed',0)} processed / {queue.get('pending',0)} queued",
            f"{queue.get('dropped',0)} older frames dropped / {queue.get('errors',0)} read errors"])
    for name,row in sorted(performance.get('operations',{}).items()):
        tables['overview'].append([name,f"{row.get('recent_median_ms',0):.1f} ms median",
            f"{row.get('count',0)} observations / {row.get('seconds',0):.2f} seconds total"])
    for key,value in baseline.get('fields',{}).items():
        tables['overview'].append(['Start '+key.replace('_',' '),value,
                                   'Starting snapshot '+baseline.get('observed_at','')])
    review_rows, review_basis = optimization_rows(data.get('optimization_review'))
    tables['overview'] = review_rows + tables['overview']
    output = {f'analytics_{k}':'~'.join('^'.join(str(c) for c in row) for row in rows) for k,rows in tables.items()}
    refill = 'measuring' if data['average_runs_per_refill'] is None else f"{data['average_runs_per_refill']:.2f} runs / {data['average_refill_seconds']/60:.1f} min"
    output['analytics_header'] = (f"NEW SW/H active {fmt(op.get('sw_active_hour'))} | wall {fmt(op.get('sw_wall_hour'))} | ETA {data['eta_seconds']/3600:.1f}–{data['eta_upper_seconds']/3600:.1f} h\n"
        f"Car {data['cycle_seconds']:.1f}s | Farm {data['farm_seconds']/60:.1f}m / {data['sp_per_farm']:.0f} SP | Batch refill: {refill}\n"
        f"Need {data['sp_required']:,} SP / {data['credits_required']:,} CR / about {data['farms_remaining']} farms\n"
        f"{data.get('total_progress',data['earned'])} / {data.get('total_target',data['target'])} total ({data.get('starting_spins',0)} starting + {data['earned']} new) | {data['bought']} cars bought | {data['retries']} retries / {data['crashes']} crashes")
    output['analytics_basis'] = review_basis + ' P99: sparse below 100 samples. Transition latency includes polling; unassigned overhead excludes it. Actual causal Forza share is unmeasured.'
    return output


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()
    print(export_csv() if args.export else display(current()))
