"""Guard automatic worker restarts against creating or replacing a mission."""


class RetryDelay:
    """Retry quickly after progress; cap delay without capping attempts."""
    def __init__(self):
        self.attempts = 0
        self.stage = None
        self.progress = None

    def observe(self, kind, value):
        if kind == 'stage' and value != self.stage:
            self.stage = value
            self.attempts = 0
        elif kind == 'progress':
            key = tuple(value.get(k) for k in ('id', 'phase', 'rewards', 'bought', 'farm_runs'))
            if key != self.progress:
                self.progress = key
                self.attempts = 0

    def next(self):
        self.attempts += 1
        return min(15, 3 * 2 ** min(3, self.attempts-1))


def validate_resume(goal, identifier):
    if not identifier:
        return
    if goal.get('id') != identifier or goal.get('phase') == 'complete':
        raise RuntimeError('Automatic resume cancelled: the saved mission completed or changed')
