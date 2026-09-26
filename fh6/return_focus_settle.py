"""Input-free proof of the two supported return menu targets."""
from dataclasses import dataclass
import time

SUPPORTED = {('journal', 'Master Explorer'), ('discover', 'Car Collection')}

@dataclass(frozen=True)
class FocusResult:
    observation: object
    elapsed: float
    captures: int
    # None means retain the original selection loop, starting with a fresh wait.
    proved: bool


def wait_target_focus(nav, screens, label, focus_boxes, *, region=None,
                      contains=False, timeout=.3, clock=time.monotonic):
    """Replace a pacing interval, never a purchase/reward/identity check.

    Call AFTER the existing arrow pulse(s), or INSTEAD OF the .30-second
    pre-Enter sleep plus wait. Success proves the exact target on two distinct
    fresh captures. Failure emits no input: caller resumes the original loop
    with nav.wait, without resending its previous arrow. This function NEVER
    presses Enter, so the original caller remains its sole owner.
    """
    expected = {screens} if isinstance(screens, str) else set(screens)
    if not expected or any((screen, label) not in SUPPORTED for screen in expected):
        raise ValueError('Unsupported adaptive focus seam')
    if timeout <= 0:
        raise ValueError('timeout must be positive')
    start = clock()
    end = start + timeout
    generation = nav.focus_generation
    previous = None
    last_obs = None
    captures = 0
    while clock() < end:
        nav.check()
        obs = nav.observe()  # Full existing identity/dialog/focus checks.
        captures += 1
        if nav.focus_generation != generation:
            raise RuntimeError('Input focus changed during adaptive settling')
        if obs.screen not in expected | {'unknown'}:
            raise RuntimeError(f'Unexpected screen during adaptive settling: {obs.screen}')
        if clock() >= end:
            break
        targets = obs.doc.find(label, region, contains)
        boxes = focus_boxes(obs.frame) if obs.screen in expected else []
        proof = None
        if len(targets) == len(boxes) == 1:
            target = targets[0]
            x, y, w, h = boxes[0]
            tx, ty = target.center
            if x <= tx <= x+w and y <= ty <= y+h:
                proof = (obs.screen, tuple(boxes[0]), tuple(target.box))
        distinct = (last_obs is not None and obs is not last_obs
                    and obs.frame is not last_obs.frame)
        same = (previous is not None and proof is not None
                and proof[0] == previous[0]
                and all(abs(a-b) <= 3 for a, b in zip(proof[1], previous[1]))
                and all(abs(a-b) <= 3 for a, b in zip(proof[2], previous[2])))
        if distinct and same:
            nav.check()
            if nav.focus_generation != generation:
                raise RuntimeError('Input focus changed before adaptive handoff')
            return FocusResult(obs, clock()-start, captures, True)
        previous = proof if last_obs is None or distinct else None
        last_obs = obs
        nav.pause(min(.02, max(0., end-clock())))
    return FocusResult(None, clock()-start, captures, False)
