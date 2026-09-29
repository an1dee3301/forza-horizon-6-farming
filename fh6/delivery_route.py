"""Read-only route cues from Tokyo delivery screenshots.

The blue chevrons drawn on the road are the only steering source here.  A
short, continuous trail must start close to the vehicle before this module
returns a cue.  Missing or ambiguous chevrons yield ``None``; the caller must
neutralize the controller in that case.  This module never reads or writes game
state and never sends input.
"""

from dataclasses import dataclass
import math
import time

import cv2
import numpy as np


_WIDTH = 1920
_HEIGHT = 1080
_CAR_X = 960
_ROI_X = 650
_ROI_Y = 310
_ROI_WIDTH = 620
_ROI_HEIGHT = 200
_SAMPLE_YS = range(500, 319, -12)
_SMOOTH = np.ones(32, dtype=np.float32)


@dataclass(frozen=True)
class RouteCue:
    """Conservative signed steering hint for one active delivery frame."""

    steer: float
    confidence: float
    target_x: float
    turn: str
    turn_urgency: str
    route_points: tuple[tuple[int, int], ...]


def _road_mask(frame):
    road = frame[_ROI_Y:_ROI_Y + _ROI_HEIGHT,
                 _ROI_X:_ROI_X + _ROI_WIDTH]
    hsv = cv2.cvtColor(road, cv2.COLOR_BGR2HSV)
    # The game's cyan racing line has a stable blue/cyan hue across the saved
    # night, dusk and snowy daytime delivery frames.  Saturation rejects most
    # grey road markings and snow.
    return cv2.inRange(hsv, (85, 60, 50), (112, 255, 255))


def _route_points(mask):
    points = []
    previous_x = None
    missing = 0
    for y in _SAMPLE_YS:
        local_y = y - _ROI_Y
        counts = np.count_nonzero(mask[local_y - 6:local_y + 6], axis=0)
        scores = np.convolve(counts.astype(np.float32), _SMOOTH, mode='same')
        center = _CAR_X if previous_x is None else previous_x
        radius = 160 if previous_x is None else 70
        left = max(_ROI_X, center - radius)
        right = min(_ROI_X + _ROI_WIDTH, center + radius + 1)
        if left >= right:
            break
        candidate_xs = np.arange(left, right)
        candidate_scores = scores[left - _ROI_X:right - _ROI_X]
        preference = candidate_scores - .5 * np.abs(candidate_xs - center)
        index = int(np.argmax(preference))
        x = int(candidate_xs[index])
        if candidate_scores[index] < 30:
            if previous_x is not None:
                missing += 1
                if missing >= 3:
                    break
            continue
        points.append((x, y))
        previous_x = x
        missing = 0
    return tuple(points)


def route_cue(frame) -> RouteCue | None:
    """Estimate the road-route bend from a BGR frame, or return no safe cue.

    ``steer`` is bounded to [-0.5, 0.5]; negative means left.  ``target_x``
    and ``route_points`` use the input frame's pixel coordinates.  This is a
    visual hint, not a collision or road-boundary detector, so an active-drive
    runner must still enforce speed, progress and visibility checks.
    """
    if (not isinstance(frame, np.ndarray) or frame.ndim != 3 or
            frame.shape[2] != 3 or frame.dtype != np.uint8):
        return None
    height, width = frame.shape[:2]
    if height < 540 or width < 960 or abs(width / height - 16 / 9) >= .04:
        return None
    normalized = frame if (width, height) == (_WIDTH, _HEIGHT) else cv2.resize(
        frame, (_WIDTH, _HEIGHT), interpolation=cv2.INTER_AREA)
    # The timed job hides its HUD after some menu transitions. The runner
    # verifies the native active screen and delivery prompt before using a cue.
    mask = _road_mask(normalized)
    # Bright snow and teal UI art can share the chevron hue.  A genuine route
    # is a narrow trail, never a quarter of the whole road crop.
    if float(np.mean(mask > 0)) > .35:
        return None
    points = _route_points(mask)
    if len(points) < 5 or points[0][1] - points[-1][1] < 60:
        return None
    # A cyan wall or pillar can form a smooth, high-confidence vertical path.
    # Chevron strokes leave dark gaps in a small patch around each sample;
    # a solid surface fills nearly the whole patch across many rows.
    broad_rows = 0
    for x, y in points:
        row = mask[y - _ROI_Y]
        center = x - _ROI_X
        if row[center] == 0:
            continue
        left = center
        right = center
        while left > 0 and row[left - 1]:
            left -= 1
        while right + 1 < len(row) and row[right + 1]:
            right += 1
        if right - left + 1 > 65:
            broad_rows += 1
    if broad_rows >= max(3, len(points) // 4):
        return None

    near_x = sum(x for x, _ in points[:3]) / min(3, len(points))
    far_x = sum(x for x, _ in points[-2:]) / 2
    raw_steer = .42 * (far_x - _CAR_X) / 260 + .58 * (far_x - near_x) / 280
    steer = float(np.clip(raw_steer, -.5, .5))

    span = points[0][1] - points[-1][1]
    support = min(1., len(points) / 10)
    reach = min(1., span / 120)
    anchor = max(0., 1 - abs(points[0][0] - _CAR_X) / 300)
    steps = [abs(points[i][0] - points[i - 1][0]) for i in range(1, len(points))]
    smoothness = max(0., 1 - float(np.median(steps)) / 70)
    confidence = float(np.clip(.35 * support + .35 * reach +
                               .2 * anchor + .1 * smoothness, 0, 1))

    if steer < -.075:
        turn = 'left'
    elif steer > .075:
        turn = 'right'
    else:
        turn = 'straight'
    # A single bright object can fall inside the search corridor.  Require a
    # bend to be visible in a pair of adjacent sampled chevrons.
    smoothed_x = [float(np.median([p[0] for p in points[max(0, i - 1):i + 2]]))
                  for i in range(len(points))]
    bend_y = next(((points[i][1] + points[i + 1][1]) // 2
                   for i in range(len(points) - 1)
                   if abs((smoothed_x[i] + smoothed_x[i + 1]) / 2 - near_x) >= 40),
                  None)
    if turn == 'straight':
        urgency = 'none'
    elif bend_y is None:
        urgency = 'later'
    elif bend_y >= 400:
        urgency = 'now'
    elif bend_y >= 330:
        urgency = 'soon'
    else:
        urgency = 'later'

    scale = width / _WIDTH
    return RouteCue(steer=steer, confidence=confidence,
                    target_x=far_x * scale, turn=turn,
                    turn_urgency=urgency,
                    route_points=tuple((round(x * scale), round(y * height / _HEIGHT))
                                       for x, y in points))


@dataclass(frozen=True)
class ProgressReport:
    distance_m: float | None
    speed_kmh: float | None
    progress_m: float
    no_progress_s: float
    stalled: bool


class RouteProgressTracker:
    """Track measured destination progress and a sustained zero-speed stall.

    The caller supplies OCR readings.  Coarse kilometre displays are allowed:
    a stationary vehicle is marked stalled after repeated zero-speed readings
    even if the displayed distance has not changed.  Missing readings never
    produce a stall claim.
    """

    def __init__(self, stall_after_s: float = 7):
        if not math.isfinite(stall_after_s) or stall_after_s <= 0:
            raise ValueError('stall_after_s must be positive')
        self.stall_after_s = stall_after_s
        self.first_distance = None
        self.best_distance = None
        self.last_progress_at = None
        self.stopped_since = None

    def observe(self, distance_m: float | None, speed_kmh: float | None,
                now: float | None = None) -> ProgressReport:
        now = time.monotonic() if now is None else float(now)
        valid_distance = (distance_m is not None and math.isfinite(distance_m)
                          and distance_m >= 0)
        valid_speed = (speed_kmh is not None and math.isfinite(speed_kmh)
                       and speed_kmh >= 0)
        if not valid_distance or not valid_speed:
            self.stopped_since = None
            return ProgressReport(distance_m if valid_distance else None,
                                  speed_kmh if valid_speed else None,
                                  max(0., (self.first_distance or 0) -
                                      (self.best_distance or 0)), 0., False)

        distance_m, speed_kmh = float(distance_m), float(speed_kmh)
        if self.first_distance is None:
            self.first_distance = self.best_distance = distance_m
            self.last_progress_at = now
        elif distance_m < self.best_distance - 1:
            self.best_distance = distance_m
            self.last_progress_at = now
        if speed_kmh <= 2:
            if self.stopped_since is None:
                self.stopped_since = now
        else:
            self.stopped_since = None
        no_progress_s = max(0., now - self.last_progress_at)
        stalled = (self.stopped_since is not None and
                   now - self.stopped_since >= self.stall_after_s and
                   no_progress_s >= self.stall_after_s)
        return ProgressReport(distance_m, speed_kmh,
                              max(0., self.first_distance - self.best_distance),
                              no_progress_s, stalled)
