"""Plan refills from observed yield; only a verified balance funds a car."""
from math import ceil, floor, isfinite
from statistics import median


MEGA = '155439962'


def refill_target(remaining, reserve=0):
    return min(999, min(47,max(0,remaining))*21+reserve)


def _legacy_plan(before, target, farms, duration, share_code):
    rates=[r['gained_sp']/(r.get('drive_seconds') or r['active_seconds']) for r in farms
           if r.get('share_code','155439962')==share_code and not r.get('capped') and not r.get('partial_timing') and r.get('gained_sp',0)>=21
           and r.get('exit_reason','natural_completion')=='natural_completion'
           and (r.get('drive_seconds') or r.get('active_seconds',0))>=min(300,duration*.9)]
    rate=median(rates[-10:]) if len(rates)>=3 else None
    needed=max(0,target-before)
    # Only the final top-up is shortened. Two full runs are still appropriate
    # when the current balance is far from enough for the batch.
    seconds=min(duration,max(420,needed/rate)) if rate else duration
    intentional=bool(duration>=420 and rate and 0<needed<rate*duration*.85)
    if intentional: seconds=min(600,max(420,seconds))
    return dict(target_sp=target,needed_sp=needed,estimated_sp_per_second=rate,
                planned_drive_seconds=seconds if intentional else duration,
                planned_exit='target_top_up' if intentional else 'natural_completion',
                yield_samples=len(rates))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _paired_yield(row):
    gain = row.get('gained_sp')
    if not _number(gain) or not 21 <= gain <= 999:
        return False
    before, after = row.get('before_sp'), row.get('after_sp')
    if before is not None or after is not None:
        return (type(before) is int and type(after) is int and
                0 <= before < after < 999 and after - before == gain)
    return True


def _mega_samples(farms, duration):
    native, legacy, topups = [], [], []
    for row in farms:
        # Missing historical profile codes are unknown, not evidence of Mega.
        if row.get('share_code') != MEGA or row.get('capped') or not _paired_yield(row):
            continue
        drive = row.get('drive_seconds')
        if (row.get('exit_reason') == 'intentional_target_top_up' and
                _number(drive) and 598 <= drive <= 602 and
                type(row.get('before_sp')) is int and type(row.get('after_sp')) is int):
            # These are observed balance pairs, not clean natural-run training.
            # Their partial whole-farm timing flag is retained in plan metadata.
            topups.append(row)
        if row.get('partial_timing') or row.get('exit_reason', 'natural_completion') != 'natural_completion':
            continue
        if _number(drive) and duration * .9 <= drive <= duration * 1.25:
            native.append(row)
        elif drive is None or (_number(drive) and drive == 0):
            active = row.get('active_seconds')
            if _number(active) and active >= duration * .9:
                legacy.append(row)
    return native[-10:], legacy[-10:], topups[-10:]


def plan(before, target, farms, duration=900, share_code=MEGA, *, reserve_sp=0):
    """Return a new plan; never change an already pinned challenge plan.

    Mega uses native drive timers exclusively for drive deadlines. Legacy
    whole-farm records may estimate a full run's yield, never its drive rate.
    Headroom limits are estimates from observed rates, not proof of SP earned.
    """
    if share_code != MEGA:
        return _legacy_plan(before, target, farms, duration, share_code)
    if (type(before) is not int or type(target) is not int or
            not 0 <= before <= 999 or not 0 <= target <= 999 or
            type(reserve_sp) is not int or not 0 <= reserve_sp <= 978 or
            not _number(duration) or duration <= 0):
        raise ValueError('Refill planning requires valid SP balances, reserve and duration')
    native, legacy, topups = _mega_samples(farms, duration)
    # Two explicitly identified native runs support an initial estimate, not a
    # precise distribution. Expose the small cohort instead of borrowing old
    # observations whose challenge profile was never recorded.
    training = native if len(native) >= 2 else legacy if len(legacy) >= 3 else []
    rates = [r['gained_sp'] / r['drive_seconds'] for r in native] if len(native) >= 2 else []
    yields = [r['gained_sp'] for r in training]
    expected = float(median(yields)) if yields else None
    margin = max(2, ceil(max(yields) - expected) + 2) if yields else None
    basis = ('native_drive' if rates else 'legacy_full_yield_only' if training else 'insufficient_samples')
    needed, headroom = max(0, target - before), 999 - before
    funded = max(0, (before - reserve_sp) // 21)
    result = dict(target_sp=target, needed_sp=needed, headroom_sp=headroom,
                  expected_yield_sp=expected, safety_margin_sp=margin,
                  estimated_sp_per_second=float(median(rates)) if rates else None,
                  yield_timer_basis=basis, yield_samples=len(training), yield_small_sample=len(training) < 3,
                  native_yield_samples=len(native), legacy_yield_samples=len(legacy),
                  funded_cars=funded, reserve_sp=reserve_sp,
                  mode='bulk', planned_exit='natural_completion', planned_drive_seconds=duration,
                  top_up_calibration_samples=0,
                  estimate_only=True)

    def convert(reason):
        result.update(mode='convert', planned_exit='convert_existing',
                      planned_drive_seconds=0, reason=reason)
        return result

    if needed == 0:
        return convert('target_already_funded')
    if funded and (needed <= 21 or headroom <= 21):
        return convert('tiny_gap_convert_verified_balance')
    if expected is not None and needed >= expected and headroom >= expected + margin:
        result['reason'] = 'full_yield_and_margin_fit'
        return result
    if not rates:
        if funded:
            return convert('no_native_deadline_convert_verified_balance')
        result['reason'] = 'bootstrap_without_native_deadline'
        return result

    # Unlike the old 420s minimum, this upper deadline shrinks with headroom.
    # Two seconds accommodate observed countdown polling/exit overshoot; this
    # is an engineering guard, not a bound on unobserved bursts or loading.
    guard_seconds, guard_sp = 2, 2
    cap_seconds = max(0, floor((headroom - guard_sp) / max(rates) - guard_seconds))
    # Headroom already bounds the exit. An additional ten-minute ceiling
    # caused split top-ups even when a longer single run safely fit the estimate.
    seconds = min(duration, max(60, ceil((needed + guard_sp) / min(rates))), cap_seconds)
    deadline_basis = 'native_natural_rate_estimate'
    top_up_rate = result['estimated_sp_per_second']

    # Preserve the measured 600s/47-car outcome near its observed starting SP.
    # Natural-run extrapolation alone proposed ~575s here, but the observed
    # top-up rates project only 46 cars at that duration. Do not call it faster.
    if topups:
        calibrated_rate = max(r['gained_sp'] / r['drive_seconds'] for r in topups)
        calibrated_cap = max(0, floor((headroom - 1) / calibrated_rate - guard_seconds))
        nearby = min(r['before_sp'] for r in topups) - 2 <= before <= max(r['before_sp'] for r in topups) + 2
        if (duration >= 600 and nearby and calibrated_cap >= 600 and
                target <= min(r['after_sp'] for r in topups) and
                needed >= min(r['gained_sp'] for r in topups) - 21):
            seconds, cap_seconds, guard_sp = 600, calibrated_cap, 1
            deadline_basis = 'observed_600s_balance_pairs'
            top_up_rate = float(median(r['gained_sp'] / r['drive_seconds'] for r in topups))
            result.update(top_up_calibration_samples=len(topups),
                          top_up_calibration_partial_timing=any(r.get('partial_timing') for r in topups),
                          top_up_calibration_uncertainty=('single_verified_balance_pair' if len(topups) == 1
                                                          else 'limited_observed_balance_pairs'))
    if seconds < 1:
        if funded:
            return convert('headroom_too_small_for_useful_top_up')
        # This only arises when a configured reserve leaves no spendable car.
        # Never turn an unsafe zero-length top-up into a full challenge.
        raise ValueError('SP reserve leaves no funded car and no headroom for a guarded top-up')
    result.update(mode='topup', planned_exit='target_top_up', planned_drive_seconds=seconds,
                  reason='headroom_bounded_top_up', deadline_basis=deadline_basis,
                  headroom_drive_limit_seconds=cap_seconds,
                  top_up_safety_margin_sp=guard_sp, exit_guard_seconds=guard_seconds,
                  estimated_top_up_sp_per_second=top_up_rate,
                  expected_top_up_yield_sp=seconds * top_up_rate)
    return result


def mini_cap_batch(points, remaining, reserve, farms):
    """Convert a near-full verified balance when another Mini would waste >=21 SP."""
    if points < 42*21+reserve or remaining <= 0:
        return False
    samples=[r['gained_sp'] for r in farms if r.get('share_code')=='169055890'
             and not r.get('capped') and not r.get('partial_timing')
             and r.get('exit_reason')=='natural_completion'
             and 270 <= (r.get('drive_seconds') or 0) <= 330
             and 21 <= r.get('gained_sp',0) <= 999][-10:]
    return len(samples)>=3 and points+median(samples)-999>=21
