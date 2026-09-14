"""Cache game-only report images; refuse an obscured or unfocused desktop."""
import ctypes
from ctypes import wintypes as wt
import hashlib
import queue
import threading
import time
from datetime import datetime, timezone

import cv2
import numpy as np
import forza_cycle as core
from .reporting import RUNS, read_json, write_json


FOLDER = RUNS/'reports'
MENU_POLICY = 'my_horizon_only_v2'
LEGACY_MENU_POLICY = 'cars_or_my_horizon_v1'


def allowed_report_menu(screen, doc):
    """Only the My Horizon / Return Home menu, independently of account strips."""
    return (screen == 'pause_menu' and (doc.has('Return Home', contains=True) or doc.has('Fast Travel Home', contains=True))
            and (doc.has('Message Center', contains=True) or doc.has('My Stats'))
            and doc.has('MY HORIZON'))


def unobscured_game(monitor, diagnostic=None):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = wt.HWND
    user.GetTopWindow.argtypes = [wt.HWND]
    user.GetTopWindow.restype = wt.HWND
    user.GetWindow.argtypes = [wt.HWND, wt.UINT]
    user.GetWindow.restype = wt.HWND
    user.IsWindowVisible.argtypes = [wt.HWND]
    user.IsIconic.argtypes = [wt.HWND]
    user.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    foreground = user.GetForegroundWindow()
    if not foreground or 'forza horizon 6' not in core.foreground_title().casefold():
        return False
    left, top = monitor['left'], monitor['top']
    right, bottom = left+monitor['width'], top+monitor['height']
    handle = user.GetTopWindow(None)
    for _ in range(1000):
        if handle == foreground:
            return True
        if not handle:
            return False
        if user.IsWindowVisible(handle) and not user.IsIconic(handle):
            rect = wt.RECT()
            if not user.GetWindowRect(handle, ctypes.byref(rect)):
                return False
            if min(right, rect.right)-max(left, rect.left) > 4 and min(bottom, rect.bottom)-max(top, rect.top) > 4:
                if diagnostic:
                    user.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
                    title = ctypes.create_unicode_buffer(256)
                    user.GetWindowTextW(handle, title, 256)
                    user.GetLayeredWindowAttributes.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.BYTE), ctypes.POINTER(wt.DWORD)]
                    color, alpha, flags = wt.DWORD(), wt.BYTE(), wt.DWORD()
                    layered = user.GetLayeredWindowAttributes(handle, ctypes.byref(color), ctypes.byref(alpha), ctypes.byref(flags))
                    diagnostic(dict(window_title=title.value, rectangle=[rect.left,rect.top,rect.right,rect.bottom], layered=bool(layered),alpha=alpha.value,flags=flags.value))
                return False
        handle = user.GetWindow(handle, 2)  # GW_HWNDNEXT, in desktop Z order.
    return False


def capture_game_window(diagnostic=None):
    """Capture only the verified FH6 window; never fall back to the desktop."""
    from .window_capture import capture_window
    from .game_lifecycle import WindowsGame
    game = WindowsGame()
    user = game.u
    user.GetForegroundWindow.restype = wt.HWND
    handle = user.GetForegroundWindow()
    if not handle or 'forza horizon 6' not in core.foreground_title().casefold():
        return None
    pid = wt.DWORD()
    user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    process = game.k.OpenProcess(0x1000, False, pid.value)
    if not process:
        return None
    try:
        if not game.matches(process):
            return None
        frame = capture_window(handle)
        if frame is None:
            return None
        if user.GetForegroundWindow() != handle or not game.matches(process):
            return None
        from .navigation import menu_name
        from .ocr import WindowsOCR
        reader = WindowsOCR()
        try:
            doc = reader.read(frame)
            screen = menu_name(doc, core.Recognizer().inspect(frame))
            if diagnostic:
                diagnostic(dict(screen=screen, shape=frame.shape, header=[l.text for l in doc.lines if l.center[1]<100]))
            if not allowed_report_menu(screen, doc):
                return None
        finally:
            reader.close()
        return frame
    finally:
        game.k.CloseHandle(process)


def store_frame(frame, observed_at, folder=FOLDER, source='Verified unobscured game frame', context=None):
    ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return
    blob = jpeg.tobytes()
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder/'game.tmp'
    temporary.write_bytes(blob)
    temporary.replace(folder/'game.jpg')
    write_json(folder/'game.json', {'observed_at': observed_at, 'sha256': hashlib.sha256(blob).hexdigest(),
                                  'source': source, **(context or {})})


def _legacy_image_is_my_horizon(blob):
    """Revalidate saved old-policy bytes; never capture or navigate the game."""
    from .ocr import WindowsOCR
    reader = None
    try:
        frame = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return False
        reader = WindowsOCR()
        return allowed_report_menu('pause_menu', reader.read(frame))
    except Exception:
        return False
    finally:
        if reader is not None:
            reader.close()


def _approved_evidence(folder, stem, *, goal_id, earned):
    metadata = read_json(folder/(stem+'.json'))
    # A running old worker can still write Cars frames. Its metadata narrows
    # candidates, then the saved bytes receive a new content check below.
    if (metadata.get('menu_policy') not in {MENU_POLICY, LEGACY_MENU_POLICY}
            or metadata.get('screen') != 'pause_menu'
            or metadata.get('verified_game') is not True):
        return None
    if goal_id is not None and metadata.get('goal_id') != goal_id:
        return None
    if earned is not None and metadata.get('earned') != earned:
        return None
    try:
        observed = datetime.fromisoformat(metadata['observed_at'])
        if observed.tzinfo is None:
            return None
        blob = (folder/(stem+'.jpg')).read_bytes()
        if len(blob) < 5_000_000 and hashlib.sha256(blob).hexdigest() == metadata.get('sha256'):
            if metadata.get('menu_policy') == LEGACY_MENU_POLICY:
                if not _legacy_image_is_my_horizon(blob):
                    return None
                metadata = dict(metadata, menu_policy=MENU_POLICY,
                    capture_menu_policy=LEGACY_MENU_POLICY,
                    delivery_verified_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    source='Latest verified My Horizon / Return Home menu')
            return blob, metadata, observed
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None


def evidence(folder=FOLDER, *, goal_id=None, earned=None, metadata_out=None):
    """Latest same-mission approved menu; exact reward matching is optional.

    Retain an independent approved copy because a running old worker can still
    overwrite game.jpg with a now-disallowed Cars frame. Missing, foreign or
    unverified evidence never becomes a fallback image.
    """
    current = _approved_evidence(folder, 'game', goal_id=goal_id, earned=earned)
    retained = _approved_evidence(folder, 'my_horizon', goal_id=goal_id, earned=earned)
    candidates = [item for item in (current, retained) if item is not None]
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: item[2])
    blob, metadata, _ = selected
    if current is selected and (retained is None or current[2] > retained[2]):
        try:
            temporary = folder/'my_horizon.tmp'
            temporary.write_bytes(blob)
            temporary.replace(folder/'my_horizon.jpg')
            write_json(folder/'my_horizon.json', metadata)
        except OSError:
            pass  # A cache lock must not prevent using the verified source.
    if metadata_out is not None:
        metadata_out.update(metadata)
    return blob, metadata['observed_at']


class ScreenshotCache:
    def __init__(self, enabled=True):
        self.enabled, self.last_capture = enabled, 0
        self.frames = queue.Queue(maxsize=1)
        self.thread = None
        self.reward = None
        self.last_reward = None
        self.pending_reward = None

    def request_reward(self, goal_id, earned):
        self.reward = (goal_id, earned) if goal_id and earned >= 0 else None

    def ready(self, monitor):
        return (self.enabled and self.reward is not None and self.reward != self.pending_reward and
                (self.reward != self.last_reward or time.monotonic()-self.last_capture>=15))

    def desktop_clear(self, monitor):
        return unobscured_game(monitor)

    @staticmethod
    def allowed(obs):
        return allowed_report_menu(obs.screen, obs.doc)

    def offer(self, obs, monitor, *, desktop_clear=None):
        if not allowed_report_menu(obs.screen, obs.doc) or not self.ready(monitor):
            return
        # The control thread only freezes the already verified game frame.
        # Desktop enumeration, image encoding and disk I/O all happen in the
        # reporter worker so they cannot delay the next game input.
        frame = obs.frame.copy()
        if self.thread is None:
            self.thread = threading.Thread(target=self._write, daemon=True)
            self.thread.start()
        try:
            context = dict(goal_id=self.reward[0], earned=self.reward[1],
                           screen=obs.screen, verified_game=True, menu_policy=MENU_POLICY)
            self.frames.put_nowait((frame, datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                    context, dict(monitor)))
            self.pending_reward = self.reward
        except queue.Full:
            pass

    def _write(self):
        while True:
            frame, timestamp, context, monitor = self.frames.get()
            try:
                # Verify that no other desktop window overlaps the game before
                # persisting pixels that can be sent to Discord.
                if not unobscured_game(monitor):
                    self.pending_reward = None
                    continue
                store_frame(frame, timestamp, source='Latest verified My Horizon / Return Home menu', context=context)
                self.last_reward = (context['goal_id'], context['earned'])
                self.last_capture = time.monotonic()
            except Exception:
                self.last_reward = None
                self.pending_reward = None
            finally:
                if self.pending_reward == (context['goal_id'], context['earned']):
                    self.pending_reward = None
                self.frames.task_done()
