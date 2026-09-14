"""Read actual available SP from the paused Cars tile, without opening its tree.

Calibrated against the recorded 1920x1080 Return Pause frame showing
``754 Skill Points Available``. This module never sends input or writes a
balance/checkpoint. Crop transforms from one frame are one observation.
"""
import re
import time

import cv2

from .pause_mastery import target_title


SP_BOX = (535, 770, 565, 55)
ACCOUNT_BOX = (1300, 40, 440, 155)
FOOTER_BOX = (65, 980, 290, 60)
SP_LABEL = re.compile(r'([0-9]{1,3})\s+Skill\s+Points\s+Available', re.IGNORECASE)


def read_tab_sp(reader, obs, gamertag):
    """Exact 0..99 Cars badge on any complete pause tab; 99+ is not a balance."""
    from .pause_tabs import pause_tab_steps
    frame = getattr(obs, 'frame', None)
    if (frame is None or frame.shape != (1080,1920,3) or obs.screen != 'pause_menu'
            or not isinstance(gamertag,str) or not gamertag.strip()
            or pause_tab_steps(obs,'CARS') is None):
        return None
    doc = obs.doc
    accounts=doc.find(gamertag,ACCOUNT_BOX,contains=True)
    if len(accounts)!=1 or not _inside(accounts[0],ACCOUNT_BOX):
        return None
    if not all(len(doc.find(label,FOOTER_BOX))==1 for label in ('Enter','Select','Back')):
        return None
    if any(doc.has(label,contains=True) for label in ('Time Remaining','Time Left','Time Limit',
            'Challenge Time','Quit Event','Restart Event','Yes','No','Cancel','Confirm','Synchronizing','Syncing')):
        return None
    box=(738,170,40,40)
    lines=[line for line in doc.lines if _inside(line,box)]
    if len(lines)!=1 or re.fullmatch(r'(?:0|[1-9]\d?)',lines[0].text.strip()) is None:
        return None
    patch=frame[170:210,738:778]
    yellow=cv2.inRange(cv2.cvtColor(patch,cv2.COLOR_BGR2HSV),(18,90,130),(45,255,255))
    if cv2.countNonZero(yellow)<150:
        return None
    crop=cv2.resize(patch,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
    crop=cv2.copyMakeBorder(crop,12,12,12,12,cv2.BORDER_REPLICATE)
    local=reader.read(crop)
    if len(local.lines)!=1 or local.lines[0].text.strip()!=lines[0].text.strip():
        return None
    return int(lines[0].text.strip())


def _inside(line, box):
    x, y, w, h = line.box
    rx, ry, rw, rh = box
    return w > 0 and h > 0 and rx <= x and ry <= y and x+w <= rx+rw and y+h <= ry+rh


def read_menu_sp(reader, obs, gamertag):
    """Return one frame's corroborated 0..999 SP, or None on missing evidence.

    Requires the exact selected Cars tab/title, an identified native account,
    the pause footer, and the full labeled balance inside the Car Mastery tile.
    Existing menu OCR and one enlarged native label crop must agree exactly.
    """
    frame = getattr(obs, 'frame', None)
    if (frame is None or frame.shape != (1080, 1920, 3)
            or not isinstance(gamertag, str) or not gamertag.strip()
            or target_title(obs) is None):
        return None
    doc = obs.doc
    accounts = doc.find(gamertag, ACCOUNT_BOX, contains=True)
    if len(accounts) != 1 or not _inside(accounts[0], ACCOUNT_BOX):
        return None
    if not all(len(doc.find(label, FOOTER_BOX)) == 1 for label in ('Enter', 'Select', 'Back')):
        return None
    if any(doc.has(label, contains=True) for label in (
            'Time Remaining', 'Time Left', 'Time Limit', 'Challenge Time',
            'Retry', 'Quit Event', 'Restart Event', 'Yes', 'No', 'Cancel',
            'Confirm', 'Synchronizing', 'Syncing', 'Insufficient Credits')):
        return None
    labels = [line for line in doc.lines if _inside(line, SP_BOX)]
    # A clipped/duplicate/unexpected line in this small native label area must
    # not be ignored in favor of whichever numeric sample happens to parse.
    if len(labels) != 1:
        return None
    first = SP_LABEL.fullmatch(labels[0].text.strip())
    if first is None:
        return None
    x, y, w, h = SP_BOX
    crop = cv2.resize(frame[y:y+h, x:x+w], None, fx=2, fy=2,
                      interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, 10, 10, 10, 10, cv2.BORDER_REPLICATE)
    local = reader.read(crop)
    if not isinstance(local.lines, list) or len(local.lines) != 1:
        return None
    second = SP_LABEL.fullmatch(local.lines[0].text.strip())
    if second is None or int(first[1]) != int(second[1]):
        return None
    return int(first[1])


def verify_menu_sp(nav, gamertag, *, timeout=2.5, clock=time.monotonic):
    """Read two distinct current frames; return SP or None without navigation.

    Call only after navigating to the paused Cars tab. All input, sync, display
    and focus guards remain current. The single process identity is pinned for
    this bounded read and must match the current sync proof. No mastery-ready
    token is created, and callers must not replace None with an estimated SP.
    """
    if not 0 < timeout <= 5:
        raise ValueError('Menu SP verification timeout must be in (0, 5] seconds')
    deadline = clock() + timeout
    provider = getattr(getattr(nav, 'setup_checks', None), 'identity', None)
    sync = getattr(nav, 'sync_guard', None)
    if not callable(provider) or not callable(getattr(sync, 'require_verified', None)):
        return None

    def identity():
        value = provider()
        if (not isinstance(value, (list, tuple)) or len(value) != 1
                or not isinstance(value[0], str) or not value[0]):
            raise RuntimeError('Current game identity unavailable for menu SP reading')
        return tuple(value)

    nav.check()
    pinned = identity()
    sync.require_verified(pinned)
    generation = getattr(nav, 'focus_generation', None)
    if type(generation) is not int:
        return None
    previous, previous_points = None, None
    while clock() < deadline:
        obs = nav.observe()
        if clock() >= deadline:
            return None
        if (nav.last is not obs or nav.focus_generation != generation
                or getattr(obs, 'focus_generation', None) != generation):
            return None
        points = read_menu_sp(nav.reader, obs, gamertag)
        if points is None:
            points = read_tab_sp(nav.reader, obs, gamertag)
        if clock() >= deadline:
            return None
        if (points is not None and previous_points == points and previous is not None
                and obs is not previous and obs.frame is not previous.frame):
            nav.check()
            if identity() != pinned:
                raise RuntimeError('Game changed while reading menu SP')
            sync.require_verified(pinned)
            nav.check()
            if (clock() >= deadline or nav.last is not obs
                    or nav.focus_generation != generation):
                return None
            return points
        previous, previous_points = obs, points
        remaining = deadline-clock()
        if remaining > 0:
            nav.pause(min(.04, remaining))
    return None
