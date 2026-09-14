"""Display-only session statistics. Never decide purchases from estimates."""
from statistics import mean

from .budget import POINTS_PER_CAR, CREDITS_PER_CAR


def duration(seconds):
    if seconds is None:
        return '—'
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours:d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


def summary(data, elapsed=None):
    completed = data.get('completed', 0)
    limit = data.get('limit', 0)
    elapsed = data.get('active_seconds', 0) if elapsed is None else elapsed
    remaining = max(0, limit - completed) if limit else None
    points = data.get('skill_points')
    if points is not None:
        points = max(0, points - data.get('rewards', 0) * POINTS_PER_CAR)
    if data.get('mode') == 'Earn saved Super Wheelspins':
        points = data.get('last_sp')
    if data.get('end_reason') == 'ended':
        points = None  # An ended run may have spent points on a partial tree.
    durations = [n for n in data.get('cycle_seconds', []) if n > 0]
    eta = None
    finished = data.get('phase') == 'complete'
    if remaining == 0 or finished:
        eta = 0
    elif remaining is not None and durations:
        current = max(0, elapsed - data.get('cycle_started_seconds', elapsed))
        eta = max(1, mean(durations) * remaining - current)
    return dict(completed=completed, remaining=remaining, elapsed=elapsed, eta=eta,
                points=points, partial_tree=data.get('phase') == 'mastery',
                credits=data.get('bought', 0) * CREDITS_PER_CAR,
                percent=min(100, completed / limit * 100) if limit else 0)
