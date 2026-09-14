"""Calibrated current-car badge proof for the first Recently Added card only.

This is visual evidence, not a transaction or car-identity decision. The caller
must independently prove sort, exact card text, saved recovery state and freshness.
"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

import forza_cycle as core


FIRST_CARD = (399, 204, 341, 260)
GLYPH = (694, 385, 30, 31)
CARD_PITCH = (332, 252)
TEMPLATE = Path(__file__).resolve().parent.parent/'recognition/current_car_glyph.png'
MIN_SCORE = .95


@lru_cache(maxsize=1)
def _template():
    image = cv2.imread(str(TEMPLATE))
    if image is None or image.shape != (31, 30, 3):
        return None
    image.flags.writeable = False
    return image


def _badge(frame, template, column, row):
    x, y, width, height = GLYPH
    x += column*CARD_PITCH[0]
    y += row*CARD_PITCH[1]
    # This slot must contain the full glyph and its tiny alignment search.
    if x-3 < 0 or y-3 < 0 or x+width+3 > frame.shape[1] or y+height+3 > frame.shape[0]:
        return False
    area = frame[y-3:y+height+3, x-3:x+width+3]
    scores = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(scores)
    if not np.isfinite(score) or score < MIN_SCORE:
        return False
    dx, dy = location
    patch = area[dy:dy+height, dx:dx+width]
    lime = cv2.inRange(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV), (20, 160, 190), (45, 255, 255))
    fraction = cv2.countNonZero(lime)/lime.size
    # A lime focus edge, NEW text or a blank square is not the steering icon.
    return .60 <= fraction <= .85


def current_first_card(frame, selected_box):
    """True only for a uniquely current, fully focused first calibrated card."""
    if not isinstance(frame, np.ndarray) or frame.shape != (1080, 1920, 3) or frame.dtype != np.uint8:
        return False
    if not isinstance(selected_box, (tuple, list)) or len(selected_box) != 4:
        return False
    if any(type(value) not in (int, float) or not np.isfinite(value)
           or abs(value-expected) > 3 for value, expected in zip(selected_box, FIRST_CARD)):
        return False
    box = tuple(round(value) for value in selected_box)
    if not core.has_focus(frame, box):
        return False
    template = _template()
    if template is None or not _badge(frame, template, 0, 0):
        return False
    # Only four complete card columns and three rows are visible at 1080p.
    # A second visible glyph means ambiguous evidence, even on a duplicate.
    return not any(_badge(frame, template, column, row)
                   for row in range(3) for column in range(4) if (column, row) != (0, 0))
