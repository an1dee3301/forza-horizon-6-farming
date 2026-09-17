"""Discord farm-start events, independent of reward delivery checkpoints."""
from datetime import datetime, timedelta


def planned_farm_remaining(remaining, elapsed, refill_plan):
    """Reporting only: the current farm can end before the event timer."""
    from math import isfinite
    if not isinstance(refill_plan, dict) or refill_plan.get('planned_exit') != 'target_top_up':
        return remaining
    planned = refill_plan.get('planned_drive_seconds')
    if any(type(value) not in (int, float) or not isfinite(value) or value < 0
           for value in (remaining, elapsed, planned)):
        return remaining
    return min(remaining, max(0., planned-elapsed))


def active_farm(goal, challenge, runtime, *, active, timestamp):
    identifier = challenge.get('id', '')
    if (not active or not runtime.get('active')
            or goal.get('phase') not in {'farm', 'terminal_sp_topup'}
            or challenge.get('phase') != 'drive'
            or not identifier.startswith(str(goal.get('id'))+'_')
            or runtime.get('stage') != 'farm_drive'
            or not runtime.get('status', '').startswith('Farming SP — ')):
        return None
    try:
        age = (datetime.fromisoformat(timestamp)-datetime.fromisoformat(runtime['updated_at'])).total_seconds()
        attempt = int(challenge.get('launch_attempts', 0))
        if not 0 <= age <= 45 or attempt < 1:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return dict(key=f"{identifier}:{attempt}", id=identifier, attempt=attempt,
                before_sp=challenge.get('before_sp'), share_code=challenge.get('share_code'),
                verified_at=runtime['updated_at'], timer=runtime['status'])


def farm_due(data, saved):
    event = data.get('farm_event')
    return bool(event and event['key'] not in saved.get('sent_keys', []))


def discord_time(value, style='R'):
    if not value:
        return 'Not yet verified'
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            stamp = stamp.astimezone()
        return f'<t:{int(stamp.timestamp())}:{style}>'
    except (ValueError, TypeError):
        return 'Time unavailable'


def projected_time(reference, seconds, style='R'):
    try:
        if type(seconds) not in (int, float) or seconds < 0:
            return 'Time unavailable'
        stamp = datetime.fromisoformat(reference)
        if stamp.tzinfo is None:
            stamp = stamp.astimezone()
        return f'<t:{int((stamp+timedelta(seconds=seconds)).timestamp())}:{style}>'
    except (ValueError, TypeError):
        return 'Time unavailable'


def observed_time(value):
    return discord_time(value, 'R')
