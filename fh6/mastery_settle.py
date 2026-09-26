"""Read-only bounded settling for an otherwise valid fresh Mazda tree."""
import time
import forza_cycle as core

ERROR = 'This Mazda does not have a fresh mastery path; no points spent'
NAMES = frozenset(node[0] for node in core.NODES)


def uncertain_fresh_tree(obs):
    if obs.screen != 'mad_mike_mastery' or obs.result.get('screen') != 'mad_mike_mastery':
        raise RuntimeError(ERROR)
    nodes = obs.result.get('nodes', {})
    if set(nodes) != NAMES or any(node.get('state') not in
            {'available', 'unavailable', 'unknown'} for node in nodes.values()):
        raise RuntimeError(ERROR)
    if nodes['Head-Turner'].get('state') != 'available':
        raise RuntimeError('The first mastery node is unavailable')
    return any(node['state'] == 'unknown' for node in nodes.values())


def settle_fresh_tree(nav, obs, *, clock=time.monotonic):
    """Keep classifier thresholds unchanged; never issue gameplay input.

    Only unknown interior states on the exact six-node unowned tree qualify.
    Polling has a 1.2-second deadline; late observations cannot authorize a claim.
    Owned nodes or another screen fail immediately, including while settling.
    """
    if not uncertain_fresh_tree(obs):
        return obs
    deadline = clock()+1.2
    generation = nav.focus_generation
    previous_stamp = getattr(obs, 'captured_monotonic', None)
    stable = 0
    while clock() < deadline:
        current = nav.observe()
        if clock() >= deadline or nav.focus_generation != generation:
            raise RuntimeError(ERROR)
        uncertain = uncertain_fresh_tree(current)
        stamp = getattr(current, 'captured_monotonic', None)
        if stamp is None or (previous_stamp is not None and stamp <= previous_stamp):
            raise RuntimeError(ERROR)
        previous_stamp = stamp
        stable = 0 if uncertain else stable+1
        if stable == 2:
            return current
        remaining = deadline-clock()
        if remaining > 0:
            nav.pause(min(.04, remaining))
    raise RuntimeError(ERROR)
