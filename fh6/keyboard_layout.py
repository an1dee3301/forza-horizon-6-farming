"""Keep letter hotkeys out of the game's IME composition window."""
import ctypes
from ctypes import wintypes as wt


class WindowsKeyboard:
    def __init__(self):
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.u.GetForegroundWindow.restype = wt.HWND
        self.u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        self.u.GetWindowThreadProcessId.restype = wt.DWORD
        self.u.GetKeyboardLayout.argtypes = [wt.DWORD]
        self.u.GetKeyboardLayout.restype = wt.HANDLE
        self.u.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(wt.HANDLE)]
        self.u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        self.u.PostMessageW.restype = wt.BOOL

    def current(self):
        window = self.u.GetForegroundWindow()
        thread = self.u.GetWindowThreadProcessId(window, None)
        if not window or not thread:
            raise RuntimeError('Cannot verify the game keyboard layout')
        return window, self.u.GetKeyboardLayout(thread) or 0

    def english(self):
        count = self.u.GetKeyboardLayoutList(0, None)
        layouts = (wt.HANDLE * count)()
        received = self.u.GetKeyboardLayoutList(count, layouts)
        return next((value for value in layouts[:received] if value and value & 0xffff == 0x0409), None)

    def request(self, window, layout):
        # Windows documents WM_INPUTLANGCHANGEREQUEST as a posted message;
        # the receiving application can refuse it, so verification is required.
        if self.u.GetForegroundWindow() != window:
            raise RuntimeError('Game focus changed before keyboard layout recovery')
        if not self.u.PostMessageW(window, 0x0050, 0, layout):
            raise RuntimeError('Could not request the game keyboard layout')


def ensure_game_keyboard(nav, keyboard=None):
    nav.check()  # Includes sync, F7 and game focus; never switch another app.
    keyboard = keyboard or WindowsKeyboard()
    window, layout = keyboard.current()
    if layout & 0xffff == 0x0409:
        return
    english = keyboard.english()
    if english is None:
        raise RuntimeError('The game needs an installed English US keyboard for its hotkeys')
    nav.check()
    keyboard.request(window, english)
    for _ in range(20):
        nav.pause(.1)
        current_window, current_layout = keyboard.current()
        if current_window != window:
            raise RuntimeError('Game focus changed during keyboard layout recovery')
        if current_layout == english:
            nav.emit('log', 'Verified English game keyboard; IME no longer captures letter hotkeys.')
            return
    raise RuntimeError('The game did not accept English keyboard input; no hotkeys sent')
