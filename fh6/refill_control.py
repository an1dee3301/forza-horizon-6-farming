"""Apply refill decisions without turning an unverified early exit into a full run."""
import json
from pathlib import Path
import time

from .refill_policy import plan
from .telemetry import duration


def _planning_object(path, check):
    """A transient checkpoint read failure is not an empty calibration.

    Missing optional files are accepted only after three confirmed absences in
    an accessible run directory. Any other failure exhausts into a retryable
    control error. Normal reads incur no sleep; retries wait at most 50ms/file.
    """
    missing_only, error = True, None
    for attempt in range(3):
        check()
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError('expected an object')
        except FileNotFoundError as exc:
            error = exc
            try:
                path.parent.stat()
            except OSError as parent_error:
                missing_only, error = False, parent_error
        except (OSError, ValueError) as exc:
            missing_only, error = False, exc
        else:
            check()
            return value
        if attempt < 2:
            time.sleep(.025)
    check()
    if missing_only:
        return {}
    raise RuntimeError(f'Refill inputs unavailable: {path.name} ({type(error).__name__}); no plan changed') from error


def decision_from_files(points, target, root, profile, *, reserve=0, check=lambda: None):
    """Read control inputs strictly from this session's run directory."""
    root = Path(root)
    history = _planning_object(root / 'analytics.json', check)
    validation = _planning_object(root / 'early_exit_validation.json', check)
    farms = history.get('farms', [])
    disabled = validation.get('disabled', False)
    if not isinstance(farms, list) or any(not isinstance(row, dict) for row in farms):
        raise RuntimeError('Refill inputs unavailable: analytics.json has invalid farm history; no plan changed')
    if type(disabled) is not bool:
        raise RuntimeError('Refill inputs unavailable: early_exit_validation.json has invalid disabled flag; no plan changed')
    check()
    return decision(points, target, farms, profile, reserve=reserve, early_exit_disabled=disabled)


def decision(points, target, farms, profile, *, reserve=0, early_exit_disabled=False):
    result = plan(points, target, farms, profile.duration_seconds,
                  share_code=profile.share_code, reserve_sp=reserve)
    if early_exit_disabled and result.get('planned_exit') == 'target_top_up':
        if points-reserve < 21:
            raise RuntimeError('A full refill would exceed SP headroom and early-exit retention is unverified')
        result.update(mode='convert', planned_exit='convert_existing', planned_drive_seconds=0,
                      reason='early_exit_unverified_convert_funded_balance')
    return result


def describe(result, profile_name):
    mode = result.get('mode', 'bulk').upper()
    expected = result.get('expected_yield_sp')
    forecast = (f'{expected:.1f} SP + {result.get("safety_margin_sp", 0)} SP margin'
                if isinstance(expected, (int, float)) else 'uncalibrated')
    return (f'{profile_name} {mode}: {result.get("headroom_sp", "?")} SP headroom; '
            f'{result.get("needed_sp", "?")} SP needed; expected full yield {forecast}; '
            f'planned drive {duration(result.get("planned_drive_seconds", 0))}. '
            'Spendable SP is verified after exit.')
