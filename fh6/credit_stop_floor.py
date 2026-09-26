"""Explicit goal-bound credit reserve; never mutates inventory or purchase history."""
from .credit_limit import PRICE, SOURCE


def floor_for(goal):
    policy = goal.get('credit_stop_floor')
    if policy is None:
        return None
    if (not isinstance(policy, dict) or policy.get('goal_id') != goal.get('id')
            or type(policy.get('credits')) is not int
            or not 0 < policy['credits'] <= 999_999_999):
        raise RuntimeError('Credit stop floor is not bound to this goal')
    return policy['credits']


def apply(goal, proof):
    floor = floor_for(goal)
    if floor is None:
        return proof
    if (proof.get('goal_id') != goal.get('id') or proof.get('source') != SOURCE
            or not goal.get('credit_account')
            or str(proof.get('gamertag','')).casefold() != str(goal['credit_account']).casefold()
            or type(proof.get('available_credits')) is not int
            or proof['available_credits'] < 0
            or type(proof.get('affordable_purchases')) is not int):
        raise RuntimeError('Credit stop floor requires identified receipt-backed budget')
    capacity = max(0, proof['available_credits']-floor)//PRICE
    return dict(proof, credit_stop_floor=floor,
                affordable_purchases=min(proof['affordable_purchases'], capacity))


def configure(goal, value=None, *, account=None):
    """Persist explicit floor once; omission preserves any saved goal policy."""
    if value is None:
        floor_for(goal.data)
        return
    if type(value) is not int or not 1 <= value <= 999_999_999:
        raise ValueError('Credit floor must be a whole number from 1 to 999,999,999')
    if goal.data.get('phase') == 'complete':
        raise ValueError('A completed goal cannot be reopened by a credit floor option')
    bound = goal.data.get('credit_account') or account
    if not isinstance(bound,str) or not bound.strip():
        raise ValueError('Credit floor needs the identified game account before starting')
    existing = floor_for(goal.data)
    if existing is not None and existing != value:
        raise ValueError('Resume with the saved credit floor')
    goal.save(credit_limited=True, credit_account=bound,
              credit_stop_floor={'goal_id':goal.data['id'],'credits':value})


def configure_cleanup(goal, policy=None):
    """Final-only cleanup is explicit and survives omitted resume options."""
    policy = goal.data.get('cleanup_policy') if policy is None else policy
    if policy is None:
        return
    if policy != 'final_only':
        raise ValueError('Supported cleanup policy is final_only')
    if floor_for(goal.data) is None:
        raise ValueError('Final-only cleanup requires a saved credit floor')
    if goal.data.get('phase') == 'complete':
        return
    goal.save(cleanup_policy='final_only', cleanup_after_each_batch=False,
              cleanup_every_batches=0, cleanup_every_cars=0)
