"""Apply refill decisions without turning an unverified early exit into a full run."""
import json
from pathlib import Path
import time
from math import ceil

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
    result = decision(points, target, farms, profile, reserve=reserve, early_exit_disabled=disabled)
    # A nearly full batch can be processed now; launching a second small
    # top-up adds search/load/exit overhead for only a few additional cars.
    if (profile.share_code == '155439962'
            and (points-reserve)//21 >= 42 and 0 < target-points <= 4*21):
        result.update(mode='convert', planned_exit='convert_existing', planned_drive_seconds=0,
                      reason='near_full_batch_avoid_small_topup_overhead')
    return result


def decision(points, target, farms, profile, *, reserve=0, early_exit_disabled=False):
    result = plan(points, target, farms, profile.duration_seconds,
                  share_code=profile.share_code, reserve_sp=reserve)
    if early_exit_disabled and result.get('planned_exit') == 'target_top_up':
        if points-reserve < 21:
            raise RuntimeError('A full refill would exceed SP headroom and early-exit retention is unverified')
        result.update(mode='convert', planned_exit='convert_existing', planned_drive_seconds=0,
                      reason='early_exit_unverified_convert_funded_balance')
    return result


def force_exact_target(plan, points, target, profile):
    """Turn a normal convert decision into a bounded terminal top-up.

    Normal production should convert a nearly full balance.  At final credit
    exhaustion there is nothing left to convert, so reaching the requested SP
    reserve is the useful action.  The game cap makes overshoot harmless.
    """
    result = dict(plan)
    if not (type(points) is int and type(target) is int and 0 <= points < target <= 999):
        return result
    if result.get('mode') != 'convert':
        return result
    rate = result.get('estimated_sp_per_second')
    duration = getattr(profile, 'duration_seconds', 0)
    if isinstance(rate, (int, float)) and rate > 0:
        seconds = max(60, ceil((target-points+4)/rate))
        seconds = min(duration, seconds) if duration else seconds
        basis = 'terminal_exact_target_recent_rate'
    else:
        seconds = duration
        basis = 'terminal_exact_target_full_run_fallback'
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        raise RuntimeError('Terminal SP top-up has no safe challenge duration')
    result.update(mode='topup', planned_exit='target_top_up', planned_drive_seconds=seconds,
                  reason='terminal_exact_target', deadline_basis=basis,
                  expected_top_up_yield_sp=(seconds*rate if isinstance(rate, (int,float)) and rate>0 else None))
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
