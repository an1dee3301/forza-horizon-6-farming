"""Windows pointer input for games that do not follow SetCursorPos alone."""
import ctypes


def mouse_button(down, button='left', **kwargs):
    flags = {'left': (2, 4), 'right': (8, 16), 'middle': (32, 64)}
    if button not in flags:
        raise ValueError('Unsupported mouse button')
    ctypes.windll.user32.mouse_event(flags[button][0 if down else 1], 0, 0, 0, 0)


def mouse_down(x=None, y=None, button='left', **kwargs):
    import pyautogui
    pyautogui.failSafeCheck()
    if x is not None and y is not None:
        move_pointer(x, y)
    mouse_button(True, button)


def mouse_up(x=None, y=None, button='left', **kwargs):
    mouse_button(False, button)


def move_pointer(x, y, duration=0, **kwargs):
    user = ctypes.windll.user32
    left, top = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
    width, height = user.GetSystemMetrics(78), user.GetSystemMetrics(79)
    if width < 2 or height < 2:
        raise RuntimeError('Windows did not report a usable desktop size')
    nx = round((int(x)-left)*65535/(width-1))
    ny = round((int(y)-top)*65535/(height-1))
    if not 0 <= nx <= 65535 or not 0 <= ny <= 65535:
        raise RuntimeError('Pointer target is outside the desktop')
    # MOVE | ABSOLUTE | VIRTUALDESK also produces an actual mouse input event.
    user.mouse_event(0xC001, nx, ny, 0, 0)


def install_pointer_input():
    import pyautogui
    # Every input is already explicitly paced and guarded by the application.
    # PyAutoGUI's implicit post-call sleep otherwise runs after BOTH key edges.
    pyautogui.PAUSE = 0
    pyautogui.moveTo = move_pointer
    pyautogui.mouseDown = mouse_down
    pyautogui.mouseUp = mouse_up
