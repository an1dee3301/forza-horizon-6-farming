"""Passive transition latency, including polling work; no causal game estimate."""
import time
import cv2
import numpy as np


def summarize_transition_timing(rows):
    """Keep latency separate from its components and from whole-cycle costs.

    The observed interval includes capture/OCR and programmed pauses while the
    game may be animating. It must not be stacked with whole-cycle decision
    time or described as time exclusively caused by Forza. Legacy rows remain
    outside this versioned coverage; no historical timing is reconstructed.
    """
    rows = list(rows)
    current = [r for r in rows if r.get('transition_timing_version') == 2]
    usable = [r for r in current if r.get('outcome') == 'usable']
    return dict(
        version=2,
        basis='input_to_observed_usable_includes_polling',
        scope='recorded_usable_transitions_only',
        usable_count=len(usable),
        partial_count=len(current)-len(usable),
        legacy_count=len(rows)-len(current),
        cost_clipped_count=sum(bool(r.get('cost_accounting_clipped')) for r in usable),
        observed_usable_seconds=sum(r['observed_transition_seconds'] for r in usable),
        polling_work_within_usable_seconds=sum(r['polling_work_seconds'] for r in usable),
        programmed_pacing_within_usable_seconds=sum(r['programmed_pacing_seconds'] for r in usable),
        unassigned_within_usable_seconds=sum(r['unassigned_transition_seconds'] for r in usable),
        causal_game_seconds=None,
    )


class TransitionProbe:
    def __init__(self, clock=time.perf_counter):
        self.clock=clock
        self.last=None
        self.pending=None
        self.rows=[]
        self.stage='startup'
        self.context={}
        self.costs=lambda:(0,0)

    def observe(self, frame, screen, event_at=None):
        # Read UI bands; exclude the animated car body. A pixel change is an
        # observed-change proxy, not proof of why the game changed.
        bands=np.concatenate([cv2.resize(frame[:210],(160,18)),cv2.resize(frame[-150:],(160,14))])
        small=cv2.cvtColor(bands,cv2.COLOR_BGR2GRAY)
        self.observe_sample(small, screen, event_at)

    def observe_sample(self, small, screen, event_at=None):
        """Consume an immutable tiny UI sample, optionally captured earlier."""
        if small.ndim == 3:
            small=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        now=self.clock() if event_at is None else event_at
        if self.pending and self.pending['changed_at'] is None and self.last:
            origin=self.pending['baseline']
            if origin is not None and (screen!=origin[0] or np.mean(cv2.absdiff(small,origin[1]))>12):
                self.pending['changed_at']=now
        self.last=(screen,small)

    def input(self, action, event_at=None, cost=None):
        now=self.clock() if event_at is None else event_at
        current_cost=self.costs() if cost is None else cost
        self.finish('superseded', event_at=now, cost=current_cost)
        self.pending=dict(start=now,baseline=self.last,changed_at=None,
                          stage=self.stage,action=action,cost_start=current_cost,**self.context)

    def finish(self, outcome='usable', event_at=None, cost=None):
        p=self.pending
        if p is None: return
        now=self.clock() if event_at is None else event_at
        changed=p['changed_at']
        cost=self.costs() if cost is None else cost
        initial=p['cost_start']
        elapsed=max(0,now-p['start'])
        work=max(0,cost[0]-initial[0]); pacing=max(0,cost[1]-initial[1])
        # These are disjoint *instrumented execution* components, not causal
        # game/automation attribution. Clamp accounting drift while making it
        # visible; never let stacked interval components exceed the interval.
        polling_work=min(elapsed,work)
        programmed_pacing=min(max(0,elapsed-polling_work),pacing)
        unassigned=max(0,elapsed-polling_work-programmed_pacing)
        wait=max(0,now-p['start']-(cost[0]-initial[0])-(cost[1]-initial[1]))
        self.rows.append({k:v for k,v in p.items() if k not in ('baseline','start','changed_at','cost_start')} | dict(
            outcome=outcome,input_to_change=None if changed is None else max(0,changed-p['start']),
            change_to_usable=None if changed is None or outcome!='usable' else max(0,now-changed),
            input_to_usable=max(0,now-p['start']) if outcome=='usable' else None,
            observed_seconds=elapsed,
            transition_timing_version=2,
            timing_basis='input_to_observed_usable_includes_polling' if outcome=='usable' else 'partial_input_interval',
            observed_transition_seconds=elapsed if outcome=='usable' else None,
            polling_work_seconds=polling_work,
            programmed_pacing_seconds=programmed_pacing,
            unassigned_transition_seconds=unassigned,
            cost_accounting_clipped=work+pacing>elapsed+1e-6,
            causal_game_seconds=None))
        # Compatibility only: this legacy residual excludes overlapping polls
        # and pauses. It is NOT the total animation/load delay or Forza's fault.
        self.rows[-1]['ui_wait_estimate_seconds']=wait if outcome=='usable' else None
        self.rows=self.rows[-2000:]
        self.pending=None
