"""Count user-approved starting inventory without inventing earned rewards."""
from datetime import datetime, timezone
from pathlib import Path

from .ownership import WorkerLease
from .session import Session


def totals(goal):
    carry = goal.get('starting_spins_counted', 0)
    earned = goal.get('rewards', 0)
    target = goal.get('limit', 0) + carry
    return dict(starting_spins=carry, total_progress=earned+carry,
                total_target=target, new_target=goal.get('limit', 0),
                total_percent=round(100*(earned+carry)/target,1) if target else 0)


def include_starting_inventory(root, total_target, starting_spins, cycle_target_seconds=50):
    if any(type(v) is not int for v in (total_target, starting_spins, cycle_target_seconds)):
        raise ValueError('Targets must be whole numbers')
    new_target = total_target-starting_spins
    if not 1 <= new_target <= 10000 or starting_spins < 0 or cycle_target_seconds <= 0:
        raise ValueError('Invalid total or starting inventory')
    root = Path(root)
    with WorkerLease():
        goal = Session(root/'goal.json')
        data = goal.data
        baseline = data.get('account_baseline') or {}
        if (not data.get('id') or baseline.get('goal_id') != data['id'] or
                baseline.get('fields', {}).get('super_wheelspins') != starting_spins):
            raise ValueError('Starting inventory must match this mission’s verified baseline')
        batch = data.get('batch') or {}
        committed = data.get('rewards', 0)+max(0, batch.get('cycles', 0)-batch.get('rewards_seen', 0))
        committed += (data.get('reservation') or {}).get('count', 0)
        if new_target < max(committed, data.get('bought', 0)):
            raise ValueError('The target is below the already funded car batch')
        history = list(data.get('target_changes', []))
        history.append(dict(at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                            previous_new_target=data['limit'], new_target=new_target,
                            starting_spins=starting_spins, total_target=total_target))
        goal.save(limit=new_target, starting_spins_counted=starting_spins,
                  cycle_target_seconds=cycle_target_seconds, target_changes=history)
        return goal.data
