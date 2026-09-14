"""Reuse a visibly retained challenge code without opening its text editor."""
import re

from .ocr import normalize


# English 1080p Search dialog, verified against the recorded search form.
# The input is the last row; title/creator text must never satisfy this proof.
SEARCH_TITLE = (550, 300, 820, 90)
SHARE_LABEL = (550, 645, 400, 80)
SHARE_VALUE = (1010, 645, 305, 80)
CONFIRM = (550, 715, 820, 65)


def retained_code(obs, share_code):
    """Return the exact code's field box, or None for an ambiguous form."""
    return _retained_code_proof(obs, share_code)[0]


def _retained_code_proof(obs, share_code):
    """Same proof with a fixed diagnostic reason; never return field text."""
    if not isinstance(share_code, str) or not re.fullmatch(r'[0-9]{9}', share_code):
        return None, 'profile_code_invalid'
    if obs.screen != 'challenge_search':
        return None, 'screen_not_search'
    doc = obs.doc
    titles = len(doc.find('Search', SEARCH_TITLE))
    if titles != 1:
        return None, 'title_missing' if not titles else 'title_ambiguous'
    confirms = len(doc.find('Confirm', CONFIRM))
    if confirms != 1:
        return None, 'confirm_missing' if not confirms else 'confirm_ambiguous'
    labels = doc.find('Share Code', SHARE_LABEL)
    if len(labels) != 1:
        return None, 'share_label_missing' if not labels else 'share_label_ambiguous'
    label = labels[0]
    rx, ry, rw, rh = SHARE_VALUE
    # Scope to both the known value column and the actual label's row. A
    # code visible in another Search field is not the selected share code.
    values = [line for line in doc.lines
              if rx <= line.center[0] < rx+rw and ry <= line.center[1] < ry+rh
              and abs(line.center[1]-label.center[1]) <= 18
              and normalize(line.text)]
    if len(values) != 1:
        return None, 'field_absent' if not values else 'field_ambiguous'
    value = values[0]
    text = value.text.strip()
    if not re.fullmatch(r'(?:[0-9]{9}|[0-9]{3}\s+[0-9]{3}\s+[0-9]{3})', text):
        return None, 'invalid_digits'
    if ''.join(text.split()) != share_code:
        return None, 'wrong_digits'
    return value.box, None


def _fallback(nav, reason):
    # One bounded message for this fallback, based entirely on already-read
    # observations. Never capture again, log user fields, or fail navigation.
    try:
        nav.emit('log', 'Retained search fallback: ' + reason)
    except Exception:
        pass
    return False


def reuse_search(nav, share_code):
    """Confirm a twice-observed retained code; False keeps normal entry intact.

    Both observations are obtained here, never from nav.last or a caller's
    earlier screen. Failed result verification propagates after Confirm, so
    the caller cannot silently submit another search in the same attempt.
    """
    current=nav.observe()
    if current.screen not in {'challenge_search','unknown'}:
        raise RuntimeError(f'Expected challenge_search; found {current.screen}; no search input sent')
    first, reason = _retained_code_proof(current, share_code)
    if first is None:
        return _fallback(nav, reason)
    nav.pause(.06)
    second, reason = _retained_code_proof(nav.observe(), share_code)
    if second is None:
        return _fallback(nav, 'second_frame_disagreement/' + reason)
    if any(abs(a-b) > 3 for a, b in zip(first, second)):
        return _fallback(nav, 'second_frame_moved_box')
    nav.select('Confirm', CONFIRM)
    nav.wait_challenge_result()
    return True
