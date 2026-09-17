"""Reuse a visibly retained challenge code without opening its text editor."""
import json
import re
from pathlib import Path

import cv2
import numpy as np

import forza_cycle as core

from .ocr import normalize


# English 1080p Search dialog, verified against the recorded search form.
# The input is the last row; title/creator text must never satisfy this proof.
SEARCH_TITLE = (550, 300, 820, 90)
SHARE_LABEL = (550, 645, 400, 80)
SHARE_VALUE = (1010, 645, 305, 80)
CONFIRM = (550, 715, 820, 65)
TEMPLATE_VERSION = 1


def _template_paths(code, root=None):
    directory = Path(root) if root is not None else core.BASE/'recognition'/'share_codes'
    return directory/(code+'.png'), directory/(code+'.json')


def _field_mask(frame):
    if frame is None or getattr(frame, 'shape', None) != (1080, 1920, 3):
        return None
    x, y, w, h = SHARE_VALUE
    # Exclude the focus border. Only the field interior may prove the digits.
    gray = cv2.cvtColor(frame[y+4:y+h-4, x+4:x+w-4], cv2.COLOR_BGR2GRAY)
    mask = (gray < 185).astype(np.uint8)*255
    if not 25 <= int(np.count_nonzero(mask)) <= mask.size*.45:
        return None
    return mask


def remember_retained_code(obs, share_code, *, root=None):
    """Persist pixels only after OCR has independently proved the exact code."""
    field, _ = _retained_code_proof(obs, share_code, allow_template=False)
    mask = _field_mask(getattr(obs, 'frame', None))
    if field is None or mask is None:
        return False
    image, metadata = _template_paths(share_code, root)
    image.parent.mkdir(parents=True, exist_ok=True)
    temporary = image.with_suffix('.tmp.png')
    if not cv2.imwrite(str(temporary), mask):
        return False
    temporary.replace(image)
    data = dict(version=TEMPLATE_VERSION, share_code=share_code,
                shape=list(mask.shape), source='exact_ocr_after_numeric_editor')
    temporary_meta = metadata.with_suffix('.tmp')
    temporary_meta.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary_meta.replace(metadata)
    return True


def retained_code_template(obs, share_code, *, root=None):
    """Exact profile-bound OpenCV proof for OCR-hostile retained digits."""
    if getattr(obs, 'screen', None) != 'challenge_search':
        return False
    image, metadata = _template_paths(share_code, root)
    try:
        data = json.loads(metadata.read_text(encoding='utf-8'))
        reference = cv2.imread(str(image), cv2.IMREAD_GRAYSCALE)
    except (OSError, ValueError):
        return False
    current = _field_mask(getattr(obs, 'frame', None))
    if (data.get('version') != TEMPLATE_VERSION or data.get('share_code') != share_code
            or reference is None or current is None
            or list(reference.shape) != data.get('shape')
            or reference.shape != current.shape):
        return False
    # Allow at most two pixels of native text jitter. Different nine-digit
    # values diverge strongly; two independent frames are still required by
    # reuse_search before Confirm is allowed.
    padded = cv2.copyMakeBorder(current, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=0)
    score = float(cv2.matchTemplate(padded, reference, cv2.TM_CCOEFF_NORMED).max())
    return np.isfinite(score) and score >= .965


def retained_code(obs, share_code):
    """Return the exact code's field box, or None for an ambiguous form."""
    return _retained_code_proof(obs, share_code)[0]


def _retained_code_proof(obs, share_code, *, allow_template=True):
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
        if allow_template and retained_code_template(obs, share_code):
            return SHARE_VALUE, None
        return None, 'field_absent' if not values else 'field_ambiguous'
    value = values[0]
    text = value.text.strip()
    # Windows OCR sometimes inserts punctuation between the three visible
    # digit groups. Accept separators only when all nine digits still exactly
    # match the configured code; letters, missing digits and extra digits stay
    # rejected. This lets repeat farms confirm the retained field without
    # reopening and clearing the editor.
    # OCR does not always preserve both visual group separators: depending on
    # the background it can return 155439 962 or 155 439962 as well as the
    # normal 155 439 962. Permit only digits and the known separator glyphs,
    # then require the complete exact nine-digit value. Letters, signs,
    # missing/extra digits and another share code still fail closed.
    if not re.fullmatch(r'[0-9\s,.-]+', text):
        if allow_template and retained_code_template(obs, share_code):
            return SHARE_VALUE, None
        return None, 'invalid_digits'
    groups = [part for part in re.split(r'[\s,.-]+', text) if part]
    if [len(part) for part in groups] not in ([9], [6, 3], [3, 6], [3, 3, 3]):
        if allow_template and retained_code_template(obs, share_code):
            return SHARE_VALUE, None
        return None, 'invalid_digits'
    digits = re.sub(r'[\s,.-]+', '', text)
    if not re.fullmatch(r'[0-9]{9}', digits):
        if allow_template and retained_code_template(obs, share_code):
            return SHARE_VALUE, None
        return None, 'invalid_digits'
    if digits != share_code:
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
