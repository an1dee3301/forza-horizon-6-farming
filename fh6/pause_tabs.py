"""Plan reversible pause-tab movement only from a complete visible tab row."""
import cv2
import numpy as np

from .ocr import normalize


TOP = (60, 100, 1770, 150)
PAUSE_TABS = ('CAMPAIGN', 'CARS', 'MY HORIZON', 'ONLINE', 'CREATIVE HUB', 'STORE')


def pause_tab_steps(obs, label):
    """Return (pgup/pgdn, at most 2 steps), or None when proof is incomplete.

    Zero steps means the target is the uniquely selected tab. The caller must
    still obtain fresh destination observations after sending any movement.
    This helper never sends input and never infers tabs omitted by OCR.
    """
    target = normalize(label)
    names = tuple(normalize(name) for name in PAUSE_TABS)
    if target not in names or obs.frame.shape != (1080, 1920, 3):
        return None
    tabs = []
    rx, ry, rw, rh = TOP
    for name in PAUSE_TABS:
        matches = obs.doc.find(name, TOP)
        if len(matches) != 1:
            return None
        tab = matches[0]
        x, y, w, h = tab.box
        if w <= 0 or h <= 0 or not (rx <= x and ry <= y and
                                    x+w <= rx+rw and y+h <= ry+rh):
            return None
        tabs.append(tab)
    if max(tab.center[1] for tab in tabs)-min(tab.center[1] for tab in tabs) > 12:
        return None
    ordered = sorted(tabs, key=lambda tab: tab.center[0])
    if tuple(normalize(tab.text) for tab in ordered) != names:
        return None
    if any(left.box[0]+left.box[2] >= right.box[0]
           for left, right in zip(ordered, ordered[1:])):
        return None
    focused = []
    for index, tab in enumerate(ordered):
        x, y, w, h = tab.box
        # Preserve the existing FarmNavigator.pause_tab black-background test.
        region = obs.frame[y-4:y+h+4, x-7:x+w+7]
        if np.mean(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) < 65) > .55:
            focused.append(index)
    if len(focused) != 1:
        return None
    current, destination = focused[0], names.index(target)
    forward = (destination-current) % len(names)
    backward = (current-destination) % len(names)
    if backward < forward:
        return 'pgup', min(backward, 2)
    return 'pgdn', min(forward, 2)
