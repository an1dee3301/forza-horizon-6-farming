"""Wheelspin Lab policy and guarded action primitives.

The live state machine is intentionally dry-run gated until calibrated reward
and duplicate screenshots pass.  This module owns policy; it never delegates
sell/keep decisions to the legacy AHK macro.
"""
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import time

import cv2

import forza_cycle as core

from .ocr import normalize
from .wheelspin_catalog import identify_protected
from .wheelspin_history import WheelspinStore
from .wheelspin_recognition import (capture_reward_observation,
                                    read_reward_observation, stable_rewards)
from .wheelspin_catalog import normalize_car_text, user_keep_match
import re
from collections import Counter


MODE = "Wheelspin Lab"
AUTO_ACTIONS_SETTING = "wheelspin_auto_actions_enabled"


def protected_keep_match(value):
    return user_keep_match(value)


def match_dialog_reward(dialog_name, rows):
    """Match a native duplicate name to its committed reward card.

    Duplicate prompts are not guaranteed to follow slot order.  A one-car
    result is unambiguous; multi-car results require a unique shared model
    token before any destructive decision is allowed.
    """
    rows = list(rows)
    if len(rows) == 1:
        return rows[0], 1.0
    dialog = normalize_car_text(dialog_name)
    ignored = {"CAR", "THE", "AND", "FORZA", "EDITION", "FE", "M", "B"}
    def tokens(value):
        return {token for token in normalize_car_text(value).split()
                if token not in ignored and not re.fullmatch(r"(?:19|20)?\d{2}", token)
                and (len(token) >= 3 or any(ch.isdigit() for ch in token))}
    target = tokens(dialog)
    scored = []
    for row in rows:
        # raw_ocr is immutable reward-screen evidence. Identity columns can
        # contain a prior bad dialog association and must not influence a
        # recovery decision.
        evidence = str(row.get("raw_ocr") or "")
        candidate = normalize_car_text(evidence)
        overlap = target & tokens(candidate)
        score = len(overlap) * 10
        if dialog and (f" {dialog} " in f" {candidate} " or
                       f" {candidate} " in f" {dialog} "):
            score += 100
        score += sum(min(8, len(token)) for token in overlap)
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] <= 0 or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None, 0.0
    return scored[0][1], 1.0


def read_sell_value(frame, reader):
    """Read the native Sell-for amount with multi-view consensus."""
    crop = frame[815:905, 620:1300]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    variants = [crop]
    for channel, thresholds in (
            (gray, (100, 120, 140)),
            (crop[:, :, 2], (120, 140, 160)),
            (cv2.normalize(crop[:, :, 0], None, 0, 255, cv2.NORM_MINMAX), (160, 180))):
        for threshold in thresholds:
            binary = cv2.threshold(channel, threshold, 255, cv2.THRESH_BINARY)[1]
            variants.append(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR))
    values = []
    for image in variants:
        text = " ".join(line.text for line in reader.read(image).lines).upper().replace("O", "0")
        match = re.search(r"SELL\s*F0R\s*[^0-9]*([0-9][0-9., ]{2,})", text)
        if not match:
            continue
        digits = re.sub(r"\D", "", match.group(1)).lstrip("0") or "0"
        value = int(digits)
        if 1_000 <= value <= 100_000_000:
            values.append(value)
    if not values:
        return None
    value, count = Counter(values).most_common(1)[0]
    return value if count >= 2 else None


@dataclass(frozen=True)
class Decision:
    action: str
    confidence: float
    send_input: bool
    reason: str


class WheelspinPolicy:
    def __init__(self, threshold=.97):
        self.threshold = threshold

    def decide(self, reward):
        if reward.get("reward_type") != "CAR" or reward.get("duplicate") is not True:
            return Decision("AUTO_ADDED", 1.0, False, "No duplicate action exists")
        confidence = float(reward.get("decision_confidence") or 0)
        protected = reward.get("protected")
        if confidence < self.threshold or protected not in {True, False}:
            return Decision("UNKNOWN_DECISION", confidence, False,
                            "Exact year, manufacturer and model were not proven")
        if protected:
            return Decision("KEEP", confidence, True, "Protected Wheelspin, Seasonal catalog match")
        return Decision("SELL", confidence, True, "Confident non-protected duplicate")


def guarded_action(running, focus_ok, sender):
    if not running.is_set():
        raise RuntimeError("F7 stopped Wheelspin Lab before input")
    guard = getattr(running, "input_guard", None)
    if callable(guard):
        guard()
    if not focus_ok():
        raise RuntimeError("Game focus lost; Wheelspin Lab paused before input")
    sender()


class WheelspinLab:
    """Current-controller Wheelspin worker; legacy Mode_Spin.ahk is not used."""
    def __init__(self, nav, running, emit=lambda *a: None, root=core.BASE / "runs"):
        self.nav, self.running, self.emit = nav, running, emit
        self.root = Path(root)
        self.store = WheelspinStore(self.root / "wheelspin_lab.sqlite")
        self.policy = WheelspinPolicy()

    def _settings(self):
        path = self.root / "wheelspin_lab_settings.json"
        if not path.exists():
            path.write_text(json.dumps({AUTO_ACTIONS_SETTING: False,
                "activation_requirements": ["offline_tests", "target_screens", "non_target_screens",
                    "ambiguous_pause", "manual_dry_run"]}, indent=2), encoding="utf-8")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {AUTO_ACTIONS_SETTING: False}

    def _progress(self, session_id):
        session = self.store.session(session_id)
        self.emit("progress", dict(id=session_id, mode=MODE, phase=session["status"].casefold(),
            completed=session["completed_spins"], rewards=session["completed_spins"], bought=0,
            limit=session["requested_spins"], active_seconds=0, farm_runs=0))

    def _focus_spin_tile(self, spin_type):
        obs = self.nav.observe()
        if obs.screen == "wheelspin_menu":
            return obs
        if obs.screen == "wheelspin_reward":
            return obs
        if self.nav.is_home(obs):
            from .navigation import LEFT
            self.nav.home_tab("campaign")
            self.nav.click_label("campaign", "Drive", LEFT)
            self.nav.until(self.nav.is_roam, "leaving home for Wheelspin Lab", timeout=max(60, self.nav.timeout))
            obs = self.nav.last
        if self.nav.is_roam(obs):
            self.nav.open_pause_menu("pause menu for Wheelspin Lab")
        elif not self.nav.is_pause(obs):
            raise RuntimeError(f"Wheelspin Lab needs Home, free roam or Pause; found {obs.screen}")
        self.nav.pause_tab("MY HORIZON")
        # Windows OCR returns the tall tiles as two independent lines
        # ("Super" + "Wheelspin").  Prove the whole fixed My Horizon layout,
        # then move once from its central Return Home tile and verify that the
        # lime focus border encloses the requested side tile before Enter.
        from .navigation import focus_boxes
        def tile_ready(item):
            if not self.nav.is_pause(item):
                return False
            region = (220, 255, 330, 590) if spin_type == "SUPER" else (1380, 255, 320, 590)
            needed = ("Super", "Wheelspin") if spin_type == "SUPER" else ("Wheelspin",)
            return all(item.doc.has(word, region) for word in needed)
        def tile_focused(item):
            if not tile_ready(item):
                return False
            boxes = focus_boxes(item.frame)
            if len(boxes) != 1:
                return False
            x, y, w, h = boxes[0]
            return (x < 550 and x+w < 620 and y < 330 and y+h > 760) if spin_type == "SUPER" else (
                    x > 1350 and x+w > 1650 and y < 330 and y+h > 700)
        obs = self.nav.until(tile_ready, f"{spin_type} Wheelspin tile")
        # On return from a prior reward the requested tile can retain focus.
        # Do not move it away and burn a five-second timeout.
        if tile_focused(obs):
            return obs
        self.nav.key("left" if spin_type == "SUPER" else "right")
        self.nav.until(tile_focused, f"focused {spin_type} Wheelspin tile", timeout=5)
        return self.nav.last

    def _resolved(self, spin_type, timeout=35, pending_spin_id=None, dry_run=False):
        observations = []
        deadline = time.monotonic() + timeout
        skip_attempts = 0
        last_skip = 0.0
        unknown_since = None
        while time.monotonic() < deadline:
            obs = self.nav.observe()
            if obs.screen == "wheelspin_duplicate":
                if not pending_spin_id:
                    raise RuntimeError("Duplicate dialog has no committed source spin; no input sent")
                self._duplicate(pending_spin_id, obs, dry_run)
                continue
            text = normalize(" ".join(line.text for line in obs.doc.lines))
            now = time.monotonic()
            unknown_since = (unknown_since or now) if obs.screen == "unknown" else None
            skip_ready = (" skip " in f" {text} " or
                          unknown_since is not None and now - unknown_since >= .65)
            if (skip_ready and
                    skip_attempts < 5 and now - last_skip >= .35):
                self.nav.key("enter")
                skip_attempts += 1
                last_skip = now
                observations.clear()
                continue
            if obs.screen == "wheelspin_reward":
                rewards = read_reward_observation(obs.frame, self.nav.reader, spin_type)
                if (len(rewards) == (3 if spin_type == "SUPER" else 1) and
                        all(item.get("raw_ocr", "").strip() for item in rewards)):
                    return obs, rewards
            else:
                observations.clear()
            self.nav.pause(.08)
        raise RuntimeError("Resolved Wheelspin reward screen was not stable; no Collect input sent")

    def _restart_unresolved_spin(self, spin_type, observed):
        """Re-enter Wheelspin after a crash returned FH6 to a normal menu.

        A SPIN_STARTED row has no durable reward yet.  If recovery leaves the
        game at Home/Pause instead of the animation, reuse that checkpoint and
        start one replacement spin.  This keeps numbering monotonic and avoids
        blind Enter pulses on Campaign.
        """
        safe = (self.nav.is_home(observed) or self.nav.is_roam(observed) or
                self.nav.is_pause(observed) or observed.screen in {
                    "wheelspin_menu", "campaign", "cars", "home_tab",
                    "garage_grid", "car_select"})
        if not safe:
            return False
        if observed.screen in {"garage_grid", "car_select"}:
            self.nav.back_home()
        self.emit("status", "Crash recovered — returning to Super Wheelspin")
        self.emit("log", "Uncommitted spin had no visible reward after recovery; reopening the verified Wheelspin tile.")
        self._focus_spin_tile(spin_type)
        self.nav.key("enter")
        return True

    def _save_dialog(self, spin_id, frame):
        folder = self.root / "wheelspin_lab" / spin_id.split(":", 1)[0] / spin_id.replace(":", "_")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"duplicate_{datetime.now().strftime('%H%M%S_%f')}.png"
        temporary = path.with_suffix(".tmp")
        ok, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        if not ok:
            raise RuntimeError("Could not encode duplicate-dialog evidence")
        temporary.write_bytes(encoded.tobytes()); temporary.replace(path)
        return str(path.resolve())

    def _duplicate(self, spin_id, obs, dry_run):
        path = self._save_dialog(spin_id, obs.frame)
        raw = " ".join(line.text for line in obs.doc.lines)
        text = normalize_car_text(raw)
        match = re.search(r"THIS CAR\s+(.+?)\s+ADD TO GARAGE", text)
        dialog_name = match.group(1).strip() if match else text
        # Match the dialog identity to the committed card. FH6 can present
        # multiple duplicates in an order that differs from the three reels.
        # Slot-order association sold the CLK GTR in incident spin 262.
        rows = self.store.rewards(spin_id)
        # Credit/cosmetic slots are never candidates for a native duplicate
        # car dialog. Including a 200,000-CR slot here made the final car in a
        # multi-duplicate spin look ambiguous after the first car was sold.
        unresolved = [row for row in rows if not row.get("action_verified") and
                      row.get("duplicate") in {None, 1}]
        # A missed year often classifies a car as OTHER. Consider every
        # unresolved non-award text slot together and let native dialog/card
        # identity choose uniquely. Never prefer a nominal CAR row merely
        # because another real car was classified OTHER.
        non_car_awards = {"CREDITS", "CLOTHING", "HORN", "EMOTE", "COSMETIC"}
        candidates = [row for row in unresolved
                      if row.get("reward_type") not in non_car_awards and
                      not re.fullmatch(r"\s*(?:CR\s*)?[0-9O][0-9O,.\s]*\s*(?:CR)?\s*",
                                       str(row.get("raw_ocr") or "").upper())]
        if not candidates:
            # The same dialog can remain visible for a frame after Enter.
            # Never press the default Add-to-Garage row without a reward slot.
            self.store.event("DUPLICATE_DIALOG_RECORDED", spin_id, path=path, raw_ocr=raw)
            self.nav.pause(.12)
            return True
        reward, association_confidence = match_dialog_reward(dialog_name, candidates)
        if reward is None:
            raise RuntimeError(f"Duplicate car identity is ambiguous ({dialog_name}); Sell blocked")
        # Only current native-dialog text and immutable reward-card OCR may
        # drive the decision. display_name can contain a stale association
        # from a previously interrupted attempt.
        combined = f"{dialog_name} {reward.get('raw_ocr') or ''}"
        normalized_combined = normalize_car_text(combined)
        # The fast skip can capture the reward during Forza's white/gold
        # flash, making a gold card appear NEUTRAL.  Retaining every
        # Lamborghini is the only destructive-action-safe interpretation of
        # "keep every gold Lambo" without slowing every spin for the fade.
        lamborghini = any(name in normalized_combined
                          for name in ("LAMBORGHINI", "LAMBO"))
        keep = protected_keep_match(combined) or lamborghini
        action = "KEEP" if keep else "SELL"
        if reward.get("action_attempted") and not reward.get("action_verified"):
            self.store.clear_unaccepted_action(spin_id, reward["reward_id"],
                                               reward["action_attempted"], path)
        identity = dict(year=reward.get("year"), manufacturer=reward.get("manufacturer"),
                        model=reward.get("model") or dialog_name,
                        display_name=dialog_name,
                        protected=keep, wheelspin_exclusive=keep)
        self.store.associate_duplicate(spin_id, reward["reward_id"], identity,
                                       association_confidence, path)
        self.store.plan_decision(spin_id, reward["reward_id"], action,
                                 association_confidence, path)
        if action == "SELL":
            value = read_sell_value(obs.frame, self.nav.reader)
            if value is None:
                # Price is reporting data, not identity evidence. Never guess
                # it and never turn a cleanly identified non-protected car
                # into a permanent stall because Windows OCR missed digits.
                self.store.event("SELL_VALUE_UNREADABLE", spin_id,
                                 reward["reward_id"], evidence_path=path)
            else:
                self.store.set_sell_value(spin_id, reward["reward_id"], value)
        refreshed = next(row for row in self.store.rewards(spin_id)
                         if row["reward_id"] == reward["reward_id"])
        if refreshed.get("action_attempted") == action and not refreshed.get("action_verified"):
            self.store.clear_unaccepted_action(spin_id, reward["reward_id"], action, path)
        self.store.assert_action_allowed(spin_id, reward["reward_id"], action)
        from .navigation import focus_boxes
        def row_index(item):
            rows = [y for x, y, w, h in focus_boxes(item.frame)
                    if w > 500 and 690 <= y <= 900]
            if len(rows) != 1:
                return None
            return 0 if rows[0] < 770 else 1 if rows[0] < 825 else 2
        current = row_index(obs)
        if current is None:
            try:
                current = row_index(self.nav.until(lambda item: row_index(item) is not None,
                                                   "duplicate action focus", timeout=1.2))
            except RuntimeError:
                fresh = self.nav.observe()
                if fresh.screen != "wheelspin_duplicate":
                    return True
                # Normalize an unreadable focus to the clamped first row.
                self.nav.key("up")
                self.nav.key("up")
                current = 0
        target = 0 if keep else 2
        key = "up" if current > target else "down"
        for expected in range(current - 1, target - 1, -1) if current > target else range(current + 1, target + 1):
            self.nav.key(key)
            self.nav.until(lambda item, expected=expected: row_index(item) == expected,
                           f"duplicate row {expected + 1}", timeout=1.2)
        self.store.action_attempted(spin_id, reward["reward_id"], action)
        self.nav.key("enter")
        self.nav.until(lambda item: item.screen != "wheelspin_duplicate" or
                      dialog_name not in normalize_car_text(" ".join(line.text for line in item.doc.lines)),
                      f"duplicate {action.casefold()} accepted", timeout=5)
        self.store.action_verified(spin_id, reward["reward_id"], action)
        self.emit("log", f"Duplicate {action.casefold()}: {dialog_name}")
        return True

    def _finish_collect(self, spin_id, dry_run, spin_again=True):
        """Resolve duplicate dialogs and return the next stable reward."""
        deadline = time.monotonic() + max(40, self.nav.timeout)
        departed = False
        skip_attempts = 0
        last_skip = 0.0
        unknown_since = None
        duplicate_seen = False
        observations = []
        while time.monotonic() < deadline:
            after = self.nav.observe()
            if after.screen == "wheelspin_duplicate":
                self._duplicate(spin_id, after, dry_run)
                departed = True
                duplicate_seen = True
                unknown_since = None
                observations.clear()
                continue
            if after.screen != "wheelspin_reward":
                departed = True
                observations.clear()
                now = time.monotonic()
                unknown_since = (unknown_since or now) if after.screen == "unknown" else None
                text = normalize(" ".join(line.text for line in after.doc.lines))
                duplicate_grace = 1.50 if duplicate_seen else .65
                skip_ready = (" skip " in f" {text} " or
                              unknown_since is not None and
                              now - unknown_since >= duplicate_grace)
                if (spin_again and skip_ready and
                        skip_attempts < 5 and now - last_skip >= .35):
                    self.nav.key("enter")
                    skip_attempts += 1
                    last_skip = now
            elif departed and spin_again:
                unknown_since = None
                rewards = read_reward_observation(after.frame, self.nav.reader,
                                                  self.store.spin(spin_id)["spin_type"])
                expected = 3 if self.store.spin(spin_id)["spin_type"] == "SUPER" else 1
                if (len(rewards) == expected and
                        all(item.get("raw_ocr", "").strip() for item in rewards)):
                    self.store.complete_spin(spin_id)
                    return after, rewards
            elif departed and not spin_again and self.nav.is_pause(after):
                self.store.complete_spin(spin_id)
                return after, None
            self.nav.pause(.04)
        raise RuntimeError("Collect-and-spin destination was not recognized; checkpoint retained")

    def run(self, requested_spins, spin_type="SUPER", dry_run=True, stop_on_unknown=True):
        requested_spins = int(requested_spins)
        if not dry_run and not self._settings().get(AUTO_ACTIONS_SETTING):
            raise RuntimeError("Start Wheelspin Lab in Dry Run; automatic actions are not calibrated")
        saved = self.store.resumable_session(requested_spins, spin_type)
        session_id = saved["session_id"] if saved else self.store.start_session(
            requested_spins, spin_type, dry_run, stop_on_unknown)
        resume_spin_id = None
        current = self.store.current_spin(session_id)
        if current:
            observed = self.nav.observe()
            if current["status"] == "SPIN_STARTED" and not current["rewards_committed"]:
                if observed.screen == "wheelspin_duplicate":
                    pending = self.store.latest_pending_duplicate_spin(session_id)
                    if not pending:
                        raise RuntimeError("Visible duplicate has no committed source spin; no input sent")
                    self._duplicate(pending["spin_id"], observed, dry_run)
                resume_spin_id = current["spin_id"]
            elif current["status"] != "COLLECT_SENT":
                raise RuntimeError(f"Wheelspin Lab has an unfinished checkpoint {current['spin_id']}; inspect the current game screen before resume")
            elif observed.screen == "wheelspin_duplicate":
                self._finish_collect(current["spin_id"], dry_run)
            elif observed.screen == "wheelspin_reward":
                self.store.complete_spin(current["spin_id"])
            elif self.nav.is_pause(observed):
                self.store.complete_spin(current["spin_id"])
            elif observed.screen in {"garage_grid", "car_select", "cars", "campaign", "home_tab"}:
                if observed.screen in {"garage_grid", "car_select"}:
                    self.nav.back_home()
                self.store.complete_spin(current["spin_id"])
            else:
                raise RuntimeError("COLLECT checkpoint screen is ambiguous; no repeat input sent")
        queued_reward = None
        chain_active = resume_spin_id is not None
        visible = self.nav.observe()
        if visible.screen == "wheelspin_duplicate":
            pending = self.store.latest_pending_duplicate_spin(session_id)
            if not pending:
                raise RuntimeError("Visible duplicate has no committed source spin; no input sent")
            self._duplicate(pending["spin_id"], visible, dry_run)
            chain_active = True
        self.emit("activity", True)
        self._progress(session_id)
        while self.running.is_set():
            session = self.store.session(session_id)
            if session["completed_spins"] >= requested_spins:
                self.emit("status", f"Wheelspin Lab complete — {requested_spins} spins recorded")
                return
            number = session["completed_spins"] + 1
            self.emit("stage", "wheelspin_open")
            self.emit("status", f"Wheelspin Lab {number}/{requested_spins}: opening {spin_type}")
            obs = stable = None
            initial = self.nav.observe()
            if resume_spin_id:
                spin_id = resume_spin_id
                resume_spin_id = None
                # Old imported/unverified decisions must never make a fresh
                # crash checkpoint look as though its duplicate dialog is
                # still open.  Associate a pending row only with a currently
                # visible native duplicate prompt.
                pending = (self.store.latest_pending_duplicate_spin(session_id)
                           if initial.screen == "wheelspin_duplicate" else None)
                if pending is None:
                    self._restart_unresolved_spin(spin_type, initial)
                obs, stable = self._resolved(spin_type,
                    pending_spin_id=pending["spin_id"] if pending else None, dry_run=dry_run)
            elif queued_reward is not None:
                spin_id = self.store.start_spin(session_id, number, spin_type)
                self.store.event("CHAINED_SPIN_STARTED", spin_id)
                obs, stable = queued_reward
                queued_reward = None
            elif chain_active:
                spin_id = self.store.start_spin(session_id, number, spin_type)
                self.store.event("CHAINED_SPIN_STARTED", spin_id)
                obs, stable = self._resolved(spin_type)
            elif initial.screen == "wheelspin_reward":
                # Recovery after selecting the tile but before the old worker
                # could create its checkpoint. The visible result is preserved
                # and recorded; no second spin input is sent.
                spin_id = self.store.start_spin(session_id, number, spin_type)
                self.store.event("RECOVERED_VISIBLE_REWARD", spin_id,
                                 reason="resolved reward was visible before checkpoint resume")
                self.emit("log", f"Recovered visible reward screen for spin {number}; no new spin input sent")
            else:
                self._focus_spin_tile(spin_type)
                # The My Horizon tile starts the spin immediately. Commit the
                # checkpoint before Enter so a crash cannot orphan a result.
                spin_id = self.store.start_spin(session_id, number, spin_type)
                self.nav.key("enter")
            if obs is None:
                obs, stable = self._resolved(spin_type)
            session_folder = self.root / "wheelspin_lab" / session_id
            screen_path, rewards = capture_reward_observation(
                obs.frame, self.nav.reader, session_folder, number, spin_type)
            # Stable OCR and the persisted evidence must describe the same slots.
            if [r["normalized_text"] for r in rewards] != [r["normalized_text"] for r in stable]:
                raise RuntimeError("Persisted reward frame disagreed with the stable observations; no Collect input sent")
            self.store.commit_rewards(spin_id, rewards, screen_path=screen_path)
            self.emit("log", f"{len(rewards)}/{len(rewards)} rewards durably committed for spin {number}")
            if stop_on_unknown and any(row["reward_type"] == "UNKNOWN" for row in rewards):
                raise RuntimeError("UNKNOWN reward recorded; Stop on unknown blocked Collect")
            last_spin = number >= requested_spins
            self.store.event("COLLECT_INTENT" if last_spin else "COLLECT_AND_SPIN_INTENT", spin_id)
            self.nav.key("esc" if last_spin else "enter")
            self.store.collect_sent(spin_id)
            queued_reward = self._finish_collect(spin_id, dry_run, spin_again=not last_spin)
            chain_active = not last_spin
            self._progress(session_id)
