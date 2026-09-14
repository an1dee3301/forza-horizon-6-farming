"""Verify the farm's frame-rate cap without changing its calibrated layout."""
import re

from .navigation import LEFT, label_focused

ROWS = (450, 210, 1000, 520)
MAX_STABLE_FPS = 45
MIN_NEAR_TARGET_FPS = 40


def frame_rate(doc):
    labels = doc.find('Frame Rate', ROWS)
    if len(labels) != 1 or not doc.has('Resolution', ROWS):
        return None
    y = labels[0].center[1]
    values = []
    for line in doc.lines:
        if 1000 < line.center[0] < 1450 and abs(line.center[1]-y) < 22:
            match = re.fullmatch(r'(\d+)\s*FPS', line.text.strip(), re.I)
            if match:
                values.append(int(match[1]))
    return values[0] if len(values) == 1 else None


def verify_frame_rate(nav):
    nav.select('Video', LEFT)
    obs = nav.until(lambda o: frame_rate(o.doc) is not None, 'video frame-rate setting')
    initial = value = frame_rate(obs.doc)
    if not MIN_NEAR_TARGET_FPS <= value <= MAX_STABLE_FPS:
        nav.select('Frame Rate', ROWS)
        # FH6 derives this list from the monitor refresh rate. On this 170 Hz
        # display 57 FPS still held the unsupported GTX 1060 at 94-99% GPU, so
        # use the next offered step (43 FPS) to preserve crash headroom.
        # Every change still requires a positively identified, focused row and
        # a visible move toward the safe interval.
        for _ in range(8):
            if MIN_NEAR_TARGET_FPS <= value <= MAX_STABLE_FPS:
                break
            obs = nav.until(lambda o: frame_rate(o.doc) == value and
                            label_focused(o.frame, o.doc.unique('Frame Rate', ROWS)),
                            'focused frame-rate row')
            direction='right' if value<MIN_NEAR_TARGET_FPS else 'left'
            nav.key(direction)
            old=value
            obs = nav.until(lambda o: frame_rate(o.doc) is not None and
                            ((direction=='right' and frame_rate(o.doc)>old) or
                             (direction=='left' and frame_rate(o.doc)<old)),
                            'frame-rate setting moving toward 60 FPS')
            value = frame_rate(obs.doc)
        else:
            raise RuntimeError('Could not reach the crash-safe FPS cap; farm was not launched')
        if not MIN_NEAR_TARGET_FPS <= value <= MAX_STABLE_FPS:
            raise RuntimeError('Could not reach the crash-safe FPS cap; farm was not launched')
        nav.until(lambda o: frame_rate(o.doc) == value and
                  o.doc.has('Save', (400, 970, 250, 70), contains=True), 'video Save action')
        nav.key('space')
        nav.until(lambda o: frame_rate(o.doc) == value and
                  not o.doc.has('Save', (400, 970, 250, 70), contains=True), 'saved frame-rate setting')
    nav.key('esc')
    nav.until(lambda o: frame_rate(o.doc) == value and o.doc.has('Difficulty'),
              'persisted video setting')
    nav.emit('log', f'Verified stable frame-rate cap: {value} FPS (was {initial}; ceiling {MAX_STABLE_FPS})')
