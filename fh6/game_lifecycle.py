"""Steam startup and bounded recovery, independent of farming and purchases.

Only the executable in Steam's FH6 manifest can be terminated. A lost focus or
an unrecognized menu is not a crash. No reward or purchase is inferred here.
"""
import ctypes
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import re
import subprocess
import time

import forza_cycle as core
from .ocr import normalize
from .cloud_sync import SyncPending, sync_state

APP_ID = '2483190'


class GameCrashed(RuntimeError):
    pass


def crash_text(text):
    value = normalize(text)
    return any(term in value for term in ('video card crash', 'terminated unexpectedly', 'fhc11'))


def startup_screen(doc):
    if doc.has('Start Game', (0, 750, 1920, 330), contains=True):
        return 'start'
    if doc.has('Continue', (0, 700, 650, 380)) and doc.has('Options', (0, 700, 650, 380)) and doc.has('Exit', (0, 700, 650, 380)):
        return 'continue'
    return None


def steam_installation():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
        root = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
    libraries = [root]
    folders = root/'steamapps/libraryfolders.vdf'
    if folders.exists():
        libraries += [Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', folders.read_text(encoding='utf-8'))]
    for library in libraries:
        manifest = library/f'steamapps/appmanifest_{APP_ID}.acf'
        if not manifest.exists():
            continue
        text = manifest.read_text(encoding='utf-8')
        app = re.search(r'"appid"\s+"(\d+)"', text)
        folder = re.search(r'"installdir"\s+"([^"/\\]+)"', text)
        if app and app[1] == APP_ID and folder and folder[1] not in {'.', '..'}:
            exe = library/'steamapps/common'/folder[1]/'forzahorizon6.exe'
            if exe.is_file() and (root/'steam.exe').is_file():
                return root/'steam.exe', exe.resolve()
    raise RuntimeError('Steam installation of Forza Horizon 6 was not found. Install it and sign in to Steam first.')


class WindowsGame:
    def __init__(self):
        self.steam, self.exe = steam_installation()
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        self.k.OpenProcess.restype = wt.HANDLE
        self.k.CloseHandle.argtypes = [wt.HANDLE]
        self.k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        self.k.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
        self.k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        self.u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        self.u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        self.u.IsWindowVisible.argtypes = [wt.HWND]
        self.u.IsIconic.argtypes = [wt.HWND]
        self.u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        self.u.SetForegroundWindow.argtypes = [wt.HWND]
        self.callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        self.u.EnumWindows.argtypes = [self.callback, wt.LPARAM]
        self.u.EnumChildWindows.argtypes = [wt.HWND, self.callback, wt.LPARAM]

    def matches(self, handle):
        buffer, size = ctypes.create_unicode_buffer(32768), wt.DWORD(32768)
        return bool(self.k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))) and os.path.normcase(buffer.value) == os.path.normcase(str(self.exe))

    def pids(self):
        # EnumProcesses includes a crashed process whose window has disappeared.
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        values, size = (wt.DWORD * 65536)(), wt.DWORD()
        if not psapi.EnumProcesses(values, ctypes.sizeof(values), ctypes.byref(size)) or size.value == ctypes.sizeof(values):
            raise RuntimeError('Could not enumerate game processes safely')
        result = []
        for pid in values[:size.value//ctypes.sizeof(wt.DWORD)]:
            handle = self.k.OpenProcess(0x1000, False, pid)
            if handle:
                try:
                    if self.matches(handle):
                        result.append(pid)
                finally:
                    self.k.CloseHandle(handle)
        if len(result) > 1:
            raise RuntimeError('More than one FH6 process is running; no launch or termination sent')
        return result

    def windows(self, pids):
        result = []
        def visit(hwnd, _):
            pid = wt.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and self.u.IsWindowVisible(hwnd):
                strings = []
                def collect(child, _):
                    buf = ctypes.create_unicode_buffer(8192)
                    self.u.GetWindowTextW(child, buf, len(buf))
                    strings.append(buf.value)
                    return True
                collect(hwnd, 0)
                self.u.EnumChildWindows(hwnd, self.callback(collect), 0)
                result.append((hwnd, ' '.join(strings)))
            return True
        self.u.EnumWindows(self.callback(visit), 0)
        return result

    def crashed(self):
        return any(crash_text(text) for _, text in self.windows(self.pids()))

    @staticmethod
    def sync_windows():
        # Check visible top-level windows, including an occluded Gaming UI.
        # Foreground title alone would let priority activation hide a sync dialog.
        user = ctypes.WinDLL('user32', use_last_error=True)
        callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        user.IsWindowVisible.argtypes = [wt.HWND]
        user.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        user.EnumWindows.argtypes = [callback, wt.LPARAM]
        result = []
        def visit(hwnd, _):
            if user.IsWindowVisible(hwnd):
                text = ctypes.create_unicode_buffer(512)
                user.GetWindowTextW(hwnd, text, len(text))
                title = text.value.casefold()
                if title == 'gaming ui' or 'cloud sync' in title or 'cloud conflict' in title:
                    result.append(hwnd)
            return True
        user.EnumWindows(callback(visit), 0)
        return result

    def identity(self):
        """PID plus process creation time prevents reusing old sync approval."""
        result = []
        self.k.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
        for pid in self.pids():
            handle = self.k.OpenProcess(0x1000, False, pid)
            if not handle:
                raise RuntimeError('Cannot verify the game process identity')
            try:
                result.append(self._handle_identity(pid, handle))
            finally:
                self.k.CloseHandle(handle)
        if not result:
            raise GameCrashed('Game process exited before sync verification')
        return result

    def _handle_identity(self, pid, handle):
        # Check both executable and creation time on the same open handle.
        if not self.matches(handle):
            raise RuntimeError('Game process identity changed; no termination sent')
        self.k.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
        times = [wt.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise RuntimeError('Cannot verify game process creation time')
        return f'{pid}:{times[0].dwHighDateTime}:{times[0].dwLowDateTime}'

    def launch(self):
        if self.pids():
            # A manual/Steam relaunch may win the race with ensure(). Attach to
            # it through normal startup verification instead of retrying later.
            return False
        subprocess.Popen([str(self.steam), '-applaunch', APP_ID],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return True

    def terminate_crashed(self, expected_identity):
        if len(expected_identity) != 1:
            raise ValueError('Exactly one crash-time process identity is required')
        pids = self.pids()
        for pid in pids:
            handle = self.k.OpenProcess(0x1000 | 0x100000 | 1, False, pid)
            if not handle:
                continue
            try:
                # Binding only to the executable would also kill a healthy
                # replacement launched during the recovery backoff.
                if self._handle_identity(pid, handle) != expected_identity[0]:
                    return False
                if not self.k.TerminateProcess(handle, 1):
                    raise RuntimeError('Could not close the crashed FH6 process')
                return True
            finally:
                self.k.CloseHandle(handle)
        return False

    def activate(self):
        windows = [(hwnd, text) for hwnd, text in self.windows(self.pids())
                   if 'forza horizon 6' in text.lower() and not crash_text(text)]
        if len(windows) != 1:
            return False
        # SW_RESTORE also unmaximizes an already-visible game, invalidating
        # every calibrated region. Restore only a minimized window.
        if self.u.IsIconic(windows[0][0]):
            self.u.ShowWindow(windows[0][0], 9)
        self.u.SetForegroundWindow(windows[0][0])
        return True


class GameLifecycle:
    def __init__(self, running, emit=lambda *a: None, enabled=True, max_restarts=0,
                 backend=None, clock=time.monotonic, sleep=time.sleep,
                 path=core.BASE/'runs/game_recovery.json', startup_timeout=300, priority=True):
        if type(max_restarts) is not int or not 0 <= max_restarts <= 10:
            raise ValueError('Crash restarts must be between 0 and 10')
        self.running, self.emit, self.enabled = running, emit, enabled
        self.priority = priority
        self.max_restarts, self.restarts = max_restarts, 0
        self.backend, self.clock, self.sleep = backend, clock, sleep
        self.path, self.startup_timeout = Path(path), startup_timeout
        self.observed_process = False
        self.sync_guard = None
        self.display_guard = None
        self._crash_observation = None
        self._timing = None

    def _current_identity(self):
        if not self.game.pids():
            return ()
        try:
            return tuple(self.game.identity())
        except GameCrashed:
            # The process may exit between enumeration and opening its handle.
            if not self.game.pids():
                return ()
            raise

    def _remember_crash(self, exc):
        if self._crash_observation is None or self._crash_observation[0] is not exc:
            self._crash_observation = (exc, self._current_identity(), self.clock())
        return self._crash_observation

    def _timing_event(self, phase, **fields):
        if self._timing is None or phase in self._timing['seen']:
            return
        self._timing['seen'].add(phase)
        self.emit('log', 'Lifecycle timing: ' + json.dumps(dict(
            phase=phase, kind=self._timing['kind'], restart=self.restarts,
            elapsed_seconds=round(self.clock()-self._timing['started'], 3),
            **fields), sort_keys=True))

    def _verify_replacement(self, nav):
        self._timing_event('replacement_observed')
        self.emit('log', 'Crash-time process has been replaced; verifying the existing game without closing or relaunching it')
        if self.sync_guard:
            self.sync_guard.evidence = None
            self.sync_guard.verified_identity = None
        return self.wait_ready(nav, launched=False)

    def check_sync(self):
        if self.sync_guard:
            self.sync_guard.check()
        if self.display_guard:
            self.display_guard.check()

    @property
    def game(self):
        if self.backend is None:
            self.backend = WindowsGame()
        return self.backend

    def check(self):
        if not self.running.is_set():
            raise core.MasteryStopped('Stopped with F7')

    def restore_focus(self):
        self.check()
        self.check_sync()
        if not self.enabled or not self.priority or core.foreground_title().casefold() == 'gaming ui':
            return False
        if not self.game.pids() or self.game.crashed() or not self.game.activate():
            return False
        deadline = self.clock()+1
        while self.clock() < deadline:
            self.check()
            if 'forza horizon 6' in core.foreground_title().casefold():
                return True
            self.pause(.1)
        return False

    def pause(self, seconds):
        end = self.clock()+seconds
        while self.clock() < end:
            self.check()
            self.sleep(min(.1, end-self.clock()))
        self.check()

    def mark_recovery(self, reason):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(reason=str(reason), restart=self.restarts)), encoding='utf-8')
        tmp.replace(self.path)

    def is_crash(self, exc):
        if isinstance(exc, SyncPending):
            return False
        if not self.enabled or isinstance(exc, core.MasteryStopped):
            return False
        self.check()
        crashed = isinstance(exc, GameCrashed) or self.game.crashed() or (self.observed_process and not self.game.pids())
        if crashed:
            self._remember_crash(exc)
        return crashed

    def recover(self, exc, nav):
        self.check()
        self.check_sync()
        self.mark_recovery(exc)
        if self.max_restarts and self.restarts >= self.max_restarts:
            raise RuntimeError(f'Crash restart limit reached ({self.max_restarts}). Progress saved. Last error: {exc}')
        _, expected_identity, detected_at = self._remember_crash(exc)
        self.restarts += 1
        self._timing = dict(kind='crash_recovery', started=detected_at, seen=set())
        self._timing_event('crash_detected')
        # The old 15/30/60/120-second backoff dominated recovery time. Steam is
        # still protected by the exact-process termination and no-duplicate
        # launch gates below, so keep only a short bounded cleanup backoff.
        delay = min(10, 2 * 2**min(3, self.restarts-1))
        limit = str(self.max_restarts) if self.max_restarts else 'unlimited'
        self.emit('stage', 'game_restart')
        self.emit('status', f'Game crashed — restart {self.restarts}/{limit} in {delay}s. F7 cancels.')
        self.emit('log', f'Crash recovery {self.restarts}/{limit}: {exc}')
        self.pause(delay)
        self.check()
        self.check_sync()
        current = self._current_identity()
        if current and current == expected_identity:
            self.check()
            self.check_sync()
            if self.game.terminate_crashed(expected_identity):
                self._timing_event('termination_sent')
        deadline = self.clock()+15
        while True:
            self.check()
            self.check_sync()
            current = self._current_identity()
            if not current:
                break
            if current != expected_identity:
                return self._verify_replacement(nav)
            if self.clock() >= deadline:
                raise RuntimeError('Crashed game did not exit; no duplicate launch sent')
            self.pause(.2)
        self._timing_event('process_exited')
        self.ensure(nav)

    def ensure(self, nav, bring_to_front=False):
        self.check()
        self.check_sync()
        if not self.enabled:
            return
        pids = self.game.pids()
        if pids:
            self.observed_process = True
            if self.game.crashed():
                raise GameCrashed('FH6 crash dialog detected')
            if self._timing is not None and self._timing['kind'] == 'crash_recovery':
                # Also cover a replacement arriving after the exit loop and
                # before ensure() checks for a process to launch.
                return self._verify_replacement(nav)
            if bring_to_front or self.priority:
                self.game.activate()
                self.pause(.5)
            # A healthy, already-open game retains the normal focus requirement.
            obs = nav.observe()
            if obs.screen=='unknown' and not startup_screen(obs.doc):
                obs.doc=nav.reader.refine_region(obs.frame,obs.doc,(0,750,500,270))
            if startup_screen(obs.doc) or (bring_to_front and obs.screen == 'unknown'):
                return self.wait_ready(nav, launched=False)
            return
        # A fresh launch may have followed a crash between worker runs. Reconcile
        # checkpoints even when no live exception was available to observe it.
        self.mark_recovery('Starting FH6 through Steam')
        self.emit('stage', 'game_start')
        self.emit('status', 'Opening Forza Horizon 6 through Steam — F7 cancels')
        self.observed_process = False
        if self._timing is None:
            self._timing = dict(kind='startup', started=self.clock(), seen=set())
        launched = self.game.launch() is not False
        self._timing_event('steam_launch' if launched else 'replacement_observed')
        if self.sync_guard:
            self.sync_guard.evidence = None
            self.sync_guard.verified_identity = None
        self.wait_ready(nav, launched=launched)

    def wait_ready(self, nav, launched):
        deadline, activated = self.clock()+self.startup_timeout, not launched
        sent, last, stable, wake_at = set(), None, 0, 0
        ready_screen, ready_count = None, 0
        waiting_focus = False
        while self.clock() < deadline:
            self.check()
            self.check_sync()
            pids = self.game.pids()
            if pids:
                self.observed_process = True
                self._timing_event('process_seen')
            elif self.observed_process:
                raise GameCrashed('FH6 exited during startup')
            if self.game.crashed():
                raise GameCrashed('FH6 crashed during startup')
            if not activated:
                activated = self.game.activate() if pids else False
                self.pause(.5)
                continue
            # Steam/Xbox can temporarily cover startup while signing in. Wait
            # without input or reactivation; never interact with a login dialog.
            foreground = core.foreground_title().casefold()
            if nav.title.casefold() not in foreground:
                ready_screen, ready_count = None, 0
                # Priority only reactivates the FH6 window; authentication and
                # other modal dialogs are never dismissed or typed into.
                if self.priority and foreground != 'gaming ui':
                    self.game.activate()
                if not waiting_focus:
                    self.emit('status', 'Waiting for game focus during startup — F7 cancels. Sign-in prompts need your input.')
                    waiting_focus = True
                self.pause(.5)
                continue
            waiting_focus = False
            obs = nav.observe()
            if nav.is_home(obs) or nav.is_roam(obs):
                ready_count = ready_count + 1 if obs.screen == ready_screen else 1
                ready_screen = obs.screen
                if ready_count < 3:
                    self.pause(.5)
                    continue
                if self.sync_guard:
                    self.sync_guard.native_startup_complete(launched, sent)
                self._timing_event('ready', screen=obs.screen,
                                   basis='three_stable_native_frames',
                                   sync_gate_checked=self.sync_guard is not None)
                self._timing = None
                self._crash_observation = None
                self.emit('status', 'Game ready — checking saved progress')
                return
            ready_screen, ready_count = None, 0
            screen = startup_screen(obs.doc)
            if screen == 'continue' or obs.screen=='unknown':
                # Cinematic scenery can skew full-frame OCR word coordinates.
                # Read the menu alone before relating Continue to its border.
                obs.doc = nav.reader.refine_region(obs.frame, obs.doc, (0,750,500,270))
                screen = startup_screen(obs.doc)
            stable = stable+1 if screen == last else 1
            last = screen
            if screen and stable >= 2 and screen not in sent:
                if screen == 'continue':
                    from .navigation import label_focused
                    matches = obs.doc.find('Continue', (0,700,650,380))
                    if len(matches) != 1 or not label_focused(obs.frame, matches[0]):
                        # A transient OCR box is not a reason to abandon
                        # startup and route this menu through free-roam recovery.
                        stable=0
                        self.pause(.5)
                        continue
                nav.key('enter')
                sent.add(screen)
                self._timing_event(screen+'_selected')
                wake_at = self.clock()+10
                self.emit('log', f'Startup: selected {screen} once')
            elif screen is None and 'continue' in sent and self.clock() >= wake_at:
                # Shift only wakes the idle home camera; it does not select a tile.
                nav.key('shift')
                wake_at = self.clock()+10
            self.pause(.5)
        if 'continue' in sent:
            raise GameCrashed('Game loading stalled for five minutes after Continue; restarting through Steam')
        raise RuntimeError('Steam/game startup timed out. Check login, updates or unexpected dialogs; no launch retry sent.')

    def wait_sync(self, nav):
        """Wait indefinitely without activation, keys, clicks, launch or kill.

        The stable native Start Game screen is the sole exception: selecting it
        initiates Xbox/cloud synchronization and cannot choose a cloud, offline,
        conflict or account-dialog option.  After that one input, disappearance
        alone is insufficient: require three stable observations of a playable
        menu. Unknown/loading/login/offline dialogs remain blocked.
        """
        guard = self.sync_guard
        guard.block('Waiting for synchronization and playable game')
        stable, last, start_sent, wake_sent, unknown_stable = 0, None, False, False, 0
        while True:
            self.check()
            if guard.observe_wait_identity(self.game.identity()):
                stable, last = 0, None
            if guard.visible():
                # Read-only OCR can see an explicit completion message before
                # the Gaming UI closes. It never dismisses or focuses it.
                foreground = core.foreground_title().casefold()
                if foreground == 'gaming ui' or 'cloud sync' in foreground or nav.title.casefold() in foreground:
                    guard.observe_completion(nav.observe_sync().doc)
                stable, last = 0, None
                self.pause(.5)
                continue
            if nav.title.casefold() not in core.foreground_title().casefold():
                stable, last = 0, None
                self.pause(.5)
                continue
            obs = nav.observe_sync()
            guard.observe_completion(obs.doc)
            native = startup_screen(obs.doc)
            if native == 'start' and not start_sent:
                stable = stable+1 if last == 'start' else 1
                last = 'start'
                if stable >= 2:
                    # Deliberately bypass the general sync input guard for this
                    # one exact lifecycle action. Display, focus, F7 and the
                    # two-frame native-label proof still apply.
                    if self.display_guard:
                        self.display_guard.check()
                    if nav.title.casefold() not in core.foreground_title().casefold():
                        stable, last = 0, None
                        self.pause(.5)
                        continue
                    import pyautogui
                    nav.invalidate_ready()
                    nav.probe('input', 'enter')
                    pyautogui.keyDown('enter')
                    try:
                        self.pause(.06)
                    finally:
                        pyautogui.keyUp('enter')
                    start_sent = True
                    stable, last = 0, None
                    self.emit('log', 'Sync gate selected verified Start Game once to initiate synchronization.')
                    self.pause(.5)
                continue
            unknown_stable = unknown_stable+1 if start_sent and obs.screen == 'unknown' else 0
            if unknown_stable >= 6 and not wake_sent and not guard.visible() and not sync_state(obs.doc):
                # FH6 can finish loading into its idle garage camera with the
                # Home tiles hidden. Shift only wakes that camera; it cannot
                # choose a tile or answer a sync/account dialog.
                if self.display_guard:
                    self.display_guard.check()
                if nav.title.casefold() in core.foreground_title().casefold():
                    import pyautogui
                    nav.invalidate_ready()
                    nav.probe('input', 'shift')
                    pyautogui.keyDown('shift')
                    try:
                        self.pause(.06)
                    finally:
                        pyautogui.keyUp('shift')
                    wake_sent = True
                    stable, last = 0, None
                    self.emit('log', 'Sync gate woke the verified idle garage camera once; no menu item selected.')
                    self.pause(.5)
                    continue
            from .farming import timer_visible, result_visible
            good = not sync_state(obs.doc) and (startup_screen(obs.doc) == 'continue' or
                nav.is_home(obs) or nav.is_roam(obs) or timer_visible(obs.doc) or result_visible(obs.doc) or
                obs.screen in {'collection_grid', 'garage_grid', 'mad_mike_mastery', 'car_mastery',
                               'journal', 'discover', 'upgrades', 'purchase_success',
                               'purchase_offer_95000', 'autoshow_prompt', 'collection_detail',
                               'recent_jump', 'sort_selection', 'manufacturers', 'car_action'})
            stable = stable+1 if good and obs.screen == last else int(good)
            last = obs.screen
            if stable >= 3 and guard.ready():
                return
            self.pause(.5)


def _confirmed_unentered_purchase(data, record, challenge_data, goal_data):
    """Authorize only reselecting one funded, confirmed, not-yet-claimed car."""
    if (data.get('phase') != 'choose' or data.get('mode') != 'Full pipeline' or
            goal_data.get('phase') != 'convert' or
            challenge_data and challenge_data.get('phase') != 'complete'):
        return False
    if (record.get('status') != 'confirmed' or type(record.get('price')) is not int or
            record['price'] != 95000 or
            record.get('car') != '1974 Mazda #123 Mad Mike 808 Wagon FURSTY' or
            not isinstance(record.get('id'), str) or not record['id'] or
            record['id'] == data.get('purchase_before')):
        return False
    batch, funding = goal_data.get('batch'), data.get('funding')
    if not isinstance(batch, dict) or not isinstance(funding, dict):
        return False
    if (not data.get('id') or batch.get('id') != data['id'] or
            not goal_data.get('id') or funding.get('goal_id') != goal_data['id'] or
            not isinstance(funding.get('id'), str) or not funding['id']):
        return False
    required = ((data, ('completed', 'bought', 'rewards', 'limit', 'observed_sp')),
                (goal_data, ('completed', 'bought', 'rewards', 'limit', 'last_sp')),
                (batch, ('cycles', 'completed_start', 'bought_start', 'rewards_start', 'bought_seen', 'rewards_seen')),
                (funding, ('count', 'points', 'reserve')))
    if any(type(source.get(name)) is not int or source[name] < 0
           for source, names in required for name in names):
        return False
    return (data['completed'] == data['rewards'] and data['bought'] == data['rewards']+1 and
            data['completed'] < data['limit'] == batch['cycles'] == funding['count'] and
            funding['points'] >= 21*funding['count']+funding['reserve'] and
            batch['completed_start'] <= data['completed'] and
            data['bought'] == batch['bought_start']+batch['bought_seen'] and
            data['rewards'] == batch['rewards_start']+batch['rewards_seen'] and
            batch['bought_seen'] == batch['rewards_seen']+1 and
            21 <= data['observed_sp'] <= 999 and
            data['observed_sp'] == goal_data['last_sp'] ==
                funding['points']-21*batch['rewards_seen'] and
            goal_data['completed'] == goal_data['rewards'] < goal_data['limit'] and
            goal_data['bought'] == goal_data['rewards']+1 and
            goal_data['rewards'] >= batch['rewards_seen'])


def reconcile_after_restart(nav, ledger, cars, challenge, goal=None):
    """Resume a safe boundary, or re-prove the exact untouched pending purchase."""
    from copy import deepcopy
    from .pipeline import ledger_data
    nav.garage_filters_clear = False
    nav.garage_recent_sort_verified = False
    ledger.ready()
    data = cars.data
    phase = data.get('phase')
    record = deepcopy(ledger_data(ledger))
    if _confirmed_unentered_purchase(data, record, challenge.data, goal.data if goal else {}):
        # This phase precedes every claim. A NEW copy may be entered normally;
        # an already-entered copy must additionally be the unique CURRENT car
        # at the first freshly sorted position. Both require an untouched tree
        # and two fresh SP readings matching the funded, unspent balance.
        before = deepcopy((cars.data, goal.data, challenge.data))
        nav.check()
        nav.ensure_home()
        nav.recover_pending_car(data['observed_sp'])
        nav.check()
        if ledger_data(ledger) != record:
            raise RuntimeError('Purchase ledger changed during crash recovery; no mastery checkpoint saved')
        if (cars.data, goal.data, challenge.data) != before:
            raise RuntimeError('Saved run changed during crash recovery; no mastery checkpoint saved')
        cars.save(phase='mastery')
        nav.emit('log', 'Crash recovery verified the newest pending Mad Mike, all six untouched nodes and unchanged SP twice; no car bought or reward counted.')
        return
    safe = not data or phase in {'complete', 'collection'}
    if phase == 'buy':
        safe = record.get('id') == data.get('purchase_before')
    if phase == 'return':
        # The claim was verified and durably counted before this phase. Only
        # navigation remains; changing cars cannot claim that reward again.
        safe = (data.get('mode') == 'Full pipeline' and
                data.get('rewards', 0) == data.get('completed', 0)+1 and
                data.get('bought', 0) >= data['rewards'])
    batch = goal.data.get('batch') if goal else None
    if batch:
        # A bound batch is normal even before the purchase and after the car
        # completes. Let Production.sync settle its absolute counters once.
        safe = safe and batch.get('id') == data.get('id') and all(
            data.get(counter, 0) >= batch.get(start, 0)+batch.get(seen, 0)
            for counter, start, seen in (
                ('rewards', 'rewards_start', 'rewards_seen'),
                ('bought', 'bought_start', 'bought_seen')))
    if not safe:
        raise RuntimeError('Game reopened. A car cycle was interrupted; verify that exact purchased car and its mastery before resuming. No purchase or reward count was changed.')
    nav.ensure_home()
    if challenge.data and challenge.data.get('phase') != 'complete':
        points = nav.available_sp()
        before = challenge.data.get('before_sp')
        if before is not None and points < before:
            raise RuntimeError('SP decreased after the crash. Check the game save before resuming.')
        # Credit only the actual retained gain. Otherwise repeat preparation;
        # never resume a held accelerator from a saved driving stage.
        if before is not None and points > before:
            challenge.save(phase='return', after_sp=points, recovered_after_crash=True)
        else:
            challenge.save(phase='prepare', before_sp=points, recovered_after_crash=True)
        nav.ensure_home()
    if phase == 'buy':
        cars.save(phase='collection')
