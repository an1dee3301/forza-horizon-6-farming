"""Portable offline checks for the read-only delivery route helper."""

import cv2
import numpy as np
import pytest

from fh6.delivery_route import RouteProgressTracker, route_cue


def delivery_frame(bend=0, *, hud=True, route=True, anchor_x=960):
    """Draw a shift HUD and a cyan road chevron trail without game images."""
    frame = np.full((1080, 1920, 3), (65, 65, 65), dtype=np.uint8)
    if hud:
        cv2.rectangle(frame, (50, 50), (360, 160), (20, 20, 20), -1)
        cv2.putText(frame, '05:13.113', (248, 151), cv2.FONT_HERSHEY_SIMPLEX,
                    .7, (0, 220, 245), 2, cv2.LINE_AA)
    if route:
        for y in range(485, 315, -12):
            x = anchor_x + round(bend * (485 - y) * .7)
            chevron = np.array([[x - 15, y - 6], [x, y + 4],
                                [x + 15, y - 6]], dtype=np.int32)
            cv2.polylines(frame, [chevron], False, (190, 150, 55),
                          8, cv2.LINE_AA)
    return frame


@pytest.mark.parametrize(('bend', 'turn'), [
    (-1, 'left'), (0, 'straight'), (1, 'right'),
])
def test_visible_chevrons_give_bounded_cue(bend, turn):
    cue = route_cue(delivery_frame(bend))
    assert cue is not None
    assert cue.confidence >= .65
    assert cue.turn == turn
    assert -.5 <= cue.steer <= .5
    assert len(cue.route_points) >= 5


def test_hidden_hud_keeps_visible_route_but_missing_route_or_anchor_fails():
    assert route_cue(delivery_frame(hud=False)) is not None
    assert route_cue(delivery_frame(route=False)) is None
    assert route_cue(delivery_frame(anchor_x=600)) is None


def test_offset_but_continuous_route_can_steer_back_toward_lane():
    cue = route_cue(delivery_frame(anchor_x=808))
    assert cue is not None
    assert cue.confidence >= .75
    assert cue.steer < 0


def test_broad_cyan_scene_is_not_a_route():
    frame = delivery_frame(route=False)
    cv2.rectangle(frame, (650, 310), (1269, 509), (190, 150, 55), -1)
    assert route_cue(frame) is None


def test_solid_cyan_pillar_is_not_a_chevron_trail():
    frame = delivery_frame(route=False, hud=False)
    cv2.rectangle(frame, (940, 310), (1020, 510), (190, 150, 55), -1)
    assert route_cue(frame) is None


def test_half_resolution_retains_input_pixel_coordinates():
    half = cv2.resize(delivery_frame(-1), (960, 540),
                      interpolation=cv2.INTER_AREA)
    cue = route_cue(half)
    assert cue is not None
    assert 300 < cue.target_x < 500
    assert all(0 <= x < 960 and 0 <= y < 540 for x, y in cue.route_points)


def test_progress_tracker_requires_sustained_zero_speed_and_valid_readings():
    tracker = RouteProgressTracker(stall_after_s=7)
    assert not tracker.observe(2400, 8, now=0).stalled
    assert not tracker.observe(2400, 0, now=2).stalled
    assert tracker.observe(2400, 0, now=9).stalled
    moving = tracker.observe(2300, 15, now=10)
    assert moving.progress_m == 100
    assert not moving.stalled
    assert not tracker.observe(None, 0, now=20).stalled
