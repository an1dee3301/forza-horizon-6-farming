"""Observed ETA history, updated by the background reporter only."""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path


def baseline(state):
    rows=state.get('rows',[])
    initial=state.get('initial_eta_seconds',0)
    start=state.get('initial_elapsed_seconds',rows[0]['elapsed_seconds'] if rows else 0)
    return start, initial


def zoom_bounds(values, minimum_span=60):
    lo,hi=min(values),max(values)
    padding=max(hi-lo,minimum_span)*.1
    return lo-padding,hi+padding


def runtime_window(state):
    """Start at the first recorded estimate; expand beyond the initial 5h."""
    rows=state.get('rows',[])
    start,_=baseline(state)
    last=max((r['elapsed_seconds'] for r in rows),default=start)
    return start,max(start+5*3600,last+(last-start)*.02)


def observe(data, previous, started_at):
    goal = data.get('goal_id')
    state = previous if previous.get('goal_id') == goal else {'goal_id': goal, 'rows': []}
    rows = list(state.get('rows', []))
    stamp = datetime.fromisoformat(data['timestamp']).astimezone()
    start = datetime.fromisoformat(started_at).astimezone()
    elapsed = max(0, (stamp-start).total_seconds())
    rate = (data.get('analytics', {}).get('operations', {})).get('sw_wall_hour')
    remaining = data.get('remaining')
    valid = lambda n: type(n) in (int,float) and math.isfinite(n)
    if not goal or not valid(remaining) or remaining < 0:
        return state
    if remaining and (not valid(rate) or rate <= 0):
        return state
    eta = remaining * 3600 / rate if remaining else 0
    if rows and stamp <= datetime.fromisoformat(rows[-1]['at']).astimezone():
        return state
    initial = state.get('initial_eta_seconds', eta)
    initial_elapsed = state.get('initial_elapsed_seconds', rows[0]['elapsed_seconds'] if rows else elapsed)
    if initial <= 0:
        return state
    operations=data.get('analytics',{}).get('operations',{})
    row = dict(at=data['timestamp'], elapsed_seconds=elapsed, eta_seconds=eta,
        active_seconds=data.get('analytics',{}).get('active_seconds'),
        active_throughput_sw_hour=operations.get('sw_active_hour'),
        farm_capacity_sw_hour=operations.get('farm_capacity'),
        conversion_capacity_sw_hour=operations.get('conversion_capacity'),
        combined_capacity_sw_hour=operations.get('combined_capacity'),
        projected_completion=(stamp+timedelta(seconds=eta)).isoformat(),
        efficiency_percent=100*(initial-eta)/initial,
        throughput_sw_hour=rate, remaining=remaining, target=data.get('target'))
    # Multiple delivery attempts within one minute replace the same observation.
    if rows and elapsed-rows[-1]['elapsed_seconds'] < 55:
        rows[-1] = row
    else:
        rows.append(row)
    rows=[dict(r,baseline_seconds=max(0,initial-(r['elapsed_seconds']-initial_elapsed))) for r in rows]
    return dict(goal_id=goal, initial_eta_seconds=initial, initial_elapsed_seconds=initial_elapsed, rows=rows)


def update(root, data):
    from .reporting import read_json, write_json
    root=Path(root)
    goal=read_json(root/'goal.json')
    if not goal.get('started_at') or goal.get('id') != data.get('goal_id'):
        return
    path=root/'eta_history.json'
    state=observe(data,read_json(path),goal['started_at'])
    write_json(path,state)
    data['eta_history']=state
    html=(Path(__file__).with_name('eta_history.html')).read_text(encoding='utf-8')
    html=html.replace('__DATA__',json.dumps(state).replace('<','\\u003c'))
    destination=root/'reports'/'eta_history.html'
    destination.parent.mkdir(exist_ok=True)
    temporary=destination.with_suffix('.tmp')
    temporary.write_text(html,encoding='utf-8')
    temporary.replace(destination)
