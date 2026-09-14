"""A bounded Graphics Capture snapshot of one already-verified game HWND."""
from threading import Event


def capture_window(handle, timeout=1.5):
    from windows_capture import WindowsCapture
    capture = WindowsCapture(window_hwnd=int(handle), cursor_capture=False,
                             secondary_window=False, minimum_update_interval=100)
    finished, frames = Event(), []

    @capture.event
    def on_frame_arrived(frame, capture_control):
        frames.append(frame.convert_to_bgr().frame_buffer.copy())
        capture_control.stop()
        finished.set()

    @capture.event
    def on_closed():
        finished.set()

    control = capture.start_free_threaded()
    if not finished.wait(timeout):
        control.stop()
    return frames[0] if frames else None
