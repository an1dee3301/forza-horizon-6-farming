"""Read-only display geometry guard for calibrated capture and inputs."""
import ctypes
from ctypes import wintypes as wt


class DisplayChanged(RuntimeError):
    pass


def monitor_bounds_at(x, y):
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wt.DWORD), ('monitor', wt.RECT),
                    ('work', wt.RECT), ('flags', wt.DWORD)]
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
    user.MonitorFromPoint.restype = wt.HANDLE
    user.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MonitorInfo)]
    handle = user.MonitorFromPoint(wt.POINT(x, y), 0)
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    if not handle or not user.GetMonitorInfoW(handle, ctypes.byref(info)):
        return None
    r = info.monitor
    return r.left, r.top, r.right-r.left, r.bottom-r.top


class DisplayGuard:
    def __init__(self, monitor, bounds=monitor_bounds_at):
        self.expected = tuple(monitor[k] for k in ('left', 'top', 'width', 'height'))
        if self.expected[2:] != (1920, 1080):
            raise DisplayChanged('Restore the selected Windows display to 1920 x 1080 before running.')
        self.bounds = bounds

    def check(self):
        x, y, w, h = self.expected
        actual = self.bounds(x+w//2, y+h//2)
        if actual != self.expected:
            size = f'{actual[2]} x {actual[3]}' if actual else 'unavailable'
            raise DisplayChanged(f'Display changed to {size}. Waiting for the original 1920 x 1080 display; all game inputs are paused.')
