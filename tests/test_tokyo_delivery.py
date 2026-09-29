"""Portable checks for the checkpointed Tokyo job runner."""

import json
from pathlib import Path
from types import SimpleNamespace
import threading

import cv2
import numpy as np
import pytest

from fh6.ocr import Document, Text
from fh6.tokyo_delivery import (
    _prompt_stage,
    DeliveryObservation,
    DeliveryEvidenceUncertain,
    DeliveryInputUncertain,
    MAX_PARKING_BRAKES,
    MAX_PARKING_NUDGES,
    TokyoDelivery,
    auto_drive_needs_route,
    auto_drive_off,
    auto_drive_on,
    classify_screen,
    delivery_remaining_seconds,
    distance_from_lines,
    guided_route_action,
    job_icon_candidates,
    job_progress_from_lines,
    plaza_egress_allowed,
    shift_progress_from_lines,
    shift_stars_from_lines,
)


def line(value, x=100, y=100):
    return Text(value, (x, y, 80, 24))


def test_delivery_timer_accepts_missing_colon_only_on_labeled_timer_row():
    doc = Document([
        line("Time Remaining:", 80, 55),
        line("0137.876", 260, 55),
        line("0100.000", 260, 95),
        line("00:22.124", 260, 130),
    ])
    assert delivery_remaining_seconds(doc) == pytest.approx(97.876)
    assert delivery_remaining_seconds(Document(doc.lines[1:])) is None


def observation(screen, *, distance=None, remaining=None, prompt="",
                stars=None, progress=None, shift_progress=None,
                failed=False, doc=None):
    return DeliveryObservation(
        screen=screen,
        native=SimpleNamespace(frame=np.zeros((1080, 1920, 3), dtype=np.uint8)),
        doc=doc if doc is not None else Document([]),
        distance_m=distance,
        remaining_s=remaining,
        prompt=prompt,
        progress=progress,
        shift_stars=stars,
        shift_progress=shift_progress,
        failed=failed,
    )


class FakeNav:
    reader = object()

    def __init__(self):
        self.checks = 0
        self.keys = []

    def check(self):
        self.checks += 1

    def pause(self, seconds):
        pass

    def key(self, name):
        self.keys.append(name)


class FakePad:
    def __init__(self, runner):
        self.runner = runner
        self.drives = []
        self.pulses = []
        self.neutrals = 0

    def check(self):
        pass

    def drive(self, throttle, steer, seconds):
        self.drives.append((throttle, steer, seconds,
                            self.runner.data["drive_steps"]))

    def pulse(self, name, seconds=0.1):
        self.pulses.append(name)

    def neutral(self):
        self.neutrals += 1


def runner(tmp_path):
    result = TokyoDelivery(FakeNav(), threading.Event(), root=tmp_path)
    result._load(1)
    result.pad = FakePad(result)
    return result


class ManualClock:
    def __init__(self):
        self.value = 0.

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def timed_runner(tmp_path):
    clock = ManualClock()
    nav = FakeNav()
    nav.pause = clock.advance
    result = TokyoDelivery(nav, threading.Event(), root=tmp_path, clock=clock)
    result._load(1)
    result.pad = FakePad(result)
    return result, clock


@pytest.mark.parametrize(("label", "metres"), [
    ("1.2 KM", 1200),
    ("2.9 KM", 2900),
    ("0378M", 378),
    ("a 123M", 123),
])
def test_native_distance_crop_variants(label, metres):
    assert distance_from_lines([line(label)]) == metres


def test_distance_and_progress_need_unambiguous_native_values():
    assert distance_from_lines([line("1.2 KM"), line("2.9 KM")]) is None
    assert distance_from_lines([line("99999 KM")]) is None
    assert job_progress_from_lines([line("10,800 / 25,000")]) == 10800
    assert job_progress_from_lines([line("800 / 25,000")]) is None


def test_stage_detection_uses_native_labels_and_screen_regions():
    active = Document([line("Time Remaining", 70, 55)])
    summary = Document([line("Job Summary", 80, 220),
                        line("Shift Progress", 90, 355)])
    solo = Document([line("Tokyo City Food Delivery", 80, 270),
                     line("Solo", 80, 690)])
    job_map = Document([line("Close Map", 150, 970),
                        line("Fast Travel", 370, 970)])
    job_journal = Document([line("Junior Delivery Driver", 140, 410),
                            line("Seasoned Delivery Driver", 480, 660),
                            line("Back", 245, 985)])
    assert classify_screen(active, is_roam=True) == "active"
    assert classify_screen(summary) == "summary"
    assert classify_screen(solo) == "solo"
    assert classify_screen(job_map) == "map"
    assert classify_screen(job_journal) == "job_journal"
    assert classify_screen(Document([]), native_screen="journal") == "journal"
    assert classify_screen(Document([]), native_screen="pause_menu") == "pause_menu"


def test_campaign_drive_menu_is_home_even_if_generic_roam_detector_fires():
    campaign = Document([
        line("Campaign", 266, 257),
        line("Drive", 116, 728),
        line("Collection Journal", 175, 782),
    ])
    assert classify_screen(campaign, is_roam=True) == "home"


def test_controller_reconnect_modal_requires_three_native_regions():
    from fh6.game_lifecycle import controller_disconnected_modal

    title = line("Controller Disconnected", 920, 492)
    body = line("Please reconnect a controller.", 920, 564)
    footer = line("Enter", 66, 994)
    modal = Document([title, body, footer])
    assert controller_disconnected_modal(modal)
    assert classify_screen(modal) == "controller_disconnected"
    assert controller_disconnected_modal(Document([
        title, body, line("0k", 116, 996)]))
    assert not controller_disconnected_modal(Document([title, body]))
    assert not controller_disconnected_modal(Document([
        title, body, line("Enter", 920, 994)]))


def test_lifecycle_accepts_stable_reconnect_modal_without_startup_key(
        monkeypatch, tmp_path):
    import fh6.game_lifecycle as lifecycle_module

    clock = ManualClock()
    doc = Document([line("Controller Disconnected", 920, 492),
                    line("Please reconnect a controller.", 920, 564),
                    line("Enter", 66, 994)])
    observed = SimpleNamespace(screen="unknown", doc=doc,
                               frame=np.zeros((1080, 1920, 3), dtype=np.uint8))

    class Game:
        def pids(self):
            return [1]

        def crashed(self):
            return False

        def identity(self):
            return ["1:created"]

    class Nav(FakeNav):
        title = "Forza Horizon 6"

        def observe(self):
            return observed

        def observe_sync(self):
            return observed

        def is_home(self, _):
            return False

        def is_roam(self, _):
            return False

    monkeypatch.setattr(lifecycle_module.core, "foreground_title",
                        lambda: "Forza Horizon 6")
    nav = Nav()
    nav.pause = clock.advance
    active = threading.Event()
    active.set()
    lifecycle = lifecycle_module.GameLifecycle(
        active, backend=Game(), clock=clock, sleep=clock.advance,
        path=tmp_path / "recovery.json", startup_timeout=5)
    lifecycle.wait_ready(nav, launched=False)
    assert nav.keys == []
    assert clock() == pytest.approx(1)

    class Sync:
        evidence = None

        def block(self, _):
            pass

        def observe_wait_identity(self, _):
            return False

        def visible(self):
            return False

        def observe_completion(self, _):
            pass

        def playable_ui_complete(self, identity, screen):
            assert identity == ["1:created"]
            assert screen == "controller_disconnected"
            self.evidence = "native modal"

        def ready(self):
            return self.evidence is not None

    lifecycle.sync_guard = Sync()
    lifecycle.wait_sync(nav)
    assert nav.keys == []


def test_reconnect_enter_is_reserved_once_without_touching_job_pending(tmp_path):
    result = runner(tmp_path)
    pending = {"action": "solo", "source": "solo",
               "targets": ["intro", "active"], "attempts": 1}
    result._save(pending=pending)
    modal = observation("controller_disconnected")
    active = observation("active", distance=1200, remaining=550)
    seen = iter([modal, active, active])
    result._observe = lambda: next(seen)

    def key(name):
        assert result.pad is not None
        assert result.data["reconnect_intent"] is not None
        assert result.data["pending"] == pending
        result.nav.keys.append(name)

    result.nav.key = key
    reached = result._dismiss_controller_modal(modal)
    assert reached.screen == "active"
    assert result.nav.keys == ["enter"]
    assert result.data["reconnect_intent"] is None
    assert result.data["pending"] == pending
    assert result.data["history"][-1]["kind"] == "CONTROLLER_RECONNECT_VERIFIED"


def test_saved_reconnect_enter_is_never_replayed(tmp_path):
    result, _ = timed_runner(tmp_path)
    result._save(reconnect_intent={"at": "saved"})
    modal = observation("controller_disconnected")
    result._observe = lambda: modal
    with pytest.raises(DeliveryInputUncertain, match="no key repeated"):
        result._dismiss_controller_modal(modal)
    assert result.nav.keys == []
    assert result.data["reconnect_intent"] is not None


def test_shift_stars_accepts_only_the_summary_value_box():
    assert shift_stars_from_lines([line("3", 486, 540),
                                   line("0", 100, 100)]) == 3
    assert shift_stars_from_lines([line("3", 100, 100)]) is None
    assert shift_progress_from_lines([line("1/3")]) == 1
    assert shift_progress_from_lines([line("3/3")]) == 3
    assert shift_progress_from_lines([line("1/2")]) is None


def test_active_timer_value_is_refined_when_full_frame_ocr_loses_colon(tmp_path):
    class Reader:
        def __init__(self):
            self.refined = []

        def refine_region(self, frame, doc, box):
            self.refined.append(box)
            return Document([line("Time Remaining:", 70, 55),
                             line("01:51.879", 250, 55)])

        def read(self, frame):
            return Document([line("123M")])

    class Nav(FakeNav):
        def __init__(self):
            super().__init__()
            self.reader = Reader()

        def observe(self):
            return SimpleNamespace(
                frame=np.zeros((1080, 1920, 3), dtype=np.uint8),
                screen="unknown",
                doc=Document([line("Time Remaining:", 70, 55),
                              line("0151.879", 250, 55)]))

        def is_home(self, native):
            return False

        def is_roam(self, native):
            return False

    result = TokyoDelivery(Nav(), threading.Event(), root=tmp_path)
    result._load(1)
    result.pad = FakePad(result)
    seen = result._observe()
    assert seen.screen == "active"
    assert seen.distance_m == 123
    assert seen.remaining_s == pytest.approx(111.879)
    assert result.nav.reader.refined == [(40, 35, 400, 170),
                                         (85, 930, 600, 100)]


def test_job_icon_square_is_only_a_candidate():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    blue = cv2.cvtColor(np.uint8([[[120, 255, 255]]]),
                        cv2.COLOR_HSV2BGR)[0, 0].tolist()
    frame[500:552, 420:472] = blue
    candidates = job_icon_candidates(frame)
    assert candidates and abs(candidates[0][0] - 445) <= 2
    assert abs(candidates[0][1] - 525) <= 2


def test_map_waits_for_job_tooltip_before_rejecting_icon(monkeypatch, tmp_path):
    import pyautogui
    monkeypatch.setattr("fh6.tokyo_delivery.job_icon_candidates",
                        lambda _: [(445, 521)])
    monkeypatch.setattr(pyautogui, "moveTo", lambda *args, **kwargs: None)
    result = runner(tmp_path)
    result.nav.monitor = {"left": 0, "top": 0}
    elapsed = [0.0]
    result.nav.pause = lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    footer = [line("Close Map", 150, 970), line("Fast Travel", 370, 970)]

    def observe():
        labels = ([line("Tokyo City Food Delivery", 550, 430),
                   line("Job", 550, 510)] if elapsed[0] >= .8 else [])
        return observation("map", doc=Document(footer + labels))

    result._observe = observe
    result._transition = lambda current, **kwargs: current
    result._map_job(observe())
    assert result.data["history"][-1]["kind"] == "MAP_JOB_VERIFIED"


def test_map_verifies_job_from_title_crop_when_full_frame_drops_delivery(
        monkeypatch, tmp_path):
    import pyautogui
    monkeypatch.setattr("fh6.tokyo_delivery.job_icon_candidates",
                        lambda _: [(445, 521)])
    monkeypatch.setattr(pyautogui, "moveTo", lambda *args, **kwargs: None)
    result = runner(tmp_path)
    result.nav.monitor = {"left": 0, "top": 0}

    class Reader:
        def read(self, frame):
            assert frame.shape[:2] == (115, 430)
            return Document([line("Tokyo City Food"), line("Delivery"),
                             line("Job")])

    result.nav.reader = Reader()
    partial = observation("map", doc=Document([
        line("Tokyo City Food", 550, 430), line("Job", 550, 510),
        line("Close Map", 150, 970), line("Fast Travel", 370, 970)]))
    result._observe = lambda: partial
    result._transition = lambda current, **kwargs: current
    result._map_job(partial)
    assert result.data["history"][-1]["kind"] == "MAP_JOB_VERIFIED"


def test_map_clears_unrelated_card_before_finding_job_icon(monkeypatch, tmp_path):
    import pyautogui
    moves = []
    monkeypatch.setattr(pyautogui, "moveTo",
                        lambda x, y, **kwargs: moves.append((x, y)))
    monkeypatch.setattr("fh6.tokyo_delivery.job_icon_candidates",
                        lambda _: [(445, 521)] if moves and
                        moves[-1] == (1850, 500) else [])
    result = runner(tmp_path)
    result.nav.monitor = {"left": 0, "top": 0}
    footer = [line("Close Map", 150, 970), line("Fast Travel", 370, 970)]
    unrelated = observation("map", doc=Document(footer + [line("Taiyaki Scramble")]))
    target = observation("map", doc=Document(footer + [
        line("Tokyo City Food Delivery"), line("Job")]))
    result._observe = lambda: target if moves and moves[-1] == (445, 521) else unrelated
    result._transition = lambda current, **kwargs: current
    result._map_job(unrelated)
    assert moves[:2] == [(1850, 500), (445, 521)]
    assert result.data["history"][-1]["kind"] == "MAP_JOB_VERIFIED"


@pytest.mark.parametrize("metres", [1200, 2900])
def test_fresh_plaza_egress_uses_prompt_and_timer_at_both_start_distances(metres):
    start = observation("active", distance=metres, remaining=550,
                        prompt="park at the restaurant")
    assert plaza_egress_allowed(start, None, 0)
    assert plaza_egress_allowed(start, 20, 2)
    assert not plaza_egress_allowed(start, 20, 3)
    assert not plaza_egress_allowed(start, 40, 0)
    assert not plaza_egress_allowed(observation("active", distance=metres,
                                               remaining=400,
                                               prompt="park at the restaurant"), None, 0)


def test_auto_drive_status_reads_only_native_hud_and_anna_regions():
    on = Document([line("Auto Drive On", 156, 968)])
    off = Document([line("Enable Auto Drive", 458, 858)])
    route = Document([line("Press to Set a Route for Auto Drive to Begin",
                           920, 982)])
    assert auto_drive_on(on) and not auto_drive_off(on)
    assert auto_drive_off(off) and not auto_drive_on(off)
    assert auto_drive_needs_route(route)
    assert not auto_drive_on(Document([line("Auto Drive On", 900, 100)]))


def test_delivery_leg_uses_verified_route_when_anna_has_no_option(
        monkeypatch, tmp_path):
    from fh6 import delivery_route

    result = runner(tmp_path)
    active = observation("active", distance=3400, remaining=150,
                         prompt="drive to the destination with your colleague")
    result._observe = lambda: active
    monkeypatch.setattr(delivery_route, "route_cue", lambda _: SimpleNamespace(
        confidence=.9, steer=0, turn_urgency="none"))
    result._ensure_auto_drive(active)
    assert result.data["route_follow_stage"] == "delivery"
    assert result.pad.pulses == []
    assert result.data["history"][-1]["kind"] == "VISIBLE_ROUTE_FOLLOW"


def test_locally_verified_native_auto_steering_avoids_anna(tmp_path):
    result = runner(tmp_path)
    (tmp_path / "tokyo_delivery").mkdir()
    (tmp_path / "tokyo_delivery" /
     "native_auto_steering_assisted_braking.png").write_bytes(b"evidence")
    (tmp_path / "tokyo_delivery_assists.json").write_text(json.dumps({
        "session_id": result.data["id"], "auto_steering": True,
    }), encoding="utf-8")
    active = observation("active", distance=2900, remaining=150,
                         prompt="reach the destination")
    result._ensure_auto_drive(active)
    assert result.data["route_follow_stage"] == "native_steering"
    assert result.pad.pulses == []
    assert result.data["history"][-1]["kind"] == "NATIVE_AUTO_STEERING_SELECTED"


def test_guided_delivery_drive_uses_short_guarded_pulse(monkeypatch, tmp_path):
    from fh6 import delivery_route, farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 12)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: True)
    monkeypatch.setattr(delivery_route, "route_cue", lambda _: SimpleNamespace(
        confidence=.9, steer=.2, turn_urgency="later"))
    result = runner(tmp_path)
    result._save(route_follow_stage="delivery", prompt_stage="delivery")
    active = observation("active", distance=3400, remaining=150,
                         prompt="drive to the destination")
    result._observe = lambda: observation("summary")
    result._drive_shift(active)
    assert len(result.pad.drives) == 1
    assert result.pad.drives[0][:3] == (.68, .2, .6)
    assert any(item["kind"] == "GUIDED_DRIVE_INTENT" for item in result.data["history"])


def test_distant_centered_chevrons_get_only_a_short_reacquire_pulse():
    cue = SimpleNamespace(confidence=.5, turn="straight", target_x=909,
                          steer=-.03)
    assert guided_route_action(cue, 1) == (.38, -.03, .4)
    assert guided_route_action(cue, 40) is None
    assert guided_route_action(SimpleNamespace(confidence=.5, turn="right",
                                               target_x=1020, steer=.2), 1) is None


def test_delivery_stage_survives_split_destination_ocr():
    assert _prompt_stage("perform wreckage skills for current o reach the d stinat on") == "delivery"
    assert _prompt_stage("park at the restaurant") == "restaurant"


def test_guided_drive_waits_through_two_missing_route_frames(monkeypatch, tmp_path):
    from fh6 import delivery_route, farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 12)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: True)
    cues = iter([None, None, SimpleNamespace(
        confidence=.9, steer=0, turn_urgency="none")])
    monkeypatch.setattr(delivery_route, "route_cue", lambda _: next(cues))
    result = runner(tmp_path)
    result._save(route_follow_stage="delivery", prompt_stage="delivery")
    active = observation("active", distance=2300, remaining=150,
                         prompt="reach the destination")
    seen = iter([active, active, observation("summary")])
    result._observe = lambda: next(seen)
    result._drive_shift(active)
    assert len(result.pad.drives) == 1


def test_failed_summary_is_read_from_focused_native_crop(tmp_path):
    class Reader:
        def refine_region(self, frame, doc, region):
            return doc

        def read(self, frame):
            return Document([line("FAILED")]) if frame.shape[:2] == (75, 200) else Document([])

    class Nav(FakeNav):
        reader = Reader()

        def observe(self):
            return SimpleNamespace(
                frame=np.zeros((1080, 1920, 3), dtype=np.uint8),
                doc=Document([line("Job Summary", 200, 228),
                              line("Shift Progress", 250, 450)]), screen="unknown")

        def is_home(self, native):
            return False

        def is_roam(self, native):
            return False

    result = TokyoDelivery(Nav(), threading.Event(), root=tmp_path)
    result._load(1)
    assert result._observe().failed is True


def test_reconnect_modal_is_read_from_center_and_footer_crops(tmp_path):
    class Reader:
        def refine_region(self, frame, doc, region):
            if region[0] == 600:
                return Document([line("Controller Disconnected", 800, 490),
                                 line("Please reconnect a controller", 800, 565)])
            if region[1] == 955:
                return Document([*doc.lines, line("Ok", 100, 1000)])
            return doc

    class Nav(FakeNav):
        reader = Reader()

        def observe(self):
            return SimpleNamespace(
                frame=np.zeros((1080, 1920, 3), dtype=np.uint8),
                doc=Document([]), screen="unknown")

        def is_home(self, native):
            return False

        def is_roam(self, native):
            return False

    result = TokyoDelivery(Nav(), threading.Event(), root=tmp_path)
    result._load(1)
    assert result._observe().screen == "controller_disconnected"


def test_anna_auto_drive_enable_intent_precedes_dpad_left(tmp_path):
    result = runner(tmp_path)
    start = observation("active", distance=1200, remaining=550)
    menu = observation("active", distance=1200, remaining=549,
                       doc=Document([line("Enable Auto Drive", 458, 858)]))
    enabled = observation("active", distance=1200, remaining=548,
                          doc=Document([line("Auto Drive On", 156, 968)]))
    seen = iter([menu, enabled, enabled])
    result._observe = lambda: next(seen)

    def pulse(name, seconds=0.1):
        if name == "left":
            assert result.data["auto_drive_attempts"] == 1
            assert result.data["history"][-1]["kind"] == "AUTO_DRIVE_ENABLE_INTENT"
        result.pad.pulses.append(name)

    result.pad.pulse = pulse
    reached = result._ensure_auto_drive(start)
    assert reached.screen == "active"
    assert result.pad.pulses == ["down", "left"]
    assert result.data["auto_drive_verified"] is True
    assert result.pad.drives == []


def test_auto_drive_on_but_route_required_stops_without_throttle(
        monkeypatch, tmp_path):
    from fh6 import farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 0)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: False)
    result = runner(tmp_path)
    hud = Document([line("Auto Drive On", 156, 968),
                    line("Press to Set a Route for Auto Drive to Begin", 920, 982)])
    active = observation("active", distance=1200, remaining=550, doc=hud)
    result._observe = lambda: active
    with pytest.raises(DeliveryEvidenceUncertain, match="asks to set a route"):
        result._drive_shift(active)
    assert result.pad.pulses == []
    assert result.pad.drives == []
    assert result.data["history"][-1]["kind"] == "AUTO_DRIVE_ROUTE_REQUIRED"


def test_auto_drive_distance_progress_reaches_summary_without_manual_drive(
        monkeypatch, tmp_path):
    from fh6 import farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 30)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: True)
    result, _ = timed_runner(tmp_path)
    hud = Document([line("Auto Drive On", 156, 968)])
    start = observation("active", distance=1200, remaining=550, doc=hud)
    next_frames = iter([
        observation("active", distance=1100, remaining=548, doc=hud),
        observation("active", distance=1000, remaining=546, doc=hud),
        observation("summary"),
    ])
    result._observe = lambda: next(next_frames)
    result._drive_shift(start)
    assert result.pad.pulses == []
    assert result.pad.drives == []
    assert result.data["auto_drive_verified"] is True


def test_auto_drive_without_distance_progress_stops_and_retains_checkpoint(
        monkeypatch, tmp_path):
    from fh6 import farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 0)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: False)
    result, clock = timed_runner(tmp_path)
    hud = Document([line("Auto Drive On", 156, 968)])
    active = observation("active", distance=1200, remaining=550, doc=hud)
    result._observe = lambda: active
    with pytest.raises(DeliveryEvidenceUncertain,
                       match="did not reduce the native route distance"):
        result._drive_shift(active)
    assert clock() >= 45
    assert result.pad.drives == []
    assert result.data["history"][-1]["kind"] == "AUTO_DRIVE_NO_PROGRESS"


def test_failed_summary_does_not_count_and_is_idempotent(tmp_path):
    result = runner(tmp_path)
    result._save(attempt_seen_active=True)
    summary = observation("summary", failed=True, stars=0, progress=11000)
    result.data["progress_before"] = 10800
    result._wait = lambda *_, **__: summary
    result._summary(summary)
    result._summary(summary)
    assert result.data["completed"] == 0
    assert result.data["failed_shifts"] == 1
    assert sum(item["kind"] == "SHIFT_FAILED"
               for item in result.data["history"]) == 1


def test_unverified_summary_is_not_counted(tmp_path):
    result = runner(tmp_path)
    result._save(attempt_seen_active=True)
    summary = observation("summary", failed=False, stars=None, progress=None)
    result._wait = lambda *_, **__: summary
    with pytest.raises(RuntimeError, match="lacks new positive Shift Stars"):
        result._summary(summary)
    assert result.data["completed"] == 0
    assert result.data["phase"] == "summary_unverified"


def test_credit_progress_without_positive_shift_stars_does_not_count(tmp_path):
    result = runner(tmp_path)
    result._save(attempt_seen_active=True, progress_before=10800)
    summary = observation("summary", failed=False, stars=None, progress=11000)
    result._wait = lambda *_, **__: summary
    with pytest.raises(RuntimeError, match="lacks new positive Shift Stars"):
        result._summary(summary)
    assert result.data["completed"] == 0
    assert result.data["history"][-1]["credit_progress"] is True


def test_positive_summary_counts_once(tmp_path):
    result = runner(tmp_path)
    result._save(attempt_seen_active=True)
    summary = observation("summary", failed=False, stars=2, shift_progress=3)
    result._wait = lambda *_, **__: summary
    result._summary(summary)
    result._summary(summary)
    assert result.data["completed"] == 1
    assert result.data["phase"] == "complete"
    assert sum(item["kind"] == "SHIFT_VERIFIED"
               for item in result.data["history"]) == 1


def test_one_of_three_deliveries_does_not_count_full_shift(tmp_path):
    result = runner(tmp_path)
    result._save(attempt_seen_active=True, phase="summary_unverified")
    summary = observation("summary", failed=False, stars=2, shift_progress=1)
    result._wait = lambda *_, **__: summary
    result._summary(summary)
    result._summary(summary)
    assert result.data["completed"] == 0
    assert result.data["shift_progress"] == 1
    assert result.data["phase"] == "summary"
    assert sum(item["kind"] == "PARTIAL_SHIFT_VERIFIED"
               for item in result.data["history"]) == 1


def test_next_shift_resets_partial_shift_progress(tmp_path):
    result = runner(tmp_path)
    result._save(shift_progress=1, summary_processed=True, phase="summary")
    pending = {"action": "new_shift", "source": "summary",
               "targets": ["intro", "active"], "attempts": 1}
    result._save(pending=pending)
    result._verify_transition(pending, observation("active"))
    assert result.data["shift_progress"] == 0
    assert result.data["summary_processed"] is False


def test_new_solo_job_resets_old_attempt_after_game_restart(tmp_path):
    result = runner(tmp_path)
    old_attempt = result.data["attempt_id"]
    result._save(shift_progress=1, summary_processed=True,
                 attempt_seen_active=True, auto_drive_verified=True)
    pending = {"action": "solo", "source": "solo",
               "targets": ["intro", "active"], "attempts": 1}
    result._verify_transition(pending, observation("active"))
    assert result.data["attempt_id"] != old_attempt
    assert result.data["shift_progress"] == 0
    assert result.data["attempt_seen_active"] is False
    assert result.data["auto_drive_verified"] is False


def test_stars_without_shift_fraction_do_not_count(tmp_path):
    result = runner(tmp_path)
    result._save(attempt_seen_active=True)
    summary = observation("summary", failed=False, stars=2)
    result._wait = lambda *_, **__: summary
    with pytest.raises(DeliveryEvidenceUncertain):
        result._summary(summary)
    assert result.data["completed"] == 0
    assert result.data["phase"] == "summary_unverified"


def test_summary_visible_before_this_session_does_not_count(tmp_path):
    result = runner(tmp_path)
    summary = observation("summary", failed=False, stars=3)
    result._wait = lambda *_, **__: summary
    result._summary(summary)
    assert result.data["completed"] == 0
    assert result.data["summary_processed"]
    assert result.data["history"][-1]["kind"] == "PREEXISTING_SUMMARY_SKIPPED"


def test_pending_input_is_reconciled_from_visible_target_without_replay(tmp_path):
    result = runner(tmp_path)
    result._save(pending={"action": "solo", "source": "solo",
                          "targets": ["intro", "active"], "attempts": 1})
    result._observe = lambda: observation("active")
    reached = result._reconcile_pending(observation("solo"))
    assert reached.screen == "active"
    assert result.data["pending"] is None
    assert result.pad.drives == []
    assert result.data["completed"] == 0


def test_open_map_intent_on_verified_home_returns_to_home_without_replay(tmp_path):
    result = runner(tmp_path)
    result._save(pending={"action": "open_map", "source": "roam",
                          "targets": ["map"], "attempts": 1})
    reached = result._reconcile_pending(observation("home"))
    assert reached.screen == "home"
    assert result.data["pending"] is None
    assert result.data["history"][-1]["kind"] == "INPUT_NOT_ACCEPTED"
    assert result.nav.keys == []


@pytest.mark.parametrize(("action", "source", "targets"), [
    ("solo", "solo", {"intro", "active"}),
    ("continue", "intro", {"solo", "active"}),
    ("fast_travel", "map", {"fast_confirm", "intro"}),
    ("fast_confirm", "fast_confirm", {"intro", "roam"}),
    ("new_shift", "summary", {"intro", "active"}),
])
def test_nonrepeatable_pending_input_stops_without_replay(
        tmp_path, action, source, targets):
    result, clock = timed_runner(tmp_path)
    sends = []
    result._observe = lambda: observation(source)
    with pytest.raises(DeliveryInputUncertain, match="no button repeated"):
        result._transition(observation(source), action=action, source=source,
                           targets=targets, send=lambda: sends.append(action),
                           timeout=1)
    assert sends == [action]
    saved = json.loads((Path(tmp_path) / "tokyo_delivery.json").read_text())
    assert saved["pending"]["action"] == action
    with pytest.raises(DeliveryInputUncertain, match="no button repeated"):
        result._reconcile_pending(observation(source))
    with pytest.raises(DeliveryInputUncertain, match="no button repeated"):
        result._transition(observation(source), action=action, source=source,
                           targets=targets, send=lambda: sends.append(action),
                           timeout=1)
    assert sends == [action]
    assert result.data["pending"] == saved["pending"]
    assert clock() >= 15


def test_delayed_pending_target_is_verified_without_replay(tmp_path):
    result, clock = timed_runner(tmp_path)
    result._save(pending={"action": "solo", "source": "solo",
                          "targets": ["intro", "active"], "attempts": 1,
                          "settle_timeout_s": 30})
    # The first four seconds on Solo do not prove the original A was lost.
    result._observe = lambda: observation("solo" if clock() < 20 else "active")
    reached = result._reconcile_pending(observation("solo"))
    assert reached.screen == "active"
    assert result.data["pending"] is None
    assert result.pad.drives == []
    assert 20 <= clock() < 30


def test_auto_drive_enable_intent_survives_crash_without_dpad_replay(tmp_path):
    result = runner(tmp_path)
    start = observation("active", distance=1200, remaining=550)
    menu = observation("active", distance=1200, remaining=549,
                       doc=Document([line("Enable Auto Drive", 458, 858)]))
    result._observe = lambda: menu

    class SimulatedCrash(Exception):
        pass

    def crash_on_left(name, seconds=0.1):
        if name == "left":
            assert result.data["auto_drive_attempts"] == 1
            raise SimulatedCrash
        result.pad.pulses.append(name)

    result.pad.pulse = crash_on_left
    with pytest.raises(SimulatedCrash):
        result._ensure_auto_drive(start)

    resumed = runner(tmp_path)
    with pytest.raises(DeliveryInputUncertain, match="no Dpad repeated"):
        resumed._ensure_auto_drive(start)
    assert resumed.pad.pulses == []
    enabled = observation("active", distance=1200, remaining=548,
                          doc=Document([line("Auto Drive On", 156, 968)]))
    resumed._ensure_auto_drive(enabled)
    assert resumed.data["auto_drive_verified"] is True
    assert resumed.pad.pulses == []
    assert sum(event["kind"] == "AUTO_DRIVE_ENABLE_INTENT"
               for event in resumed.data["history"]) == 1


def test_legacy_stall_intent_overrides_stale_false_flag(tmp_path):
    result = runner(tmp_path)
    result._save(event={"kind": "STALL_RECOVERY_INTENT"},
                 stall_recovery_used=False)
    assert result._stall_recovery_reserved()


def test_clear_new_job_stage_resets_parking_budget_but_ocr_variation_does_not(
        monkeypatch, tmp_path):
    from fh6 import delivery_route, farm_motion

    monkeypatch.setattr(delivery_route, "route_cue",
                        lambda *_: SimpleNamespace(confidence=.9, steer=0,
                                                   turn_urgency="none"))
    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 20)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: True)
    result = runner(tmp_path)
    result._save(last_prompt="park at the restaurant", prompt_stage="restaurant",
                 parking_nudges=6, parking_brakes=4,
                 auto_drive_verified=True)
    result._observe = lambda: observation("summary")
    result._drive_shift(observation("active", distance=500, remaining=400,
                                    prompt="paik at the restaurant"))
    assert result.data["parking_nudges"] == 6
    assert result.data["parking_brakes"] == 4
    assert result.data["history"][-1]["kind"] == "JOB_PROMPT"

    result._drive_shift(observation("active", distance=500, remaining=400,
                                    prompt="deliver to the customer"))
    assert result.data["parking_nudges"] == 0
    assert result.data["parking_brakes"] == 0
    assert result.data["auto_drive_verified"] is False
    assert result.data["auto_drive_attempts"] == 0
    assert any(event["kind"] == "JOB_STAGE_CHANGED"
               for event in result.data["history"][-3:])


def test_distance_jump_to_next_waypoint_resets_parking_budget(
        monkeypatch, tmp_path):
    from fh6 import delivery_route, farm_motion

    monkeypatch.setattr(delivery_route, "route_cue",
                        lambda *_: SimpleNamespace(confidence=.9, steer=0))
    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 0)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: False)
    result, clock = timed_runner(tmp_path)
    result._save(parking_nudges=6, parking_brakes=4,
                 auto_drive_verified=True)
    first = observation("active", distance=15, remaining=400)
    next_waypoint = observation("active", distance=350, remaining=399)
    seen = iter([next_waypoint, observation("summary")])
    result._observe = lambda: next(seen)
    result._drive_shift(first)
    assert result.data["parking_nudges"] == 0
    assert result.data["parking_brakes"] == 0
    assert result.data["auto_drive_verified"] is True
    assert any(item["kind"] == "NEXT_WAYPOINT_VERIFIED"
               for item in result.data["history"])


def test_anna_new_drop_off_allows_large_distance_jump(monkeypatch, tmp_path):
    from fh6 import farm_motion
    from fh6.tokyo_delivery import next_drop_off_announced

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 35)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: True)
    first_doc = Document([line("Auto Drive On", 156, 968)])
    advanced_doc = Document([
        line("Auto Drive On", 156, 968),
        line("Delivery complete. I have changed your route to the next drop-off", 1006, 960),
    ])
    assert next_drop_off_announced(advanced_doc)
    result, _ = timed_runner(tmp_path)
    result._save(auto_drive_verified=True)
    first = observation("active", distance=75, remaining=200, doc=first_doc)
    next_waypoint = observation("active", distance=1700, remaining=199,
                                doc=advanced_doc)
    seen = iter([next_waypoint, observation("summary")])
    result._observe = lambda: next(seen)
    result._drive_shift(first)
    events = [item for item in result.data["history"]
              if item["kind"] == "NEXT_WAYPOINT_VERIFIED"]
    assert len(events) == 1
    assert events[0]["anna_confirmed"] is True


def test_two_fresh_route_distances_rebase_after_unannounced_jump(
        monkeypatch, tmp_path):
    from fh6 import farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 35)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: True)
    hud = Document([line("Auto Drive On", 156, 968)])
    result, _ = timed_runner(tmp_path)
    result._save(auto_drive_verified=True)
    first = observation("active", distance=75, remaining=200, doc=hud)
    seen = iter([
        observation("active", distance=758, remaining=199, doc=hud),
        observation("active", distance=740, remaining=198, doc=hud),
        observation("summary"),
    ])
    result._observe = lambda: next(seen)
    result._drive_shift(first)
    rebases = [item for item in result.data["history"]
               if item["kind"] == "ROUTE_DISTANCE_REBASED"]
    assert len(rebases) == 1
    assert rebases[0]["prior_distance_m"] == 75
    assert rebases[0]["distance_m"] == 740


def test_near_target_brakes_only_while_measured_speed_is_high(
        monkeypatch, tmp_path):
    from fh6 import farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 15)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: True)
    result = runner(tmp_path)
    result._observe = lambda: observation("summary")
    result._drive_shift(observation("active", distance=12, remaining=150))
    assert result.pad.drives == [(-.25, 0, .2, 0)]
    assert result.data["parking_nudges"] == 0
    assert result.data["parking_brakes"] == 1


def test_near_target_braking_is_checkpointed_and_bounded_across_resume(
        monkeypatch, tmp_path):
    from fh6 import farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 15)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: True)
    result, clock = timed_runner(tmp_path)
    active = observation("active", distance=12, remaining=150)
    result._observe = lambda: active
    result.pad.drive = lambda throttle, steer, seconds: (
        result.pad.drives.append((throttle, steer, seconds,
                                  result.data["parking_brakes"])),
        clock.advance(seconds))
    with pytest.raises(RuntimeError, match="parking trigger did not activate"):
        result._drive_shift(active)
    assert len(result.pad.drives) == MAX_PARKING_BRAKES
    assert all(throttle == -.25 and saved_count == number
               for number, (throttle, _, _, saved_count)
               in enumerate(result.pad.drives, 1))
    assert result.data["parking_brakes"] == MAX_PARKING_BRAKES

    resumed_nav = FakeNav()
    resumed_nav.pause = clock.advance
    resumed = TokyoDelivery(resumed_nav, threading.Event(),
                            root=tmp_path, clock=clock)
    resumed._load(1)
    resumed.pad = FakePad(resumed)
    resumed._observe = lambda: active
    with pytest.raises(RuntimeError, match="parking trigger did not activate"):
        resumed._drive_shift(active)
    assert resumed.pad.drives == []
    assert resumed.data["parking_brakes"] == MAX_PARKING_BRAKES


def test_near_target_waits_then_reserves_bounded_forward_nudge(
        monkeypatch, tmp_path):
    from fh6 import delivery_route, farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 0)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: False)
    monkeypatch.setattr(delivery_route, "route_cue",
                        lambda *_: SimpleNamespace(confidence=.9, steer=.5))
    result, clock = timed_runner(tmp_path)
    active = observation("active", distance=12, remaining=150)
    seen = iter([active, observation("summary")])
    result._observe = lambda: next(seen)
    result.pad.drive = lambda throttle, steer, seconds: (
        result.pad.drives.append((throttle, steer, seconds,
                                  result.data["parking_nudges"])),
        clock.advance(seconds))
    result._drive_shift(active)
    assert result.pad.drives == [(.18, .15, .3, 1)]
    assert result.data["parking_nudges"] == 1
    assert result.data["history"][-1]["kind"] == "PARKING_NUDGE_INTENT"


@pytest.mark.parametrize("cue_present", [False, True])
def test_near_target_neutral_wait_is_bounded_and_never_reverses_when_stopped(
        monkeypatch, tmp_path, cue_present):
    from fh6 import delivery_route, farm_motion

    monkeypatch.setattr(farm_motion, "speed_from_frame", lambda *_: 0)
    monkeypatch.setattr(farm_motion, "scene_is_moving", lambda *_: False)
    cue = SimpleNamespace(confidence=.9, steer=0) if cue_present else None
    monkeypatch.setattr(delivery_route, "route_cue", lambda *_: cue)
    result, clock = timed_runner(tmp_path)
    if cue_present:
        result._save(parking_nudges=MAX_PARKING_NUDGES)
    active = observation("active", distance=12, remaining=150)
    result._observe = lambda: active
    with pytest.raises(RuntimeError, match="parking trigger did not activate"):
        result._drive_shift(active)
    assert result.pad.drives == []
    assert result.pad.neutrals >= 8
    assert clock() >= 6


@pytest.mark.parametrize(("source", "target"), [
    ("pause_menu", "roam"),
    ("pause_menu", "active"),
    ("job_journal", "discover"),
    ("discover", "journal"),
    ("journal", "home"),
])
def test_backing_out_of_pause_and_journal_is_observed_and_checkpointed(
        tmp_path, source, target):
    result = runner(tmp_path)
    result._observe = lambda: observation(target)
    if source == "pause_menu":
        reached = result._leave_pause(observation(source))
    else:
        reached = result._leave_journal(observation(source))
    assert reached.screen == target
    assert result.nav.keys == ["esc"]
    assert result.data["pending"] is None
    assert result.data["history"][-1]["kind"] == "INPUT_VERIFIED"


def test_active_elapsed_time_survives_checkpoint_and_resume(tmp_path):
    now = [100.]
    emitted = []
    clock = lambda: now[0]
    first = TokyoDelivery(FakeNav(), threading.Event(),
                          emit=lambda name, payload: emitted.append((name, payload)),
                          root=tmp_path, clock=clock)
    first._load(1)
    now[0] += 7.5
    first._save(phase="active")
    assert first.data["active_seconds"] == 7.5

    resumed = TokyoDelivery(FakeNav(), threading.Event(),
                            emit=lambda name, payload: emitted.append((name, payload)),
                            root=tmp_path, clock=clock)
    now[0] += 100  # Offline time between worker instances is not active time.
    resumed._load(1)
    assert emitted[-1][1]["active_seconds"] == 7.5
    now[0] += 2.5
    resumed._save(phase="active")
    assert resumed.data["active_seconds"] == 10
    assert emitted[-1][1]["active_seconds"] == 10


def test_worker_exit_flushes_final_active_interval(tmp_path):
    clock = ManualClock()
    nav = FakeNav()
    result = TokyoDelivery(nav, threading.Event(), root=tmp_path, clock=clock)

    def make_pad(*, guard):
        assert guard == nav.check
        clock.advance(5.25)
        return FakePad(result)

    result.pad_factory = make_pad
    result.run(1)
    saved = json.loads((Path(tmp_path) / "tokyo_delivery.json").read_text())
    assert saved["active_seconds"] == 5.25
