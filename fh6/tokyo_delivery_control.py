"""Single-owner virtual Xbox controller for supervised Tokyo delivery runs.

Run with ``python -u -m fh6.tokyo_delivery_control``. Commands are read from
stdin; the controller stays connected until ``quit`` or the process exits.
Every input checks the original FH6 process and foreground, and all controls
are neutralized even if a command fails.
"""

import json
import math
import sys
import time
import uuid
from datetime import datetime, timezone

import vgamepad as vg

from .game_lifecycle import WindowsGame
from .ownership import WorkerLease


BUTTONS = {
    'a': vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    'b': vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    'x': vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    'y': vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    'up': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    'down': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    'left': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    'right': vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    'menu': vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    'view': vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    'lb': vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    'rb': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
}

MAX_SEQUENCE_STEPS = 16
MAX_SEQUENCE_INPUT_SECONDS = 12
MAX_SEQUENCE_WALL_SECONDS = 15


def _bounded_number(value, label, low, high):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f'{label} must be between {low} and {high}')
    return float(value)


def validate_sequence(steps):
    """Reject an entire malformed plan before sending its first input."""
    if not isinstance(steps, list) or len(steps) > MAX_SEQUENCE_STEPS:
        raise ValueError(f'Sequence must be a list of at most {MAX_SEQUENCE_STEPS} steps')
    result, total = [], 0.0
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError('Every sequence step must be an object')
        action = step.get('action')
        fields = {
            'pulse': ({'action', 'button', 'seconds'}, {'action', 'button'}),
            'drive': ({'action', 'throttle', 'steer', 'seconds'},
                      {'action', 'throttle', 'steer', 'seconds'}),
            'stick': ({'action', 'x', 'y', 'seconds'},
                      {'action', 'x', 'y', 'seconds'}),
            'wait': ({'action', 'seconds'}, {'action', 'seconds'}),
        }
        if not isinstance(action, str) or action not in fields:
            raise ValueError(f'Unsupported sequence action: {action}')
        allowed, required = fields[action]
        if not required <= step.keys() or step.keys() - allowed:
            raise ValueError(f'Wrong fields for {action} step')
        duration = _bounded_number(
            step.get('seconds', 0.1), 'seconds', 0.03,
            0.4 if action == 'pulse' else 3 if action == 'wait' else 2)
        normalized = {'action': action, 'seconds': duration}
        if action == 'pulse':
            if not isinstance(step['button'], str) or step['button'] not in BUTTONS:
                raise ValueError('Unsupported sequence button')
            normalized['button'] = step['button']
        elif action == 'drive':
            normalized['throttle'] = _bounded_number(step['throttle'], 'throttle', -1, 1)
            normalized['steer'] = _bounded_number(step['steer'], 'steer', -1, 1)
        elif action == 'stick':
            normalized['x'] = _bounded_number(step['x'], 'x', -1, 1)
            normalized['y'] = _bounded_number(step['y'], 'y', -1, 1)
        total += duration
        if total > MAX_SEQUENCE_INPUT_SECONDS:
            raise ValueError(f'Sequence input and waits exceed {MAX_SEQUENCE_INPUT_SECONDS} seconds')
        result.append(normalized)
    return result


class GuardedPad:
    def __init__(self, *, guard=None):
        self.game = WindowsGame()
        self.identity = tuple(self.game.identity())
        if len(self.identity) != 1:
            raise RuntimeError('Expected one verified FH6 process')
        self.guard = guard
        self.pad = vg.VX360Gamepad()
        self.neutral()

    def check(self):
        try:
            if self.guard is not None:
                self.guard()
            if not self.game.foreground_matches(self.identity):
                raise RuntimeError('FH6 process or foreground changed; controller neutralized')
            if self.game.sync_windows():
                raise RuntimeError('Cloud or Gaming UI dialog is open; controller neutralized')
        except Exception:
            self.neutral()
            raise

    def neutral(self):
        self.pad.reset()
        self.pad.update()

    def _wait_checked(self, seconds, deadline=None):
        end = time.monotonic() + seconds
        while True:
            self.check()
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise RuntimeError('Sequence exceeded its wall-time bound')
            remaining = end - now
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining,
                           deadline - now if deadline is not None else remaining))

    def pulse(self, name, seconds=0.1, *, deadline=None):
        if name not in BUTTONS or not 0.03 <= seconds <= 0.4:
            raise ValueError('Unsupported button or pulse duration')
        self.check()
        try:
            self.pad.press_button(button=BUTTONS[name])
            self.pad.update()
            self._wait_checked(seconds, deadline)
        finally:
            self.neutral()

    def drive(self, throttle, steer, seconds, *, deadline=None):
        if not -1 <= throttle <= 1 or not -1 <= steer <= 1 or not 0.03 <= seconds <= 2:
            raise ValueError('Drive command outside bounded range')
        self.check()
        try:
            if throttle >= 0:
                self.pad.right_trigger_float(value_float=throttle)
            else:
                self.pad.left_trigger_float(value_float=-throttle)
            self.pad.left_joystick_float(x_value_float=steer, y_value_float=0)
            self.pad.update()
            self._wait_checked(seconds, deadline)
        finally:
            self.neutral()

    def stick(self, x, y, seconds, *, deadline=None):
        if not -1 <= x <= 1 or not -1 <= y <= 1 or not 0.03 <= seconds <= 2:
            raise ValueError('Stick command outside bounded range')
        self.check()
        try:
            self.pad.left_joystick_float(x_value_float=x, y_value_float=y)
            self.pad.update()
            self._wait_checked(seconds, deadline)
        finally:
            self.neutral()

    def sequence_and_observe(self, steps):
        """Run a short plan, then return one process-bound image and local OCR."""
        try:
            plan = validate_sequence(steps)
            from .ocr import WindowsOCR
            from .report_images import _capture_verified_window
            from .reporting import RUNS
            import cv2

            started = time.monotonic()
            deadline = started + MAX_SEQUENCE_WALL_SECONDS
            self.check()
            for step in plan:
                action, seconds = step['action'], step['seconds']
                if action == 'pulse':
                    self.pulse(step['button'], seconds, deadline=deadline)
                elif action == 'drive':
                    self.drive(step['throttle'], step['steer'], seconds, deadline=deadline)
                elif action == 'stick':
                    self.stick(step['x'], step['y'], seconds, deadline=deadline)
                else:
                    self.neutral()
                    self._wait_checked(seconds, deadline)
            self.neutral()
            self.check()
            if time.monotonic() >= deadline:
                raise RuntimeError('Sequence exceeded its wall-time bound')
            input_elapsed = time.monotonic() - started
            frame = _capture_verified_window()
            self.check()
            if frame is None:
                raise RuntimeError('Could not capture the verified FH6 foreground window')
            folder = RUNS / 'tokyo_delivery'
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
            path = folder / f'{stamp}_{uuid.uuid4().hex[:8]}.png'
            if not cv2.imwrite(str(path), frame):
                raise RuntimeError('Could not save the verified FH6 screenshot')
            reader = WindowsOCR()
            try:
                doc = reader.read(frame)
            finally:
                reader.close()
            self.check()
            return {
                'screenshot': str(path.resolve()),
                'ocr': [{'text': line.text, 'center': line.center} for line in doc.lines],
                'steps': len(plan),
                'input_seconds': round(input_elapsed, 3),
                'elapsed_seconds': round(time.monotonic() - started, 3),
            }
        finally:
            self.neutral()


def main():
    with WorkerLease():
        pad = GuardedPad()
        print(json.dumps({'ready': True, 'game_identity': pad.identity}), flush=True)
        try:
            for line in sys.stdin:
                try:
                    raw = line.strip()
                    command, _, payload = raw.partition(' ')
                    command = command.casefold()
                    if command == 'sequence':
                        result = pad.sequence_and_observe(json.loads(payload))
                        print(json.dumps({'ok': 'sequence', **result}), flush=True)
                        continue
                    if command == 'observe' and not payload:
                        result = pad.sequence_and_observe([])
                        print(json.dumps({'ok': 'observe', **result}), flush=True)
                        continue
                    parts = raw.lower().split()
                    if not parts:
                        continue
                    if parts[0] == 'quit':
                        break
                    if parts[0] == 'neutral' and len(parts) == 1:
                        pad.neutral()
                    elif parts[0] == 'pulse' and len(parts) in (2, 3):
                        pad.pulse(parts[1], float(parts[2]) if len(parts) == 3 else 0.1)
                    elif parts[0] == 'drive' and len(parts) == 4:
                        pad.drive(float(parts[1]), float(parts[2]), float(parts[3]))
                    elif parts[0] == 'stick' and len(parts) == 4:
                        pad.stick(float(parts[1]), float(parts[2]), float(parts[3]))
                    else:
                        raise ValueError('Use pulse BUTTON [SECONDS], drive THROTTLE STEER SECONDS, stick X Y SECONDS, sequence JSON, observe, neutral, quit')
                    print(json.dumps({'ok': parts}), flush=True)
                except Exception as exc:
                    pad.neutral()
                    print(json.dumps({'error': str(exc)}), flush=True)
        finally:
            pad.neutral()


if __name__ == '__main__':
    main()
