"""Durable acknowledgement for a single verified removal; never sends input."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def identity(nav):
    nav.check()
    value = nav.setup_checks.identity()
    if not isinstance(value, (list, tuple)) or len(value) != 1 or not isinstance(value[0], str) or not value[0]:
        raise RuntimeError('Cleanup process identity unavailable')
    return list(value)


class RemovalJournal:
    def __init__(self, tracker):
        self.tracker = tracker
        self.path = Path(tracker.root) / 'garage_removal_pending.json'

    def read(self):
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding='utf-8'))

    def save(self, row):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        from .session import replace_checkpoint
        try:
            with temp.open('w', encoding='utf-8') as stream:
                json.dump(row, stream)
                stream.flush()
                os.fsync(stream.fileno())
            replace_checkpoint(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)

    def begin(self, nav):
        if self.read() is not None:
            raise RuntimeError('Cleanup acknowledgement must be reconciled before another removal')
        row = dict(operation_id=uuid.uuid4().hex, goal_id=self.tracker.data.get('goal_id'),
                   game_identity=identity(nav), state='prepared', prepared_at=now())
        self.save(row)
        return row

    def submitted(self, row):
        row.update(state='submitted', submitted_at=now())
        self.save(row)

    def acknowledged(self, row, nav):
        if row['game_identity'] != identity(nav):
            raise RuntimeError('Cleanup process changed before acknowledgement')
        row.update(state='acknowledged', acknowledged_at=now(), proof='two_fresh_garage_grid_frames')
        self.save(row)

    def finish(self, row, reason):
        # Preserve an immutable operation outcome before removing the pending slot.
        folder = self.path.parent / 'garage_removal_operations'
        folder.mkdir(exist_ok=True)
        destination = folder / (row['operation_id'] + '.json')
        outcome = dict(row, outcome=reason, finished_at=now())
        try:
            with destination.open('x', encoding='utf-8') as stream:
                json.dump(outcome, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            previous = json.loads(destination.read_text(encoding='utf-8'))
            if previous['operation_id'] != row['operation_id'] or previous['outcome'] != reason:
                raise RuntimeError('Cleanup operation outcome conflicts with existing evidence')
        self.path.unlink(missing_ok=True)

    def commit(self, row):
        if row.get('state') != 'acknowledged' or row.get('goal_id') != self.tracker.data.get('goal_id'):
            raise RuntimeError('Cleanup journal requires matching acknowledged operation')
        before = self.tracker.data.get('garage_cleanup', {}).get('removed', 0)
        self.tracker.event('garage_removed', {'count': 1, 'operation_id': row['operation_id']})
        self.finish(row, 'journaled')
        return int(self.tracker.data.get('garage_cleanup', {}).get('removed', 0) > before)
