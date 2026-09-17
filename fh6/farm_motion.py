"""Conservative native speedometer evidence for prolonged stationary farming."""
import re
import cv2
from .ocr import normalize


# Native 1920x1080 speed digits. This excludes the gear, tachometer, GPU
# overlay and KM/H label; the challenge countdown is proved separately before
# this crop is read.
SPEED_DIGITS = (1700, 925, 190, 130)
# Native gameplay region above the car and away from every HUD element.  The
# long Mega tunnel gives a very strong frame-to-frame signal while driving.
MOTION_SCENE = (450, 180, 1020, 500)


def anti_afk_interval(profile):
    """Use the observed stable Mega refresh cadence without changing profiles.

    Current community guidance requires a steering movement in less than five
    minutes, while this operation's costly low-yield attempts make a wider
    guard worthwhile. Three minutes adds only two 150 ms pulses to a full run.
    Other challenge profiles retain their calibrated cadence.
    """
    configured = float(profile.movement_interval)
    return min(configured, 180.) if profile.share_code == '155439962' else configured


def speed_from_document(doc):
    # Coordinates are local to the 1640,890,270,160 native HUD crop.
    if not any(normalize(line.text) in {'km h', 'kmh'} and line.center[1] < 60
               for line in doc.lines):
        return None
    candidates = [line for line in doc.lines if line.center[1] >= 60
                  and line.box[2] >= 60]
    if len(candidates) != 1 or re.fullmatch(r'[0-9]{1,3}', candidates[0].text.strip()) is None:
        return None
    return int(candidates[0].text.strip())


def _digits_from_document(doc):
    values = [line.text.strip() for line in doc.lines
              if re.fullmatch(r'[0-9]{1,3}', line.text.strip())]
    return int(values[0]) if len(values) == 1 else None


def speed_from_frame(reader, frame):
    """Read the low-contrast native speed digits with two agreeing masks.

    Windows OCR cannot normally see Forza's translucent speedometer. Two
    nearby binary thresholds make it legible while requiring independent
    agreement before the value can contribute to a stationary-run exit.
    """
    if frame is None or getattr(frame, 'shape', (0, 0))[:2] != (1080, 1920):
        return None
    x, y, w, h = SPEED_DIGITS
    gray = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
    values = []
    for threshold in (200, 210):
        _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        values.append(_digits_from_document(reader.read(
            cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR))))
    return values[0] if values[0] is not None and values[0] == values[1] else None


def scene_is_moving(previous, current):
    """Return conservative visual motion evidence, or None for bad frames.

    This is a fallback for translucent speed digits that Windows OCR can miss.
    It deliberately recognizes motion rather than trying to infer an exact
    speed.  A stationary result is never enough on its own: StationaryWatch
    still requires five ordered samples spanning at least 30 seconds.
    """
    if (previous is None or current is None or
            getattr(previous, 'shape', (0, 0))[:2] != (1080, 1920) or
            getattr(current, 'shape', (0, 0))[:2] != (1080, 1920)):
        return None
    x, y, w, h = MOTION_SCENE
    samples = []
    for frame in (previous, current):
        gray = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
        samples.append(cv2.GaussianBlur(gray, (5, 5), 0))
    delta = cv2.absdiff(*samples)
    # Live moving samples are normally >35% changed pixels.  Six percent is a
    # deliberately wide floor for lighting/compression noise on a stopped car.
    return float((delta > 5).mean()) >= .06


class StationaryWatch:
    def __init__(self):
        self.since = self.last = None
        self.samples = 0

    def observe(self, speed, elapsed, now):
        if (speed != 0 or elapsed < 45 or self.last is not None and
                (now <= self.last or now-self.last > 12)):
            self.since = self.last = None
            self.samples = 0
            return False
        if self.since is None:
            self.since = now
        self.last = now
        self.samples += 1
        return self.samples >= 5 and now-self.since >= 30
