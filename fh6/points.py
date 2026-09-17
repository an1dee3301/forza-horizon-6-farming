"""Read the visible SP balance using agreeing enlarged crops."""
import re
import time
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from forza_cycle import crop

MASTERY_POINTS = (675, 922, 65, 31)
ZERO_TEMPLATE = Path(__file__).resolve().parent.parent/'recognition'/'sp_zero.png'


@dataclass(frozen=True)
class VerifiedSP:
    points: int
    observation: object
    ready: object
    observed_at: float


def recent_sp(nav):
    """Hand off a twice-read balance before any new input or observation.

    This proof is process-local and expires after 750ms. Navigation invalidates
    its ready token on input, capture or focus restoration. No saved balance,
    estimated gain or historical observation can create this proof.
    """
    proof = getattr(nav, '_verified_sp', None)
    if not isinstance(proof, VerifiedSP) or getattr(nav, 'fast_navigation', False) is not True:
        return None
    if not 0 <= time.monotonic()-proof.observed_at <= .75:
        return None
    nav.check()
    if (not 0 <= time.monotonic()-proof.observed_at <= .75 or
            getattr(nav, '_ready', None) is not proof.ready or
            getattr(nav, 'last', None) is not proof.observation):
        return None
    return proof


def remember_sp(nav, points):
    """Called only after agreeing SP reads from two fresh mastery frames."""
    ready = getattr(nav, '_ready', None)
    obs = getattr(nav, 'last', None)
    if (type(points) is int and 0 <= points <= 999 and isinstance(ready, tuple) and
            len(ready) == 2 and ready[0] is obs and
            obs.screen in {'car_mastery', 'mad_mike_mastery'}):
        nav._verified_sp = VerifiedSP(points, obs, ready, ready[1])


def _context_readings(reader, frame):
    """Keep the label and digits together, without the icon or Cost row."""
    context = crop(frame, (320, 918, 420, 40))
    readings = []
    for scale in (2, 3, 4, 5):
        sample = cv2.resize(context, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        sample = cv2.copyMakeBorder(sample, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
        text = ' '.join(line.text.strip() for line in reader.read(sample).lines).strip()
        match = re.fullmatch(r'Available Points\s+([0-9]{1,3})', text, re.IGNORECASE)
        # Preserve failed samples so recovery cannot mistake two matching
        # context readings plus two unreadable ones for four confirmations.
        readings.append(int(match[1]) if match else None)
    return readings


def _normalise_digit(mask):
    ys, xs = np.where(mask > 0)
    if not len(xs):
        return None
    glyph = mask[ys.min():ys.max()+1, xs.min():xs.max()+1]
    scale = min(24/glyph.shape[1], 32/glyph.shape[0])
    glyph = cv2.resize(glyph, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((36, 28), dtype=np.uint8)
    y, x = (36-glyph.shape[0])//2, (28-glyph.shape[1])//2
    canvas[y:y+glyph.shape[0], x:x+glyph.shape[1]] = glyph
    return canvas


@lru_cache(maxsize=1)
def _zero_template():
    value = cv2.imread(str(ZERO_TEMPLATE), cv2.IMREAD_GRAYSCALE)
    return value if value is not None and value.shape == (36, 28) else None


def _opencv_zero(frame, box):
    """Recognize the native single zero that Windows OCR consistently drops."""
    if box != MASTERY_POINTS or frame is None or frame.shape[:2] != (1080, 1920):
        return False
    region = crop(frame, box)
    mask = cv2.inRange(cv2.cvtColor(region, cv2.COLOR_BGR2HSV),
                       (20, 110, 140), (45, 255, 255))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    components = [tuple(map(int, stat)) for stat in stats[1:] if stat[4] >= 20]
    if len(components) != 1:
        return False
    x, y, w, h, area = components[0]
    if not (12 <= w <= 18 and 17 <= h <= 22 and 120 <= area <= 220):
        return False
    actual, expected = _normalise_digit(mask[y:y+h, x:x+w]), _zero_template()
    if actual is None or expected is None:
        return False
    union = np.logical_or(actual > 0, expected > 0).sum()
    return bool(union and np.logical_and(actual > 0, expected > 0).sum()/union >= .90)


def read_points(reader, frame, box=MASTERY_POINTS):
    region = crop(frame, box)
    enlarged = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    yellow = cv2.inRange(cv2.cvtColor(region, cv2.COLOR_BGR2HSV), (20, 110, 140), (45, 255, 255))
    mono = cv2.cvtColor(255 - yellow, cv2.COLOR_GRAY2BGR)
    mono = cv2.resize(mono, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    readings = []
    enlarged2 = cv2.resize(region, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    enlarged3 = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # Native digits are only about 19 pixels tall. Windows OCR can misread
    # 243 as 713 at that size despite agreeing enlarged readings. Keep every
    # numeric sample enlarged; disagreements still invalidate the balance.
    samples = []
    for sample in (enlarged, enlarged2, mono, enlarged3):
        sample = cv2.copyMakeBorder(sample, 30, 30, 30, 30, cv2.BORDER_REPLICATE)
        doc = reader.read(sample)
        text = ' '.join(line.text.strip() for line in doc.lines).strip()
        value = int(text) if re.fullmatch(r'[0-9]{1,3}', text) else None
        samples.append(value)
        if value is not None:
            readings.append(value)
    counts = Counter(readings)
    isolated_mask = (samples[0] is not None and samples[0] == samples[1] == samples[3]
                     and samples[2] is not None and samples[2] != samples[0])
    isolated_3x = (samples[0] is not None and samples[0] == samples[1] == samples[2]
                   and samples[3] is not None and samples[3] != samples[0])
    isolated_4x = (samples[1] is not None and samples[1] == samples[2] == samples[3]
                   and samples[0] is not None and samples[0] != samples[1])
    isolated_4x_missing_mask = (
        samples[1] is not None and samples[1] == samples[3]
        and samples[2] is None and samples[0] is not None
        and samples[0] != samples[1])
    if (box == MASTERY_POINTS and len(counts) == 2
            and (isolated_mask or isolated_3x or isolated_4x or isolated_4x_missing_mask)):
        # Recorded transformed-crop errors: mask 806 -> 606, 3x 965 -> 966,
        # 4x 945 -> 946, and 4x 796 -> 196 with an unreadable mask. The last pattern has
        # only two numeric confirmations, so it must also be corroborated
        # by EVERY full "Available Points <value>" crop at four scales.
        # This is contextual proof, not a numeric-majority fallback. Other
        # disagreement patterns still reject; callers retain fresh-frame
        # checks because these transforms all originate in one frame.
        expected = samples[1] if (isolated_4x or isolated_4x_missing_mask) else samples[0]
        context = _context_readings(reader, frame)
        if all(value == expected for value in context):
            return expected
        raise RuntimeError('Could not reliably read the available skill-point total: '
                           f'conflicting SP readings were not confirmed by all labeled crops; numeric samples={samples}, labeled samples={context}')
    if box == MASTERY_POINTS and len(counts) <= 1 and len(readings) < 2:
        # Short balances such as 51 can disappear from OCR's text detector
        # when cropped to digits alone. Keep the adjacent label for context,
        # excluding the currency icon and the separate Cost row entirely.
        readings.extend(value for value in _context_readings(reader, frame) if value is not None)
        counts = Counter(readings)
    if not readings and _opencv_zero(frame, box):
        # Zero is a valid balance and is re-read from a second fresh mastery
        # frame by available_sp(). Never infer it from spending arithmetic.
        return 0
    if len(counts) != 1 or next(iter(counts.values()), 0) < 2:
        raise RuntimeError(f'Could not reliably read the available skill-point total: numeric samples (4x/2x/mask/3x)={samples}')
    return readings[0]
