"""Durable cycle checkpoints. A partially completed cycle cannot become a new buy."""
import json
import time
from datetime import datetime
from pathlib import Path

from forza_cycle import BASE
from .budget import plan_from_sp


def replace_checkpoint(temporary, destination):
    """A Windows reader may briefly deny replacement; retry the same bytes only."""
    for attempt in range(21):
        try:
            temporary.replace(destination)
            return
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(.025)


class Session:
    def __init__(self, path=BASE/'runs'/'session.json', clock=time.monotonic):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.clock = clock
        self._active_since = None

    def start(self, mode, limit, skill_points=None, reserve_sp=0, *, funding=None):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError('Cycle limit must be a whole number, zero or greater')
        if self.data and self.data.get('phase') != 'complete':
            if self.data['mode'] != mode or self.data['limit'] != limit:
                raise RuntimeError('An unfinished session exists. Keep its mode and limit to resume, or use End session after checking the game.')
            if self._active_since is None:
                self._active_since = self.clock()
            return
        if skill_points is not None:
            plan = plan_from_sp(skill_points, reserve_sp)
            if mode != 'Full pipeline' or plan.cars < 1 or limit != plan.cars:
                raise ValueError('The SP budget must fund at least one car and match the full-pipeline limit.')
        if self.data:
            self.archive()
        self.data = dict(id=datetime.now().strftime('%Y%m%d_%H%M%S_%f'),
                         mode=mode, limit=limit, phase='collection', completed=0,
                         bought=0, rewards=0, purchase_before=None,
                         started_at=datetime.now().isoformat(timespec='seconds'),
                         active_seconds=0, cycle_started_seconds=0, cycle_seconds=[])
        self._active_since = self.clock()
        if skill_points is not None:
            self.data['skill_points'] = plan.points
            self.data['reserve_sp'] = plan.reserve
        if funding is not None:
            # Stored with the first checkpoint, not in a second vulnerable write.
            self.data['funding'] = dict(funding)
        self.save()

    @property
    def elapsed(self):
        return self.data.get('active_seconds', 0) + (
            max(0, self.clock() - self._active_since) if self._active_since is not None else 0)

    def save(self, **changes):
        self.data['active_seconds'] = self.elapsed
        if self._active_since is not None:
            self._active_since = self.clock()
        self.data.update(changes)
        if self.data.get('phase') == 'complete':
            self._active_since = None
            self.data.setdefault('finished_at', datetime.now().isoformat(timespec='seconds'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
        replace_checkpoint(temp, self.path)
        if self.data.get('phase') == 'complete':
            self.archive()

    def finish_cycle(self, completed, done):
        elapsed = self.elapsed
        durations = list(self.data.get('cycle_seconds', []))
        start = self.data.get('cycle_started_seconds')
        # Legacy checkpoints have no timing for their current partial cycle.
        if start is not None:
            durations.append(max(0, elapsed - start))
        self.save(completed=completed, phase='complete' if done else 'collection',
                  cycle_seconds=durations[-20:], cycle_started_seconds=elapsed)

    def pause(self):
        if self._active_since is not None:
            self.save()
            self._active_since = None

    def archive(self):
        folder = self.path.parent/'history'
        folder.mkdir(parents=True, exist_ok=True)
        # Checkpoint ids are file names, never paths from imported JSON.
        identifier = str(self.data.get('id', 'unknown'))
        if not identifier or any(c not in '0123456789_' for c in identifier):
            raise ValueError('Invalid session id')
        path = folder/f'{identifier}.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
        replace_checkpoint(temp, path)

    def history(self):
        records = {}
        paths = [*self.path.parent.glob('ended_*.json'),
                 *(self.path.parent/'history').glob('*.json'), self.path]
        for path in paths:
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(record, dict) and record.get('id') and record.get('mode'):
                    if path.name.startswith('ended_'):
                        record.update(end_reason='ended', phase='complete')
                    records[record['id']] = record
            except (OSError, ValueError):
                continue
        return sorted(records.values(), key=lambda r: r['id'], reverse=True)

    def end(self):
        if self.data:
            archive = self.path.with_name(f"ended_{self.data['id']}.json")
            archive.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
            self.save(phase='complete', end_reason='ended')
