import time
import threading
from pathlib import Path

import cv2
import keyboard
import mss
import numpy as np
import pyautogui


BASE = Path(__file__).resolve().parent
T = BASE / "templates"

MONITOR = 1
THRESHOLD = 0.96
POLL = 0.15
TIMEOUT = 8.0

stop_event = threading.Event()
run_lock = threading.Lock()

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

sct = mss.MSS()

MASTERY = T / "mastery_anchor.png"
MAD_MIKE = T / "mad_mike_anchor.png"

NODES = [
    ("Node 1", T / "node1_locked.png", T / "node1_unlocked.png"),
    ("Node 2", T / "node2_locked.png", T / "node2_unlocked.png"),
    ("Node 3", T / "node3_locked.png", T / "node3_unlocked.png"),
    ("Node 4", T / "node4_locked.png", T / "node4_unlocked.png"),
    ("Node 5", T / "node5_locked.png", T / "node5_unlocked.png"),
    ("SUPER", T / "super_locked.png", T / "super_unlocked.png"),
]

cache = {}


def monitor():
    return sct.monitors[MONITOR]


def screenshot():
    raw = np.array(sct.grab(monitor()))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)


def load(path):
    if path not in cache:
        img = cv2.imread(str(path))

        if img is None:
            raise RuntimeError(f"Missing template: {path}")

        cache[path] = img

    return cache[path]


def find(path):
    screen = screenshot()
    target = load(path)

    result = cv2.matchTemplate(
        screen,
        target,
        cv2.TM_CCOEFF_NORMED
    )

    _, confidence, _, pos = cv2.minMaxLoc(result)

    if confidence < THRESHOLD:
        return None

    h, w = target.shape[:2]
    mon = monitor()

    return {
        "x": mon["left"] + pos[0] + w // 2,
        "y": mon["top"] + pos[1] + h // 2,
        "confidence": confidence,
    }


def wait_for(path, timeout=TIMEOUT):
    end = time.time() + timeout

    while time.time() < end:
        check_stop()

        result = find(path)

        if result:
            return result

        time.sleep(POLL)

    return None


def check_stop():
    if stop_event.is_set():
        raise InterruptedError


def move_away():
    mon = monitor()

    pyautogui.moveTo(
        mon["left"] + 40,
        mon["top"] + 40,
        duration=0.2
    )

    time.sleep(0.6)


def verify_screen():
    move_away()

    if not wait_for(MASTERY, 3):
        raise RuntimeError("Not on mastery screen")

    if not wait_for(MAD_MIKE, 3):
        raise RuntimeError("Mad Mike not detected")


def unlock_node(name, locked, unlocked):
    print()
    print(name)

    move_away()

    already_unlocked = find(unlocked)

    if already_unlocked:
        print(f"{name}: already unlocked")
        return

    print(f"{name}: waiting for locked state")

    target = wait_for(
        locked,
        timeout=TIMEOUT
    )

    if not target:
        raise RuntimeError(
            f"{name}: locked state never appeared"
        )

    print(
        f"{name}: locked {target['confidence']:.3f}"
    )

    pyautogui.moveTo(
        target["x"],
        target["y"],
        duration=0.3
    )

    time.sleep(0.5)

    check_stop()

    pyautogui.press("enter")

    print(f"{name}: ENTER")

    time.sleep(0.7)

    move_away()

    print(f"{name}: verifying unlock")

    result = wait_for(
        unlocked,
        timeout=TIMEOUT
    )

    if not result:
        raise RuntimeError(
            f"{name}: did not unlock"
        )

    print(
        f"{name}: UNLOCKED {result['confidence']:.3f}"
    )

    time.sleep(0.7)


def process_car():
    if not run_lock.acquire(blocking=False):
        print("Already running")
        return

    try:
        stop_event.clear()

        print()
        print("MAD MIKE MASTERY START")

        verify_screen()

        for name, locked, unlocked in NODES:
            check_stop()

            unlock_node(
                name,
                locked,
                unlocked
            )

        move_away()

        if not wait_for(
            NODES[-1][2],
            timeout=3
        ):
            raise RuntimeError(
                "Super final verification failed"
            )

        print()
        print("DONE - SUPER BANKED")

    except InterruptedError:
        print("STOPPED")

    except Exception as e:
        print(f"ERROR: {e}")

    finally:
        run_lock.release()


def emergency_stop():
    stop_event.set()
    print("STOP REQUESTED")


keyboard.add_hotkey(
    "f6",
    process_car
)

keyboard.add_hotkey(
    "f7",
    emergency_stop
)

print("Ready")
print("F6 = run")
print("F7 = stop")

keyboard.wait()