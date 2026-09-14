"""Narrow recovery for the photographed native failed-challenge prompt.

This module only refines OCR evidence. It never authorizes throttle or inputs.
"""
import cv2

from fh6.ocr import Document, Text

TRY_AGAIN = (55, 268, 190, 55)
EXIT_FOOTER = (70, 983, 270, 45)


def _replace_region(document, local, box, padding=0):
    x, y, w, h = box
    retained = [line for line in document.lines if not
                (x <= line.center[0] < x+w and y <= line.center[1] < y+h)]
    for line in local.lines:
        lx, ly, lw, lh = line.box
        translated = Text(line.text, (x+lx-padding, y+ly-padding, lw, lh))
        if x <= translated.center[0] < x+w and y <= translated.center[1] < y+h:
            retained.append(translated)
    return Document(retained)


def refine_failed_prompt(reader, frame, document):
    """Separate yellow prompt text from bright animated sky, retaining all else.

    The caller gates this to unknown, non-driving screens with an exit label.
    Require both native Retry/Quit labels before reading the prompt. The
    existing result predicate still requires Try Again + Retry + Quit.
    """
    if frame is None or frame.shape[:2] != (1080, 1920):
        return document
    x, y, w, h = EXIT_FOOTER
    footer = reader.read(frame[y:y+h, x:x+w])
    if not footer.has('Retry') or not footer.has('Quit'):
        return document
    x, y, w, h = TRY_AGAIN
    crop = frame[y:y+h, x:x+w]
    mask = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV),
                       (20, 100, 140), (65, 255, 255))
    if cv2.countNonZero(mask) < 60:
        return document
    mask = cv2.copyMakeBorder(mask, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=0)
    prompt = reader.read(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR))
    if not prompt.has('Try Again', contains=True):
        return document
    result = _replace_region(document, footer, EXIT_FOOTER)
    return _replace_region(result, prompt, TRY_AGAIN, padding=5)


def result_exit_action(document, result_visible, footer):
    if not result_visible(document):
        return None
    continue_visible = document.has('Continue', footer, contains=True)
    exit_visible = (document.has('Exit', footer, contains=True)
                    or document.has('Quit', footer, contains=True))
    if continue_visible and exit_visible:
        return None
    if continue_visible:
        return 'enter'
    if exit_visible:
        return 'esc'
    return None


class RepeatedResultExit:
    """Two distinct current frames with the same verified result exit action."""
    def __init__(self, action, result_visible, footer):
        self.action, self.result_visible, self.footer = action, result_visible, footer
        self.previous = None

    def __call__(self, observation):
        if result_exit_action(observation.doc, self.result_visible, self.footer) != self.action:
            self.previous = None
            return False
        prior = self.previous
        self.previous = observation
        return (prior is not None and prior is not observation
                and prior.frame is not observation.frame)
