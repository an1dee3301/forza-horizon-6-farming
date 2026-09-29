"""The virtual pad must stay bound to one live FH6 process and foreground."""

import ctypes
from ctypes import wintypes as wt
from types import SimpleNamespace

from fh6.game_lifecycle import WindowsGame


def test_foreground_requires_same_pid_and_creation_time():
    game = WindowsGame.__new__(WindowsGame)
    foreground_pid = 4242

    def get_foreground_window():
        return 123

    def get_window_pid(_hwnd, output):
        ctypes.cast(output, ctypes.POINTER(wt.DWORD)).contents.value = foreground_pid

    game.u = SimpleNamespace(GetForegroundWindow=get_foreground_window,
                             GetWindowThreadProcessId=get_window_pid)
    game.identity = lambda: ["4242:creation-a"]
    assert game.foreground_matches(("4242:creation-a",)) is True
    assert game.foreground_matches(("4242:creation-b",)) is False
    assert game.foreground_matches(("4243:creation-a",)) is False
    assert game.foreground_matches(("4242:creation-a", "4242:creation-b")) is False
