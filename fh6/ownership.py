"""One input-owning worker across every panel and independent module."""
import ctypes


class WorkerLease:
    def __init__(self):
        self.handle = None

    def __enter__(self):
        k = ctypes.windll.kernel32
        k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k.CreateMutexW.restype = ctypes.c_void_p
        handle = k.CreateMutexW(None, True, 'Local\\FH6AutoWorker')
        error = k.GetLastError()
        if not handle:
            raise RuntimeError('Could not reserve the game input worker')
        if error == 183:
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            k.CloseHandle(handle)
            raise RuntimeError('Another FH6 module is running. Stop it before starting another.')
        self.handle = handle
        return self

    def __exit__(self, *args):
        if self.handle:
            k = ctypes.windll.kernel32
            k.ReleaseMutex.argtypes = [ctypes.c_void_p]
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            k.ReleaseMutex(self.handle)
            k.CloseHandle(self.handle)
            self.handle = None
