"""Conservative refinement policy for an already observed farm countdown.

This only skips the unrelated footer/home OCR pass. Full-frame OCR, the
dedicated timer crop, focus/sync checks and the driver's timer watchdog still
run on every observation; no previous-frame timer evidence is reused.
"""
from math import isfinite


def active_countdown_only(doc, remaining):
    """True when footer refinement cannot add a currently needed farm action.

    ``remaining`` must come from this observation's refined timer document.
    The final two seconds and any hint of a result, menu or pause stay on the
    full refinement path, including partially recognized result dialogs.
    """
    if isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
        return False
    if not isfinite(remaining) or remaining <= 2:
        return False
    # A timer may remain underneath a result/pause overlay. Even one action
    # label is enough to retain the extra result/footer pass; it need not
    # satisfy the complete result detector yet.
    possible_overlay = (
        'Retry', 'Quit', 'Continue', 'Exit', 'Try Again', 'Restart', 'Resume',
        'Paused', 'Challenge Complete', 'Challenge Completed',
        'Challenge Failed', 'Success', 'Completed', 'Failed',
    )
    return not any(doc.has(label, contains=True) for label in possible_overlay)
