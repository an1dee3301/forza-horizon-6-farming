"""Validate a diagnostic emitted only after current guarded countdown proof."""
from math import isfinite


def valid_farm_active(value):
    if not isinstance(value, dict) or value.get('proof') != 'two_fresh_native_countdown_frames':
        return False
    current, previous = value.get('remaining_seconds'), value.get('previous_remaining_seconds')
    return (isinstance(value.get('id'), str) and bool(value['id']) and
            value.get('guard_current') is True and
            all(type(n) in (int, float) and isfinite(n) for n in (current, previous)) and
            0 <= current < previous)
