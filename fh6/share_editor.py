"""Prove an already-empty native share-code editor without sending keys.

The normal 16 backspace/delete pairs remain the fallback. This only authorizes
omitting those clearing keys; it never types, confirms or launches a challenge.
The caller must still verify the exact newly entered code before submission.
"""
import time
import re

import cv2
import numpy as np


FIELD = (653, 575, 614, 45)


def exact_share_code(obs, code):
    """Only the full numeric editor field can authorize submission."""
    if (getattr(obs, 'screen', None) != 'share_code' or
            not isinstance(code, str) or re.fullmatch(r'[0-9]{9}', code) is None):
        return False
    x, y, w, h = FIELD
    fields = [line.text.strip() for line in obs.doc.lines
              if x <= line.center[0] < x+w and y <= line.center[1] < y+h]
    return fields == [code]


def empty_share_editor(obs):
    """Exact editor context plus blank white pixels, allowing its native caret.

    Calibrated against the actual empty editor failure image from 2026-09-09,
    and actual nine-/ten-digit filled editors. An OCR miss alone is never blank
    evidence. An uncertain field keeps the existing full clearing routine.
    """
    frame = getattr(obs, 'frame', None)
    if (getattr(obs, 'screen', None) != 'share_code' or frame is None
            or frame.shape != (1080, 1920, 3)):
        return False
    doc = obs.doc
    required = (('Share Code', (620, 420, 680, 90)),
                ('Enter Share Code', (620, 510, 680, 55)),
                ('Enter', (65, 980, 155, 60)),
                ('Select', (65, 980, 155, 60)),
                ('Cancel', (230, 980, 160, 60)))
    if not all(len(doc.find(label, box)) == 1 for label, box in required):
        return False
    if any(doc.has(label, contains=True) for label in (
            'Confirm', 'Yes', 'No', 'Synchronizing', 'Syncing',
            'Time Remaining', 'Quit Event', 'Retry')):
        return False
    x, y, w, h = FIELD
    if any(x <= line.center[0] < x+w and y <= line.center[1] < y+h
           for line in doc.lines):
        return False
    field = frame[y:y+h, x:x+w]
    # The settled native field is neutral white. Do not accept a fading field,
    # a blank OCR read over scenery, a colored selection, or dark text pixels.
    if np.max(field.max(axis=2)-field.min(axis=2)) > 2:
        return False
    gray = cv2.cvtColor(field, cv2.COLOR_BGR2GRAY)
    _, _, stats, _ = cv2.connectedComponentsWithStats((gray < 250).astype(np.uint8))
    marks = stats[1:]
    if len(marks) == 0:
        return True  # Caret's invisible blink phase.
    if len(marks) != 1:
        return False
    mx, my, mw, mh, area = map(int, marks[0])
    # Only the observed 1..2 px caret near the empty field's center can remain.
    # The actual filled frames contain wider digit components and/or dark ink.
    return (297 <= mx <= 302 and 9 <= my <= 13 and 1 <= mw <= 2
            and 20 <= mh <= 24 and area == mw*mh and int(gray.min()) >= 220)


def verify_empty_share_editor(nav, *, timeout=1.5, clock=time.monotonic):
    """Two current independent frames; False preserves normal clearing.

    No input or OCR is issued here beyond the navigator's required full
    observations. Use the result immediately; exact code verification after
    typing stays mandatory even when clearing is skipped.
    """
    if not 0 < timeout <= 3:
        raise ValueError('Empty editor timeout must be in (0, 3] seconds')
    deadline = clock()+timeout
    provider = getattr(getattr(nav, 'setup_checks', None), 'identity', None)
    sync = getattr(nav, 'sync_guard', None)
    if not callable(provider) or not callable(getattr(sync, 'require_verified', None)):
        return False

    def identity():
        value = provider()
        if (not isinstance(value, (list, tuple)) or len(value) != 1
                or not isinstance(value[0], str) or not value[0]):
            raise RuntimeError('Current game identity unavailable for editor blank proof')
        return tuple(value)

    nav.check()
    pinned = identity()
    sync.require_verified(pinned)
    generation = getattr(nav, 'focus_generation', None)
    if type(generation) is not int or clock() >= deadline:
        return False
    previous = None
    for _ in range(2):
        obs = nav.observe()
        if (clock() >= deadline or nav.last is not obs
                or nav.focus_generation != generation
                or getattr(obs, 'focus_generation', None) != generation
                or not empty_share_editor(obs)):
            return False
        if previous is not None:
            if obs is previous or obs.frame is previous.frame:
                return False
            nav.check()
            if identity() != pinned:
                raise RuntimeError('Game changed while verifying empty share editor')
            sync.require_verified(pinned)
            nav.check()
            return (clock() < deadline and nav.last is obs
                    and nav.focus_generation == generation)
        previous = obs
        nav.pause(min(.04, max(0., deadline-clock())))
    return False
