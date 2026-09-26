"""Spaced reversible cleanup navigation; confirmation remains with caller."""


def spaced_four_to_focus(nav, target_proven):
    """Caller must first prove Get In Car focus on the exact selected car.

    Retain normal key holds, add released intervals, and require two fresh
    Remove-focus observations. Never send Enter or replay a failed pulse group.
    """
    generation = nav.focus_generation
    for _ in range(4):
        nav.check()
        if nav.focus_generation != generation:
            raise RuntimeError('Cleanup focus changed during spaced pulses; no Enter sent')
        nav.key('down')
        nav.pause(.08)
    nav.pause(.16)
    if nav.focus_generation != generation:
        raise RuntimeError('Cleanup focus changed during spaced pulses; no Enter sent')
    try:
        return nav.wait('car_action', timeout=1.2, stable_frames=2,
                        predicate=target_proven)
    except RuntimeError as exc:
        if 'Timed out' not in str(exc):
            raise
        return None
