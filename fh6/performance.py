"""Bounded local measurements of work on the game input thread."""
import time
from collections import deque
from statistics import median
import numpy as np
from .reporting import RUNS, read_json, write_json
from .transitions import TransitionProbe, summarize_transition_timing
from .recovery_evidence import valid_farm_active


class Performance:
    def __init__(self, goal_id, path=RUNS/'performance.json', stream=None):
        self.goal_id, self.path, self.stream = goal_id, path, stream
        self.stage = 'startup'
        self.samples = {}
        old = read_json(path)
        self.totals = old.get('operations', {}) if old.get('goal_id') == goal_id else {}
        self.probe=TransitionProbe()
        self.probe_context={}
        self.decision_seconds=0
        self.pacing_seconds=0
        self.probe.costs=lambda:(self.decision_seconds,self.pacing_seconds)
        self.probe.rows=old.get('transitions',[]) if old.get('goal_id')==goal_id else []
        self.cycle_decision=old.get('cycle_decision',{}) if old.get('goal_id')==goal_id else {}
        self.cycle_key=None
        self.active_farm_id=None
        self.failed_stage=old.get('failed_stage') if old.get('goal_id')==goal_id else None

    def mark_event(self, kind, value):
        """Record only timing-critical state on the game input thread.

        Cycle summaries and persistence are deliberately excluded here.  They
        can scan/copy the retained telemetry after the input that follows this
        marker has already been sent.
        """
        if kind=='stage':
            self.stage = str(value)
            self.probe.stage=str(value)
        elif kind=='cycle_stage':
            if self.failed_stage and value['phase']!=self.failed_stage:
                self.failed_stage=None
            self.cycle_key=value['batch_id']+':'+str(value['cycle'])
            self.probe_context={k:value[k] for k in ('batch_id','cycle')}
            self.probe_context['during_recovery']=bool(self.failed_stage)
            self.probe.context=dict(self.probe_context)
        elif kind=='cycle_complete':
            self.cycle_key=None
            self.probe_context={}
            self.probe.context={}
            self.failed_stage=None
        elif kind=='farm_started':
            self.active_farm_id=value.get('id')
        elif kind=='farm_active':
            if (valid_farm_active(value) and self.active_farm_id==value['id'] and
                    self.stage=='farm_drive' and self.cycle_key is None and self.failed_stage):
                self.record_probe('finish','recovery_ended')
                self.failed_stage=None
                self.probe_context={}
                self.probe.context={}
        elif kind in {'farm_completed','farm_skipped'}:
            if self.active_farm_id==value.get('id'):
                self.active_farm_id=None
        elif kind=='failure':
            self.failed_stage=value.get('stage')
            self.record_probe('finish','failed')
            self.probe_context['during_recovery']=True
            self.probe.context['during_recovery']=True

    def enrich_event(self, kind, value):
        """Build report-only statistics on the ordered diagnostics stream."""
        if kind != 'cycle_complete':
            return
        key=value['batch_id']+':'+str(value['cycle'])
        value['automation_decision_seconds']=self.cycle_decision.pop(key,0)
        rows=[r for r in self.probe.rows
            if r.get('batch_id')==value['batch_id'] and r.get('cycle')==value['cycle'] and not r.get('during_recovery')]
        value['ui_wait_estimate_seconds']=sum(r.get('ui_wait_estimate_seconds') or 0 for r in rows)
        # Separate overlapping latency diagnostics from legacy whole-cycle
        # counters. Polling while the game loads is still observed latency.
        value['transition_timing']=summarize_transition_timing(rows)

    def event(self, kind, value):
        """Synchronous compatibility API used by focused unit tests/tools."""
        self.mark_event(kind, value)
        self.enrich_event(kind, value)

    def measure(self, name, action):
        # Keep only the clock read and the counters needed by TransitionProbe
        # on the game-control thread. Rolling medians and retained operation
        # totals are report-only work and belong on the diagnostics stream.
        key = self.stage+'/'+name
        cycle_key = self.cycle_key
        during_recovery = bool(self.failed_stage)
        start = time.perf_counter()
        try:
            return action()
        finally:
            seconds = time.perf_counter()-start
            self.decision_seconds+=seconds
            if self.stream:
                self.stream.submit(self._record_measure, key, seconds,
                                   cycle_key, during_recovery)
            else:
                self._record_measure(key, seconds, cycle_key, during_recovery)

    def record_probe(self, method, *args):
        """Queue passive transition statistics without delaying game control."""
        if not self.stream:
            getattr(self.probe, method)(*args)
            return
        at=time.perf_counter()
        cost=(self.decision_seconds,self.pacing_seconds)
        stage=self.stage
        context=dict(self.probe_context)
        if method=='observe':
            frame,screen=args
            # Freeze only ~15 KB of sampled UI pixels.  Resize, grayscale,
            # differencing and row aggregation all stay off the input thread.
            top=frame[:210:12, ::12].copy()
            bottom=frame[-150::11, ::12].copy()
            self.stream.submit(self._record_probe_observation,top,bottom,screen,at)
        else:
            self.stream.submit(self._record_probe_event,method,args,at,cost,stage,context)

    def _record_probe_observation(self, top, bottom, screen, at):
        self.probe.observe_sample(np.concatenate((top,bottom)),screen,event_at=at)

    def _record_probe_event(self, method, args, at, cost, stage, context):
        self.probe.stage=stage
        self.probe.context=dict(context)
        if method=='input':
            self.probe.input(*args,event_at=at,cost=cost)
        elif method=='finish':
            self.probe.finish(*args,event_at=at,cost=cost)
        else:
            getattr(self.probe,method)(*args)

    def _record_measure(self, key, seconds, cycle_key=None, during_recovery=False):
        """Aggregate one immutable timing sample off the control thread."""
        try:
            values = self.samples.setdefault(key, deque(maxlen=128))
            values.append(seconds)
            total = self.totals.setdefault(key, {'count':0,'seconds':0})
            total['count'] += 1
            total['seconds'] += seconds
            total['recent_median_ms'] = round(median(values)*1000,3)
            if cycle_key and not during_recovery:
                self.cycle_decision[cycle_key]=self.cycle_decision.get(cycle_key,0)+seconds
        except Exception:
            # Timing telemetry is never authoritative for a game action.
            pass

    def flush(self, account=None, stream=None, direct=False):
        data = dict(goal_id=self.goal_id, operations={k:dict(v) for k,v in self.totals.items()},transitions=list(self.probe.rows),
                    cycle_decision=dict(self.cycle_decision),failed_stage=self.failed_stage)
        if account:
            data['account_queue'] = {key:getattr(account,key,0) for key in ('submitted','processed','dropped','errors')}
            data['account_queue']['pending'] = account.queue.qsize()
        if stream:
            data['diagnostic_queue']=dict(pending=stream.queue.qsize(),dropped=stream.dropped,errors=stream.errors)
            if not direct:
                stream.submit(write_json,self.path,data)
                return
        if direct or not stream:
            write_json(self.path, data)
