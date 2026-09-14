"""Funding policy for refill-to-cap, then convert batches."""
from .budget import POINTS_PER_CAR
from .refill_policy import refill_target

SP_CAP = 999
CARS_PER_BATCH = 47


def funded_cars(points, remaining, reserve=0, *, allow_partial=False):
    """Fund from observed SP; permit a partial first batch with a saved baseline."""
    if any(type(n) is not int for n in (points, remaining, reserve)):
        raise ValueError('Batch funding needs whole-number balances and targets')
    if not 0 <= points <= SP_CAP or remaining < 0 or not 0 <= reserve <= 978:
        raise ValueError('Invalid batch funding balance or target')
    if points < refill_target(remaining,reserve) and not allow_partial:
        return 0
    return max(0, min(CARS_PER_BATCH, remaining, (points-reserve)//POINTS_PER_CAR))


def starting_balance_allowed(goal):
    baseline = goal.get('account_baseline') or {}
    return bool(baseline.get('goal_id') == goal.get('id') and baseline.get('fields')
                and not any(goal.get(k,0) for k in ('rewards','bought','farm_runs')))
