"""Checkpointed Tokyo City Food Delivery worker.

The wheelspin panel's ordinary Controller owns the WorkerLease, lifecycle,
sync gate, navigator, OCR reader and F7 signal.  This module adds the job
state machine and borrows the same worker's virtual pad for driving.  A job
is counted only from a verified, non-failed native summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import time
import uuid

import cv2
import numpy as np

from forza_cycle import BASE

from .farming import remaining_seconds
from .game_lifecycle import controller_disconnected_modal
from .ocr import Document, normalize
from .session import load_checkpoint, replace_checkpoint


MODE = "Tokyo Delivery"
MAX_FAILED_SHIFTS = 6
ACTIVE_WALL_LIMIT_SECONDS = 11 * 60
MAX_INPUT_ATTEMPTS = 2
MAX_PARKING_NUDGES = 6
MAX_PARKING_BRAKES = 4
REPLAYABLE_ACTIONS = frozenset({
    "open_map", "leave_pause", "journal_back_job_journal",
    "journal_back_collection_grid", "journal_back_discover",
    "journal_back_journal",
})
PLAYABLE_JOB_SCREENS = frozenset({
    "home", "roam", "map", "fast_confirm", "solo", "intro",
    "active", "summary", "job_journal", "journal", "discover",
    "collection_grid", "pause_menu",
})


class DeliveryInputUncertain(RuntimeError):
    """A saved menu input may have been accepted; no repeat is permitted."""


class DeliveryEvidenceUncertain(DeliveryInputUncertain):
    """Native delivery or route evidence is insufficient for further input."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _document_text(doc: Document) -> str:
    return normalize(" ".join(line.text for line in doc.lines))


def auto_drive_on(doc: Document) -> bool:
    """Recognize the native HUD status or ANNA's inverse menu option."""
    return (doc.has("Auto Drive On", (90, 940, 280, 80), contains=True) or
            doc.has("Disable Auto Drive", (310, 830, 335, 95), contains=True))


def auto_drive_off(doc: Document) -> bool:
    return (doc.has("Auto Drive Off", (90, 940, 280, 80), contains=True) or
            doc.has("Enable Auto Drive", (310, 830, 335, 95), contains=True))


def auto_drive_needs_route(doc: Document) -> bool:
    return doc.has("Set a Route for Auto Drive to Begin",
                   (400, 950, 1150, 95), contains=True)


def distance_from_lines(lines) -> float | None:
    """Read the lower-left native route distance, ignoring its map-pin glyph."""
    found = []
    for line in lines:
        match = re.search(r"(?<!\d)(\d{1,5}(?:[.,]\d)?)\s*(KM|M)\b",
                          line.text.upper().replace("O", "0"))
        if match:
            value = float(match.group(1).replace(",", "."))
            metres = value * 1000 if match.group(2) == "KM" else value
            if 0 <= metres <= 20_000:
                found.append(metres)
    return found[0] if len(found) == 1 else None


def delivery_remaining_seconds(doc: Document) -> float | None:
    """Read the job timer when OCR drops the colon in its fixed HUD row."""
    standard = remaining_seconds(doc)
    if standard is not None:
        return standard
    labels = doc.find("Time Remaining", (40, 35, 350, 165), contains=True)
    if len(labels) != 1:
        return None
    row = labels[0].center[1]
    values = []
    for line in doc.lines:
        x, y = line.center
        if abs(y - row) > 18 or not 230 <= x <= 400:
            continue
        match = re.fullmatch(r"\s*(\d{2})(\d{2})[.:](\d{2,3})\s*", line.text)
        if match and int(match.group(2)) < 60:
            minutes, seconds, fraction = match.groups()
            values.append(60 * int(minutes) + int(seconds) + float("0." + fraction))
    return values[0] if len(values) == 1 else None


def job_progress_from_lines(lines) -> int | None:
    """Accept a complete native job-progress fraction, not a clipped suffix."""
    values = []
    for line in lines:
        match = re.search(
            r"(?<!\d)((?:\d{1,3}(?:,\d{3})+)|\d{4,})\s*/\s*"
            r"((?:\d{1,3}(?:,\d{3})+)|\d{4,})(?!\d)", line.text)
        if not match:
            continue
        current, target = (int(value.replace(",", "")) for value in match.groups())
        if 0 <= current <= target and target >= 10_000:
            values.append(current)
    return values[0] if len(values) == 1 else None


def shift_stars_from_lines(lines) -> int | None:
    """Read only a digit in the native Shift Stars value box."""
    values = []
    for line in lines:
        x, y = line.center
        raw = line.text.strip()
        if 470 <= x <= 555 and 530 <= y <= 615 and re.fullmatch(r"[0-5]", raw):
            values.append(int(raw))
    return values[0] if len(values) == 1 else None


def shift_progress_from_lines(lines) -> int | None:
    """Read the delivery count within one native three-delivery shift."""
    values = []
    for line in lines:
        match = re.fullmatch(r"\s*([1-3])\s*/\s*3\s*", line.text)
        if match:
            values.append(int(match.group(1)))
    return values[0] if len(values) == 1 else None


def next_drop_off_announced(doc: Document) -> bool:
    """Recognize ANNA's native confirmation that a delivery changed the route."""
    words = _document_text(doc)
    return "delivery complete" in words and "route to the next drop off" in words


def guided_route_action(cue, speed_kmh):
    """Return a bounded input only for a clear route or a centered far trail."""
    if cue is None or speed_kmh is not None and speed_kmh > 80:
        return None
    if cue.confidence >= .75:
        throttle = .68 if cue.turn_urgency in {"none", "later"} else .42
        if speed_kmh is not None and speed_kmh >= 60:
            throttle = .25
        return throttle, max(-.38, min(.38, cue.steer)), .6
    if (cue.confidence >= .45 and cue.turn == "straight" and
            abs(cue.target_x - 960) <= 110 and
            (speed_kmh is None or speed_kmh <= 35)):
        return .38, max(-.12, min(.12, cue.steer)), .4
    return None


def plaza_egress_allowed(observation, speed_kmh, drive_steps: int) -> bool:
    """Allow only a few straight pulses from a freshly loaded restaurant start.

    The pickup can begin 1.2 or 2.9 km away, so distance is only a sanity
    bound.  The native prompt and nearly full timer identify the start; saved
    pulse count prevents replaying the same motion after an interruption.
    """
    return (observation.screen == "active" and drive_steps < 3 and
            observation.remaining_s is not None and observation.remaining_s >= 500 and
            observation.distance_m is not None and
            300 <= observation.distance_m <= 5_000 and
            "restaurant" in observation.prompt and
            (speed_kmh is None or speed_kmh < 35))


def _prompt_stage(prompt: str) -> str | None:
    """Recognize only clear job-waypoint changes, not small OCR variations."""
    words = set(normalize(prompt).split())
    if "restaurant" in words:
        return "restaurant"
    if words & {"deliver", "delivery", "customer", "destination", "reach"}:
        return "delivery"
    return None


def job_icon_candidates(frame) -> list[tuple[int, int]]:
    """Find the square blue job icon; every candidate is later OCR-verified.

    The Winter map also has blue house and circular event icons.  The job
    square's connected area and height differ from those in the saved map
    frames; this is a candidate generator, never proof of the destination.
    """
    if frame is None or getattr(frame, "shape", (0, 0))[:2] != (1080, 1920):
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([115, 110, 100]),
                       np.array([125, 255, 255]))
    mask[:100, :] = 0
    mask[900:, :] = 0
    mask[:, :50] = 0
    mask[:, 1870:] = 0
    count, _, boxes, centers = cv2.connectedComponentsWithStats(mask)
    found = []
    for index in range(1, count):
        _, _, width, height, area = (int(value) for value in boxes[index])
        if 38 <= width <= 80 and 37 <= height <= 80 and area >= 700:
            x, y = (int(round(value)) for value in centers[index])
            found.append((area, x, y))
    found.sort(reverse=True)
    return [(x, y) for _, x, y in found[:8]]


def classify_screen(doc: Document, *, is_home: bool = False,
                    is_roam: bool = False, native_screen: str = "unknown") -> str:
    """Classify job screens independently of the car-farming recognizer."""
    body = _document_text(doc)
    if controller_disconnected_modal(doc):
        return "controller_disconnected"
    if doc.has("Job Summary", (50, 180, 600, 160), contains=True) and (
            "shift progress" in body or "delivery stars" in body):
        return "summary"
    if doc.has("Time Remaining", (35, 25, 420, 135), contains=True):
        return "active"
    if (doc.has("Fast Travel", (600, 385, 720, 120), contains=True)
            and doc.has("Yes", (600, 535, 720, 85))
            and doc.has("No", (600, 605, 720, 85))):
        return "fast_confirm"
    if (doc.has("Close Map", (120, 950, 500, 100), contains=True)
            and doc.has("Fast Travel", (300, 950, 350, 100), contains=True)):
        return "map"
    if (doc.has("Solo", (65, 650, 580, 105))
            and "tokyo city food delivery" in body):
        return "solo"
    if (doc.has("Continue", (45, 505, 435, 130), contains=True)
            and doc.has("Job", (40, 260, 300, 205), contains=True)):
        return "intro"
    # Collection Journal's job progression grid has no recognized generic
    # menu name.  Its driver cards and keyboard Back footer are distinctive.
    if (doc.has("Junior Delivery Driver", (120, 390, 390, 105)) and
            doc.has("Seasoned Delivery Driver", (450, 635, 390, 105)) and
            doc.has("Back", (220, 970, 200, 85), contains=True)):
        return "job_journal"
    if (doc.has("Campaign", (40, 185, 510, 170), contains=True) and
            doc.has("Drive", (60, 675, 400, 105)) and
            doc.has("Collection Journal", (60, 750, 420, 95))):
        return "home"
    if is_home:
        return "home"
    if is_roam or doc.has("ANNA", (55, 975, 320, 100), contains=True):
        return "roam"
    if native_screen == "pause_menu":
        return "pause_menu"
    if native_screen in {"journal", "discover", "collection_grid"}:
        return native_screen
    return "unknown"


@dataclass(frozen=True)
class DeliveryObservation:
    screen: str
    native: object
    doc: Document
    distance_m: float | None = None
    remaining_s: float | None = None
    prompt: str = ""
    progress: int | None = None
    shift_stars: int | None = None
    shift_progress: int | None = None
    failed: bool = False


class TokyoDelivery:
    """One resumed, counted job session under the main FH6 worker."""

    def __init__(self, nav, running, emit=lambda *_: None, *, root=None,
                 pad_factory=None, clock=time.monotonic):
        self.nav, self.running, self.emit = nav, running, emit
        self.root = Path(root) if root is not None else BASE / "runs"
        self.path = self.root / "tokyo_delivery.json"
        self.clock = clock
        self._last_accounted_at = None
        self.pad_factory = pad_factory
        self.pad = None
        self._keyboard_ready = False
        self.data: dict = {}

    def _check(self):
        self.nav.check()  # F7, sync, display and focus checks from the worker.
        if self.pad is not None:
            self.pad.check()

    def _native_auto_steering_enabled(self):
        """Use only the locally verified assist for this checkpointed session."""
        path = self.root / "tokyo_delivery_assists.json"
        if not path.is_file():
            return False
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        evidence = self.root / "tokyo_delivery" / "native_auto_steering_assisted_braking.png"
        return (config.get("session_id") == self.data.get("id") and
                config.get("auto_steering") is True and evidence.is_file())

    def _save(self, event=None, **changes):
        next_data = dict(self.data)
        next_data.update(changes)
        now = self.clock()
        if self._last_accounted_at is not None:
            next_data["active_seconds"] = round(
                max(0., float(self.data.get("active_seconds", 0))) +
                max(0., now - self._last_accounted_at), 3)
        next_data["updated_at"] = _utc_now()
        if event is not None:
            history = list(next_data.get("history", []))
            history.append(dict(at=next_data["updated_at"], **event))
            next_data["history"] = history
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(next_data, indent=2, sort_keys=True),
                                 encoding="utf-8")
            replace_checkpoint(temporary, self.path, keep_backup=True)
        finally:
            temporary.unlink(missing_ok=True)
        self.data = next_data
        self._last_accounted_at = now
        self._progress()

    def _progress(self):
        if not self.data:
            return
        self.emit("progress", dict(
            id=self.data["id"], mode=MODE, phase=self.data["phase"],
            completed=self.data["completed"], rewards=0, bought=0,
            limit=self.data["limit"],
            active_seconds=self.data.get("active_seconds", 0), farm_runs=0,
            failed_shifts=self.data.get("failed_shifts", 0),
            last_prompt=self.data.get("last_prompt", "")))

    def _load(self, limit: int):
        if type(limit) is not int or not 1 <= limit <= 10_000:
            raise ValueError("Tokyo Delivery needs 1–10,000 verified shifts")
        saved = load_checkpoint(self.path,
                                required_fields=("version", "id", "mode", "limit",
                                                 "completed", "phase", "attempt_id"))
        if saved and saved.get("phase") != "complete":
            if saved.get("version") != 1 or saved.get("mode") != MODE:
                raise RuntimeError("Tokyo Delivery checkpoint version or mode differs")
            if saved["limit"] != limit:
                raise ValueError("Resume the saved Tokyo Delivery shift target")
            self.data = saved
            self._last_accounted_at = self.clock()
            self._progress()
            return
        past = list(saved.get("history", [])) if saved else []
        self.data = dict(version=1, id=datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8],
                         mode=MODE, limit=limit, completed=0, failed_shifts=0,
                         consecutive_failures=0, phase="entry", attempt_id=uuid.uuid4().hex,
                         summary_processed=False, attempt_seen_active=False,
                         pending=None, last_prompt="", prompt_stage=None,
                         drive_steps=0, stall_recovery_used=False,
                         parking_nudges=0, parking_brakes=0,
                         auto_drive_attempts=0, auto_drive_verified=False,
                         route_follow_stage=None,
                         reconnect_intent=None,
                         active_seconds=0, history=past)
        self._last_accounted_at = self.clock()
        self._save(event=dict(kind="SESSION_STARTED", limit=limit))

    def _observe(self) -> DeliveryObservation:
        self._check()
        native = self.nav.observe()
        doc = native.doc
        phase = self.data.get("phase", "")
        # Full-frame OCR occasionally loses the white job HUD against snow.
        # The established OCR reader can re-read its fixed native region.
        if (phase in {"active", "summary"} or native.screen == "unknown") and \
                remaining_seconds(doc) is None:
            doc = self.nav.reader.refine_region(native.frame, doc, (40, 35, 400, 170))
        if phase in {"active", "summary"} and not doc.has(
                "Job Summary", (50, 180, 600, 160), contains=True) and not doc.has(
                "Time Remaining", (35, 25, 420, 135), contains=True):
            doc = self.nav.reader.refine_region(native.frame, doc, (60, 190, 550, 455))
        native.doc = doc
        home = self.nav.is_home(native)
        roam = self.nav.is_roam(native)
        screen = classify_screen(doc, is_home=home, is_roam=roam,
                                 native_screen=native.screen)
        if screen == "unknown":
            # The reconnect modal can replace every normal HUD cue.  Its
            # central banner is reliable even when full-frame OCR misses it.
            doc = self.nav.reader.refine_region(native.frame, doc,
                                                (600, 450, 750, 180))
            native.doc = doc
            screen = classify_screen(doc, is_home=home, is_roam=roam,
                                     native_screen=native.screen)
        if screen == "unknown":
            doc = self.nav.reader.refine_region(native.frame, doc,
                                                (55, 955, 260, 100))
            native.doc = doc
            screen = classify_screen(doc, is_home=home, is_roam=roam,
                                     native_screen=native.screen)
        if screen == "unknown":
            # The map footer spans more of the frame than the modal keycap.
            doc = self.nav.reader.refine_region(native.frame, doc,
                                                (60, 965, 1250, 95))
            native.doc = doc
            screen = classify_screen(doc, is_home=home, is_roam=roam,
                                     native_screen=native.screen)
        if (screen == "unknown" or screen == "roam" and
                (doc.has("Job", (40, 250, 360, 230), contains=True) or
                 "tokyo city food" in _document_text(doc))):
            doc = self.nav.reader.refine_region(native.frame, doc, (50, 250, 850, 360))
            native.doc = doc
            screen = classify_screen(doc, is_home=home, is_roam=roam,
                                     native_screen=native.screen)
        if screen == "active" and not (auto_drive_on(doc) or auto_drive_off(doc)):
            doc = self.nav.reader.refine_region(native.frame, doc,
                                                (85, 930, 600, 100))
            native.doc = doc
        distance = None
        if screen == "active":
            distance_doc = self.nav.reader.read(native.frame[700:815, 95:395])
            distance = distance_from_lines(distance_doc.lines)
        prompt = ""
        if screen == "active":
            prompt_lines = [line.text for line in doc.lines
                            if 35 <= line.center[0] <= 420 and 125 <= line.center[1] <= 225]
            prompt = normalize(" ".join(prompt_lines))
        shift_stars = shift_progress = None
        if screen == "summary":
            shift_stars = shift_stars_from_lines(doc.lines)
            shift_progress = shift_progress_from_lines(doc.lines)
            if shift_stars is None:
                stars = self.nav.reader.read(native.frame[525:600, 350:555])
                values = [int(line.text.strip()) for line in stars.lines
                          if re.fullmatch(r"[0-5]", line.text.strip())]
                if len(values) == 1:
                    shift_stars = values[0]
            if shift_progress is None:
                enlarged = cv2.resize(native.frame[420:490, 450:565], None,
                                      fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                shift_progress = shift_progress_from_lines(
                    self.nav.reader.read(enlarged).lines)
        failed = screen == "summary" and "failed" in _document_text(doc)
        if screen == "summary" and not failed:
            failure_crop = self.nav.reader.read(native.frame[525:600, 100:300])
            failed = "failed" in _document_text(failure_crop)
        result = DeliveryObservation(
            screen=screen, native=native, doc=doc, distance_m=distance,
            remaining_s=delivery_remaining_seconds(doc) if screen == "active" else None,
            prompt=prompt,
            progress=job_progress_from_lines(doc.lines) if screen in {"solo", "summary"} else None,
            shift_stars=shift_stars, shift_progress=shift_progress,
            failed=failed)
        self._check()
        return result

    def _wait(self, targets, *, timeout=45):
        targets = set(targets)
        deadline = self.clock() + timeout
        last = None
        stable = 0
        while self.clock() < deadline:
            current = self._observe()
            stable = stable + 1 if current.screen in targets and current.screen == last else (
                1 if current.screen in targets else 0)
            last = current.screen
            if stable >= 2:
                return current
            self.nav.pause(.25)
        raise RuntimeError(f"Tokyo Delivery did not reach {sorted(targets)}; checkpoint retained")

    def _reconcile_pending(self, current):
        pending = self.data.get("pending")
        if not pending:
            return current
        targets = set(pending["targets"])
        if current.screen in targets:
            return self._verify_transition(pending, current)
        action = pending["action"]
        replayable = action in REPLAYABLE_ACTIONS
        if action == "open_map" and current.screen == "home":
            # M had no map effect while the campaign Drive menu was open.
            # The native home menu proves it is safe to discard this
            # reversible intent and enter free roam first.
            self._save(event=dict(kind="INPUT_NOT_ACCEPTED", action=action,
                                  reached="home"), pending=None)
            return current
        if current.screen not in {pending["source"], "unknown"}:
            raise DeliveryInputUncertain(
                f"Pending Tokyo {action} reached {current.screen}; no button repeated")
        # A, X and fast-travel submissions can be accepted while the same
        # menu remains visible for a long loading transition.  Observe for
        # their original timeout, then retain the intent and stop.  Only
        # reversible map/back operations can be retried from a stable source.
        grace = 4 if replayable else max(15, float(pending.get("settle_timeout_s", 60)))
        deadline = self.clock() + grace
        seen = current
        stable_target = stable_source = 0
        last_target = None
        while self.clock() < deadline:
            seen = self._observe()
            if seen.screen in targets:
                stable_target = stable_target + 1 if seen.screen == last_target else 1
                last_target = seen.screen
                stable_source = 0
                if stable_target >= 2:
                    return self._verify_transition(pending, seen)
            elif seen.screen == pending["source"]:
                stable_source += 1
                stable_target = 0
                last_target = None
            elif seen.screen == "unknown":
                stable_target = stable_source = 0
                last_target = None
            else:
                raise DeliveryInputUncertain(
                    f"Pending Tokyo {action} changed to {seen.screen}; no button repeated")
            self.nav.pause(.3)
        if replayable and seen.screen == pending["source"] and stable_source >= 2:
            return seen
        raise DeliveryInputUncertain(
            f"Tokyo {action} input may be accepted; {seen.screen} remains visible. "
            "Saved intent retained; no button repeated")

    def _verify_transition(self, pending, current):
        changes = {"pending": None}
        if pending["action"] == "new_shift":
            changes.update(attempt_id=uuid.uuid4().hex, summary_processed=False,
                           attempt_seen_active=False,
                           phase="entry", shift_progress=0,
                           drive_steps=0, last_prompt="",
                           prompt_stage=None,
                           stall_recovery_used=False, parking_nudges=0,
                           parking_brakes=0, auto_drive_attempts=0,
                           auto_drive_verified=False, route_follow_stage=None,
                           progress_before=None)
        elif pending["action"] == "solo":
            changes.update(phase="entry", attempt_id=uuid.uuid4().hex,
                           summary_processed=False, attempt_seen_active=False,
                           shift_progress=0, drive_steps=0, last_prompt="",
                           prompt_stage=None, stall_recovery_used=False,
                           parking_nudges=0, parking_brakes=0,
                           auto_drive_attempts=0, auto_drive_verified=False,
                           route_follow_stage=None,
                           progress_before=None)
        elif current.screen == "active":
            changes["phase"] = "active"
        self._save(event=dict(kind="INPUT_VERIFIED", action=pending["action"],
                              reached=current.screen), **changes)
        return current

    def _transition(self, current, *, action, source, targets, send, timeout=60):
        if current.screen != source:
            raise RuntimeError(f"{action} needs {source}; observed {current.screen}")
        pending = self.data.get("pending")
        if pending and pending["action"] != action:
            raise RuntimeError(f"Pending {pending['action']} blocks {action}")
        if pending and action not in REPLAYABLE_ACTIONS:
            raise DeliveryInputUncertain(
                f"Tokyo {action} input remains uncertain; saved intent retained, no button repeated")
        attempts = int(pending.get("attempts", 0)) if pending else 0
        if attempts >= MAX_INPUT_ATTEMPTS:
            raise RuntimeError(f"{action} was not accepted after {attempts} verified attempts")
        new_pending = dict(action=action, source=source, targets=sorted(set(targets)),
                           attempts=attempts + 1, intent_at=_utc_now(),
                           settle_timeout_s=timeout)
        self._save(event=dict(kind="INPUT_INTENT", action=action,
                              attempt=attempts + 1), pending=new_pending)
        self._check()
        send()
        deadline = self.clock() + timeout
        sent_at = self.clock()
        last = None
        stable = 0
        reached = None
        while self.clock() < deadline:
            observed = self._observe()
            if observed.screen in targets:
                stable = stable + 1 if observed.screen == last else 1
                if stable >= 2:
                    reached = observed
                    break
            else:
                stable = 0
            last = observed.screen
            if (action in REPLAYABLE_ACTIONS and observed.screen == source and
                    self.clock() - sent_at >= 5):
                raise RuntimeError(f"{action} remained on {source}; saved intent will be reconciled")
            self.nav.pause(.25)
        if reached is None:
            error = RuntimeError if action in REPLAYABLE_ACTIONS else DeliveryInputUncertain
            raise error(f"Tokyo {action} did not reach {sorted(targets)}; "
                        "saved intent retained, no button repeated")
        return self._verify_transition(new_pending, reached)

    def _map_job(self, current):
        import pyautogui

        def card_verified(candidate):
            map_visible = candidate.screen == "map" or (
                candidate.doc.has("Close Map", (120, 950, 500, 100),
                                  contains=True) and
                candidate.doc.has("Fast Travel", (300, 950, 350, 100),
                                  contains=True))
            if not map_visible:
                return False
            text = _document_text(candidate.doc)
            if "tokyo city food delivery" not in text and hasattr(
                    self.nav.reader, "read"):
                # The full frame can omit the second title line. The fixed
                # title crop reads all three lines from a settled job card.
                title = self.nav.reader.read(
                    candidate.native.frame[415:530, 520:950])
                text += " " + _document_text(title)
            return "tokyo city food delivery" in text and "job" in text

        verified = current if card_verified(current) else None
        if verified is not None:
            self._save(event=dict(kind="MAP_JOB_VERIFIED", source="visible_card"))
        else:
            candidates = job_icon_candidates(current.native.frame)
            if not candidates:
                # Any map card hides other icons. Move over blank sea, then
                # observe the uncovered icons before deciding the job is gone.
                pyautogui.moveTo(self.nav.monitor["left"] + 1850,
                                 self.nav.monitor["top"] + 500, duration=0)
                self.nav.pause(.8)
                current = self._observe()
                candidates = job_icon_candidates(current.native.frame)
            if not candidates:
                raise RuntimeError("Tokyo job icon is not visible on this map; no map selection guessed")
            for x, y in candidates:
                self._check()
                pyautogui.moveTo(self.nav.monitor["left"] + x,
                                 self.nav.monitor["top"] + y, duration=0)
                self.nav.pause(.8)
                for attempt in range(2):
                    candidate = self._observe()
                    if card_verified(candidate):
                        verified = candidate
                        self._save(event=dict(kind="MAP_JOB_VERIFIED", x=x, y=y))
                        break
                    if attempt == 0 and candidate.screen == "map":
                        self.nav.pause(.5)
                if verified is not None:
                    break
            if verified is None:
                raise RuntimeError("Map icons were checked; Tokyo City Food Delivery was not verified")
        return self._transition(verified, action="fast_travel", source="map",
                                targets={"fast_confirm", "intro", "roam"},
                                send=lambda: self.pad.pulse("x"), timeout=30)

    def _leave_home(self):
        from .navigation import LEFT
        self._save(event=dict(kind="HOME_EXIT_INTENT"))
        self.nav.home_tab("campaign")
        self.nav.click_label("campaign", "Drive", LEFT)
        current = self._wait({"roam", "intro"}, timeout=65)
        self._save(event=dict(kind="HOME_EXIT_VERIFIED", reached=current.screen))
        return current

    def _leave_journal(self, current):
        """Back out one observed menu level; every step is checkpointed."""
        targets = {
            "job_journal": {"discover", "journal", "collection_grid", "home", "roam"},
            "collection_grid": {"discover", "journal", "home", "roam"},
            "discover": {"journal", "home", "roam"},
            "journal": {"home", "roam"},
        }
        return self._transition(current, action="journal_back_" + current.screen,
                                source=current.screen, targets=targets[current.screen],
                                send=lambda: self.nav.key("esc"), timeout=20)

    def _leave_pause(self, current):
        return self._transition(current, action="leave_pause", source="pause_menu",
                                targets={"roam", "home", "active"},
                                send=lambda: self.nav.key("esc"), timeout=20)

    def _dismiss_controller_modal(self, current):
        """Dismiss the exact native reconnect prompt once, after pad creation.

        A saved Enter intent is never replayed.  This state is independent of
        a pending job/menu input, so the original transaction is reconciled
        only after the reconnect prompt has disappeared.
        """
        if current.screen != "controller_disconnected":
            return current
        self._check()
        intent = self.data.get("reconnect_intent")
        if not intent:
            fresh = self._observe()
            if fresh.screen != "controller_disconnected":
                if fresh.screen in PLAYABLE_JOB_SCREENS:
                    return fresh
                raise DeliveryEvidenceUncertain(
                    "Controller reconnect prompt was not stable; no Enter sent")
            self._save(event=dict(kind="CONTROLLER_RECONNECT_INTENT",
                                  attempt_id=self.data["attempt_id"]),
                       reconnect_intent=dict(at=_utc_now(),
                                             attempt_id=self.data["attempt_id"]))
            self._check()
            self.nav.key("enter")
        try:
            reached = self._wait(PLAYABLE_JOB_SCREENS, timeout=15)
        except RuntimeError as exc:
            raise DeliveryInputUncertain(
                "Controller reconnect Enter may have been accepted; "
                "saved intent retained, no key repeated") from exc
        self._save(event=dict(kind="CONTROLLER_RECONNECT_VERIFIED",
                              reached=reached.screen), reconnect_intent=None)
        return reached

    def _ensure_auto_drive(self, current):
        """Enable ANNA Auto Drive once per waypoint from visible native UI."""
        if current.screen != "active":
            return current
        if self.data.get("route_follow_stage") in {"delivery", "native_steering"}:
            return current
        if auto_drive_on(current.doc):
            if not self.data.get("auto_drive_verified"):
                self._save(event=dict(kind="AUTO_DRIVE_ON_VERIFIED",
                                      distance_m=current.distance_m),
                           auto_drive_verified=True)
            return current
        if self.data.get("auto_drive_verified"):
            if auto_drive_off(current.doc):
                if (_prompt_stage(current.prompt) == "delivery" and
                        self._native_auto_steering_enabled()):
                    self._save(event=dict(kind="AUTO_DRIVE_OFF_NATIVE_STEERING",
                                          distance_m=current.distance_m),
                               route_follow_stage="native_steering",
                               auto_drive_verified=False)
                    return current
                raise DeliveryEvidenceUncertain(
                    "Auto Drive visibly turned off during the active waypoint")
            # The HUD status can be covered by other notifications.  Prior
            # proof allows observation only; the progress gate below will
            # stop if the car is no longer following the route.
            return current
        if (_prompt_stage(current.prompt) == "delivery" and
                current.distance_m is not None and current.distance_m > 20 and
                self._native_auto_steering_enabled()):
            self._save(event=dict(kind="NATIVE_AUTO_STEERING_SELECTED",
                                  distance_m=current.distance_m),
                       route_follow_stage="native_steering")
            return current
        # During the timed delivery leg ANNA can cover the route and omit its
        # Auto Drive option. Prefer a verified road cue before opening ANNA;
        # otherwise the overlay itself makes the cue unreadable.
        if (_prompt_stage(current.prompt) == "delivery" and
                current.distance_m is not None and current.distance_m > 20):
            from .delivery_route import route_cue
            cue = route_cue(current.native.frame)
            if cue is not None and guided_route_action(cue, None) is not None:
                self._save(event=dict(kind="VISIBLE_ROUTE_FOLLOW",
                                      distance_m=current.distance_m,
                                      cue_confidence=round(cue.confidence, 3)),
                           route_follow_stage="delivery")
                return current
        if int(self.data.get("auto_drive_attempts", 0)) >= 1:
            raise DeliveryInputUncertain(
                "Auto Drive enable input remains uncertain; no Dpad repeated")
        menu = current
        if not auto_drive_off(menu.doc):
            self.pad.pulse("down")
            self.nav.pause(.35)
            menu = self._observe()
        if menu.screen != "active":
            return menu
        for _ in range(8):
            if auto_drive_on(menu.doc) or auto_drive_off(menu.doc):
                break
            self.nav.pause(.3)
            menu = self._observe()
            if menu.screen != "active":
                return menu
        doc = menu.doc
        if not (auto_drive_on(doc) or auto_drive_off(doc)) and hasattr(
                self.nav.reader, "refine_region"):
            doc = self.nav.reader.refine_region(
                menu.native.frame, doc, (300, 800, 360, 205))
        if auto_drive_on(doc) and auto_drive_off(doc):
            raise DeliveryEvidenceUncertain(
                "ANNA showed conflicting Auto Drive options; no selection sent")
        if auto_drive_on(doc):
            self._save(event=dict(kind="AUTO_DRIVE_ON_VERIFIED",
                                  distance_m=menu.distance_m),
                       auto_drive_verified=True)
            return menu
        if not doc.has("Enable Auto Drive", (310, 830, 335, 95),
                       contains=True):
            from .delivery_route import route_cue
            if (_prompt_stage(menu.prompt) == "delivery" and
                    menu.distance_m is not None and menu.distance_m > 20 and
                    (cue := route_cue(menu.native.frame)) is not None and
                    guided_route_action(cue, None) is not None):
                self._save(event=dict(kind="AUTO_DRIVE_UNAVAILABLE_ROUTE_FOLLOW",
                                      distance_m=menu.distance_m,
                                      cue_confidence=round(cue.confidence, 3)),
                           route_follow_stage="delivery")
                return menu
            raise DeliveryEvidenceUncertain(
                "ANNA Enable Auto Drive option was not verified; no selection sent")
        self._save(event=dict(kind="AUTO_DRIVE_ENABLE_INTENT",
                              distance_m=menu.distance_m,
                              attempt_id=self.data["attempt_id"]),
                   auto_drive_attempts=1)
        self.pad.pulse("left")
        deadline = self.clock() + 6
        stable_on = 0
        while self.clock() < deadline:
            seen = self._observe()
            if seen.screen != "active":
                return seen
            stable_on = stable_on + 1 if auto_drive_on(seen.doc) else 0
            if stable_on >= 2:
                self._save(event=dict(kind="AUTO_DRIVE_ON_VERIFIED",
                                      distance_m=seen.distance_m),
                           auto_drive_verified=True)
                return seen
            self.nav.pause(.3)
        raise DeliveryInputUncertain(
            "Auto Drive enable may have been accepted; saved intent retained, "
            "no Dpad repeated")

    def _save_evidence(self, frame, label):
        folder = self.root / "tokyo_delivery"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.data['id']}_{self.data['attempt_id']}_{label}.png"
        temporary = path.with_suffix(".png.tmp")
        ok, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        if not ok:
            raise RuntimeError("Could not encode Tokyo Delivery evidence")
        temporary.write_bytes(encoded.tobytes())
        temporary.replace(path)
        return str(path.resolve())

    def _summary(self, current):
        if self.data.get("summary_processed"):
            return
        stable = self._wait({"summary"}, timeout=5)
        if stable.failed != current.failed:
            raise RuntimeError("Tokyo summary failure evidence changed between fresh frames")
        evidence = self._save_evidence(stable.native.frame, "summary")
        if not self.data.get("attempt_seen_active"):
            self._save(event=dict(kind="PREEXISTING_SUMMARY_SKIPPED", evidence=evidence),
                       summary_processed=True, phase="summary")
            return
        before = self.data.get("progress_before")
        credit_progress = (before is not None and stable.progress is not None
                           and stable.progress > before)
        success = (not stable.failed and stable.shift_stars is not None and
                   stable.shift_stars > 0 and stable.shift_progress is not None and
                   stable.shift_progress > int(self.data.get("shift_progress", 0)))
        if stable.failed:
            failures = self.data.get("failed_shifts", 0) + 1
            consecutive = self.data.get("consecutive_failures", 0) + 1
            self._save(event=dict(kind="SHIFT_FAILED", evidence=evidence),
                       summary_processed=True, failed_shifts=failures,
                       consecutive_failures=consecutive, phase="summary")
            self.emit("status", f"Tokyo shift failed; {self.data['completed']} verified completed")
            return
        if not success:
            self._save(event=dict(kind="SUMMARY_UNVERIFIED", evidence=evidence,
                                  shift_stars=stable.shift_stars,
                                  shift_progress=stable.shift_progress,
                                  progress_before=before, progress_after=stable.progress,
                                  credit_progress=credit_progress),
                       phase="summary_unverified")
            raise DeliveryEvidenceUncertain(
                "Tokyo summary lacks new positive Shift Stars and 1/3–3/3 proof; no shift counted")
        if stable.shift_progress < 3:
            self._save(event=dict(kind="PARTIAL_SHIFT_VERIFIED", evidence=evidence,
                                  shift_stars=stable.shift_stars,
                                  shift_progress=stable.shift_progress),
                       shift_progress=stable.shift_progress,
                       summary_processed=True, phase="summary")
            self.emit("status", f"Tokyo shift: {stable.shift_progress}/3 deliveries verified")
            return
        completed = self.data["completed"] + 1
        phase = "complete" if completed >= self.data["limit"] else "summary"
        self._save(event=dict(kind="SHIFT_VERIFIED", evidence=evidence,
                              shift_stars=stable.shift_stars,
                              shift_progress=stable.shift_progress,
                              progress_before=before, progress_after=stable.progress,
                              credit_progress=credit_progress),
                   completed=completed, consecutive_failures=0,
                   shift_progress=3,
                   summary_processed=True, phase=phase)
        self.emit("status", f"Tokyo Delivery: {completed}/{self.data['limit']} verified shifts")

    def _stall_recovery_reserved(self):
        """Preserve one recovery per shift, including older checkpoint schemas."""
        if self.data.get("stall_recovery_used"):
            return True
        attempt_id = self.data.get("attempt_id")
        for event in reversed(self.data.get("history", [])):
            if event.get("kind") == "STALL_RECOVERY_INTENT":
                if event.get("attempt_id") in (None, attempt_id):
                    return True
            if (event.get("kind") == "SESSION_STARTED" or
                    event.get("kind") == "NEXT_ACTIVE_SHIFT_RECONCILED" or
                    event.get("kind") == "INPUT_VERIFIED" and
                    event.get("action") == "new_shift"):
                break
        return False

    def _drive_shift(self, first):
        from .delivery_route import route_cue
        from .farm_motion import speed_from_frame, scene_is_moving

        recovery_used = self._stall_recovery_reserved()
        self._save(event=dict(kind="ACTIVE_SHIFT_VERIFIED"), phase="active",
                   attempt_seen_active=True, stall_recovery_used=recovery_used)
        started = self.clock()
        previous_distance = None
        rise_candidate = None
        previous_frame = None
        last_progress_at = started
        last_checkpoint_at = started
        missing_distance = 0
        missing_route_frames = 0
        stationary_since = None
        pace_anchor_distance = None
        pace_anchor_at = None
        parking_waits = 0
        current = first
        while self.clock() - started < ACTIVE_WALL_LIMIT_SECONDS:
            self._check()
            if current.screen == "summary":
                return current
            if current.screen == "controller_disconnected":
                current = self._dismiss_controller_modal(current)
                continue
            if current.screen != "active":
                current = self._wait(
                    {"active", "summary", "controller_disconnected"}, timeout=12)
                continue
            now = self.clock()
            if current.prompt and current.prompt != self.data.get("last_prompt"):
                prior_stage = self.data.get("prompt_stage") or _prompt_stage(
                    self.data.get("last_prompt", ""))
                observed_stage = _prompt_stage(current.prompt)
                stage_changed = (prior_stage is not None and
                                 observed_stage is not None and
                                 prior_stage != observed_stage)
                changes = {"last_prompt": current.prompt}
                if observed_stage is not None:
                    changes["prompt_stage"] = observed_stage
                if stage_changed:
                    # The restaurant handoff may switch Auto Drive off.  A
                    # verified new objective permits one new guarded enable.
                    changes.update(parking_nudges=0, parking_brakes=0,
                                   auto_drive_verified=False,
                                   auto_drive_attempts=0,
                                   route_follow_stage=None)
                    previous_distance = None
                    rise_candidate = None
                    parking_waits = 0
                    last_progress_at = now
                    stationary_since = None
                    pace_anchor_distance = None
                    pace_anchor_at = None
                self._save(event=dict(kind="JOB_STAGE_CHANGED" if stage_changed else
                                      "JOB_PROMPT", prompt=current.prompt,
                                      from_stage=prior_stage,
                                      to_stage=observed_stage), **changes)
            if current.remaining_s is not None and current.remaining_s <= .5:
                self.pad.neutral()
                return self._wait({"summary"}, timeout=25)
            if current.distance_m is None:
                missing_distance += 1
            else:
                missing_distance = 0
                if previous_distance is None or current.distance_m < previous_distance - 4:
                    last_progress_at = now
                    previous_distance = current.distance_m
                    rise_candidate = None
                elif ((previous_distance <= 50 or next_drop_off_announced(current.doc))
                      and current.distance_m > previous_distance + 80):
                    self._save(event=dict(kind="NEXT_WAYPOINT_VERIFIED",
                                          prior_distance_m=previous_distance,
                                          distance_m=current.distance_m,
                                          anna_confirmed=next_drop_off_announced(current.doc)),
                               parking_nudges=0, parking_brakes=0)
                    previous_distance = current.distance_m
                    rise_candidate = None
                    last_progress_at = now
                    parking_waits = 0
                elif (current.distance_m > previous_distance + 80 or
                      previous_distance <= 20 and current.distance_m > previous_distance + 8):
                    # A new drop-off or route recalculation may appear before
                    # ANNA's text is captured. Confirm a large increase on a
                    # second fresh HUD frame before changing the baseline;
                    # a single OCR glitch never stops guided Auto Drive.
                    if (rise_candidate is not None and
                            abs(current.distance_m - rise_candidate) <=
                            max(50, rise_candidate * .3)):
                        self._save(event=dict(kind="ROUTE_DISTANCE_REBASED",
                                              prior_distance_m=previous_distance,
                                              distance_m=current.distance_m))
                        previous_distance = current.distance_m
                        rise_candidate = None
                        last_progress_at = now
                        parking_waits = 0
                    else:
                        rise_candidate = current.distance_m
                if now - last_checkpoint_at >= 15:
                    self._save(event=dict(kind="DRIVE_PROGRESS",
                                          distance_m=current.distance_m,
                                          remaining_s=current.remaining_s))
                    last_checkpoint_at = now
            if missing_distance >= 4:
                raise RuntimeError("Tokyo route distance unreadable on four fresh frames; driving stopped")
            speed = speed_from_frame(self.nav.reader, current.native.frame)
            moving = scene_is_moving(previous_frame, current.native.frame)
            if (_prompt_stage(current.prompt) == "delivery" and
                    self.data.get("auto_drive_verified") and
                    self.data.get("route_follow_stage") != "native_steering" and
                    self._native_auto_steering_enabled() and
                    current.distance_m is not None and current.distance_m > 20 and
                    current.remaining_s is not None and current.remaining_s > 8):
                if (pace_anchor_distance is None or
                        current.distance_m > pace_anchor_distance + 100):
                    pace_anchor_distance = current.distance_m
                    pace_anchor_at = now
                elif now - pace_anchor_at >= 15:
                    actual_rate = max(0, pace_anchor_distance - current.distance_m) / (now - pace_anchor_at)
                    required_rate = current.distance_m / (current.remaining_s - 8)
                    if actual_rate < required_rate * .8:
                        evidence = self._save_evidence(
                            current.native.frame, f"auto_drive_pace_{round(current.distance_m)}")
                        self._save(event=dict(kind="AUTO_DRIVE_PACE_TAKEOVER",
                                              distance_m=current.distance_m,
                                              remaining_s=current.remaining_s,
                                              actual_mps=round(actual_rate, 2),
                                              required_mps=round(required_rate, 2),
                                              evidence=evidence),
                                   route_follow_stage="native_steering",
                                   auto_drive_verified=False)
                    pace_anchor_distance = current.distance_m
                    pace_anchor_at = now
            if current.distance_m is not None and current.distance_m <= 20:
                # At the parking trigger, reverse input can pull the truck
                # away from the target.  Brake only while measured speed is
                # above a low threshold, then release controls and wait for
                # the game's next stage.  A forward approach requires a
                # visible route and is reserved before input; it cannot be
                # repeated without bound across worker restarts.
                brakes = int(self.data.get("parking_brakes", 0))
                if speed is not None and speed > 6 and brakes < MAX_PARKING_BRAKES:
                    self._save(event=dict(kind="PARKING_BRAKE_INTENT",
                                          number=brakes + 1,
                                          distance_m=current.distance_m,
                                          speed_kmh=speed),
                               parking_brakes=brakes + 1)
                    self.pad.drive(-.25, 0, .2)
                    parking_waits = 0
                else:
                    self.pad.neutral()
                    self.nav.pause(.75)
                    parking_waits += 1
                    cue = route_cue(current.native.frame)
                    ready_to_nudge = (speed is not None and speed <= 2 or
                                      speed is None and moving is False)
                    nudges = int(self.data.get("parking_nudges", 0))
                    if (parking_waits >= 2 and ready_to_nudge and
                            cue is not None and cue.confidence >= .65 and
                            nudges < MAX_PARKING_NUDGES):
                        self._save(event=dict(kind="PARKING_NUDGE_INTENT",
                                              number=nudges + 1,
                                              distance_m=current.distance_m),
                                   parking_nudges=nudges + 1)
                        self.pad.drive(.18, max(-.15, min(.15, cue.steer)), .3)
                        parking_waits = 0
                    elif parking_waits >= 8:
                        raise RuntimeError(
                            "Tokyo parking trigger did not activate after bounded approach; driving stopped")
                previous_frame = current.native.frame
                current = self._observe()
                continue
            was_verified = bool(self.data.get("auto_drive_verified"))
            current = self._ensure_auto_drive(current)
            if self.data.get("route_follow_stage") == "native_steering" and current.screen == "active":
                if speed is not None and speed <= 2 or moving is False:
                    if stationary_since is None:
                        stationary_since = now
                else:
                    stationary_since = None
                if stationary_since is not None and now - stationary_since >= 8:
                    self.pad.neutral()
                    raise DeliveryEvidenceUncertain(
                        "Native Auto-Steering stayed stationary; driving stopped")
                if now - last_progress_at >= 30:
                    self.pad.neutral()
                    raise DeliveryEvidenceUncertain(
                        "Native Auto-Steering did not reduce route distance")
                self._save(event=dict(kind="NATIVE_STEERING_DRIVE_INTENT",
                                      distance_m=current.distance_m,
                                      speed_kmh=speed))
                self.pad.drive(.62, 0, .4)
                previous_frame = current.native.frame
                current = self._observe()
                continue
            if self.data.get("route_follow_stage") == "delivery" and current.screen == "active":
                cue = route_cue(current.native.frame)
                action = guided_route_action(cue, speed)
                if action is None:
                    self.pad.neutral()
                    missing_route_frames += 1
                    if missing_route_frames >= 3:
                        evidence = self._save_evidence(current.native.frame,
                                                       "route_lost")
                        self._save(event=dict(kind="ROUTE_CUE_LOST",
                                              evidence=evidence,
                                              distance_m=current.distance_m))
                        raise DeliveryEvidenceUncertain(
                            "Tokyo route chevrons are not clear enough for guided driving")
                    self.nav.pause(.35)
                    current = self._observe()
                    continue
                missing_route_frames = 0
                if now - last_progress_at >= 25:
                    self.pad.neutral()
                    raise DeliveryEvidenceUncertain(
                        "Tokyo guided driving did not reduce route distance")
                throttle, steer, seconds = action
                self._save(event=dict(kind="GUIDED_DRIVE_INTENT",
                                      distance_m=current.distance_m,
                                      speed_kmh=speed,
                                      steer=round(steer, 3)))
                self.pad.drive(throttle, steer, seconds)
                previous_frame = current.native.frame
                current = self._observe()
                continue
            if current.screen != "active" or not was_verified:
                last_progress_at = self.clock()
                previous_frame = current.native.frame
                continue
            if auto_drive_needs_route(current.doc):
                self.pad.neutral()
                self._save(event=dict(kind="AUTO_DRIVE_ROUTE_REQUIRED",
                                      distance_m=current.distance_m))
                raise DeliveryEvidenceUncertain(
                    "Auto Drive is on but FH6 asks to set a route; no blind driving sent")
            no_progress_limit = 45 if (current.distance_m or 0) > 1000 else 25
            if now - last_progress_at >= no_progress_limit:
                self.pad.neutral()
                self._save(event=dict(kind="AUTO_DRIVE_NO_PROGRESS",
                                      distance_m=current.distance_m,
                                      speed_kmh=speed,
                                      seconds=round(now - last_progress_at, 1)))
                raise DeliveryEvidenceUncertain(
                    "Auto Drive did not reduce the native route distance; driving stopped")
            self.pad.neutral()
            self.nav.pause(1)
            previous_frame = current.native.frame
            current = self._observe()
        raise RuntimeError("Tokyo shift exceeded eleven minutes without a verified summary")

    def run(self, limit):
        """Resume the visible job state; never replay a summary or purchase."""
        self._load(int(limit) if type(limit) is int else limit)
        if self.pad_factory is None:
            from .tokyo_delivery_control import GuardedPad
            self.pad_factory = GuardedPad
        self.pad = self.pad_factory(guard=self.nav.check)
        try:
            self.emit("activity", True)
            while self.running.is_set():
                if self.data["completed"] >= self.data["limit"]:
                    self._save(phase="complete")
                    self.emit("status", f"Tokyo Delivery complete: {self.data['completed']} verified shifts")
                    return
                current = self._wait(PLAYABLE_JOB_SCREENS |
                                     {"controller_disconnected"}, timeout=75)
                if current.screen == "controller_disconnected":
                    current = self._dismiss_controller_modal(current)
                elif self.data.get("reconnect_intent"):
                    self._save(event=dict(kind="CONTROLLER_RECONNECT_VERIFIED",
                                          reached=current.screen),
                               reconnect_intent=None)
                if not self._keyboard_ready:
                    from .keyboard_layout import ensure_game_keyboard
                    ensure_game_keyboard(self.nav)
                    self._keyboard_ready = True
                current = self._reconcile_pending(current)
                self.emit("stage", "tokyo_" + current.screen)
                if current.screen == "summary":
                    self._summary(current)
                    if self.data["completed"] >= self.data["limit"]:
                        continue
                    if self.data.get("consecutive_failures", 0) >= MAX_FAILED_SHIFTS:
                        raise RuntimeError(
                            f"{MAX_FAILED_SHIFTS} consecutive Tokyo shifts failed; checkpoint retained")
                    self._transition(current, action="new_shift", source="summary",
                                     targets={"intro", "active"},
                                     send=lambda: self.pad.pulse("a"), timeout=90)
                elif current.screen == "active":
                    if self.data.get("summary_processed"):
                        self._save(event=dict(kind="NEXT_ACTIVE_SHIFT_RECONCILED"),
                                   attempt_id=uuid.uuid4().hex, summary_processed=False,
                                   phase="active", shift_progress=0,
                                   drive_steps=0, last_prompt="",
                                   prompt_stage=None,
                                   stall_recovery_used=False, parking_nudges=0,
                                   parking_brakes=0, auto_drive_attempts=0,
                                   auto_drive_verified=False,
                                   route_follow_stage=None)
                    self._drive_shift(current)
                elif current.screen == "solo":
                    if current.progress is not None:
                        self._save(progress_before=current.progress)
                    self._transition(current, action="solo", source="solo",
                                     targets={"intro", "active"},
                                     send=lambda: self.pad.pulse("a"), timeout=90)
                elif current.screen == "intro":
                    self._transition(current, action="continue", source="intro",
                                     targets={"solo", "active"},
                                     send=lambda: self.pad.pulse("x"), timeout=50)
                elif current.screen == "fast_confirm":
                    self._transition(current, action="fast_confirm", source="fast_confirm",
                                     targets={"roam", "intro"},
                                     send=lambda: self.pad.pulse("a"), timeout=90)
                elif current.screen == "map":
                    self._map_job(current)
                elif current.screen == "roam":
                    self._transition(current, action="open_map", source="roam",
                                     targets={"map"}, send=lambda: self.nav.key("m"), timeout=15)
                elif current.screen == "home":
                    self._leave_home()
                elif current.screen == "pause_menu":
                    self._leave_pause(current)
                elif current.screen in {"job_journal", "journal", "discover", "collection_grid"}:
                    self._leave_journal(current)
        finally:
            try:
                self.pad.neutral()
            finally:
                if self.data and self._last_accounted_at is not None:
                    try:
                        # Account for the final interval when F7 or an error
                        # ends the worker between periodic drive checkpoints.
                        self._save()
                    except Exception as exc:
                        self.emit("log", f"Tokyo timing checkpoint failed: {exc}")
                self.emit("activity", False)
