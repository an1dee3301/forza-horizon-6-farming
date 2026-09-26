"""Observed one-Up shortcut; no trial configuration or filesystem access."""
import time
from .ocr import Document


def already_first_new(obs, *, now=None):
    """Reuse captured OCR and pixels; no capture, OCR, input, or state writes."""
    from .navigation import selected_card, recent_sort_verified, fresh_mazda_card
    now = time.monotonic() if now is None else now
    stamp = getattr(obs, 'captured_monotonic', None)
    if (stamp is None or not 0 <= now-stamp <= .8 or
            obs.screen != 'garage_grid' or not recent_sort_verified(obs) or
            len(obs.doc.find('All Cars', (425,145,310,65))) != 1):
        return False
    try:
        box = selected_card(obs.frame)
    except RuntimeError:
        return False
    if any(abs(a-b)>3 for a,b in zip(box,(399,204,341,260))):
        return False
    x,y,w,h = box
    # Entire OCR line must lie inside this card, not merely its center.
    lines = [line for line in obs.doc.lines if
             x <= line.box[0] and y <= line.box[1] and
             line.box[0]+line.box[2] <= x+w and
             line.box[1]+line.box[3] <= y+h]
    return fresh_mazda_card(Document(lines))


def one_up_eligible(obs, *, now=None):
    """Exact observed second-row focus and NEW first card; no navigation guesses."""
    from .navigation import selected_card, recent_sort_verified, fresh_mazda_card
    now=time.monotonic() if now is None else now
    stamp=getattr(obs,'captured_monotonic',None)
    if (stamp is None or not 0<=now-stamp<=.8 or obs.screen!='garage_grid' or
        not recent_sort_verified(obs) or len(obs.doc.find('All Cars',(425,145,310,65)))!=1):
        return False
    try:box=selected_card(obs.frame)
    except RuntimeError:return False
    if any(abs(a-b)>3 for a,b in zip(box,(399,456,341,260))):return False
    x,y,w,h=399,204,341,260
    lines=[line for line in obs.doc.lines if x<=line.box[0] and y<=line.box[1]
           and line.box[0]+line.box[2]<=x+w and line.box[1]+line.box[3]<=y+h]
    return fresh_mazda_card(Document(lines))


def try_one_up(nav, obs):
    """One reversible Up, then actual first-card proof. No Enter or Up retry."""
    if not one_up_eligible(obs):return None
    generation=nav.focus_generation
    before=obs.captured_monotonic
    nav.check()
    if nav.focus_generation!=generation:return None
    nav.key('up')
    def proved(current):
        if nav.focus_generation!=generation:
            raise RuntimeError('Focus changed during first-card trial')
        return (current is not obs and current.frame is not obs.frame and
                current.captured_monotonic is not None and current.captured_monotonic>before
                and already_first_new(current))
    try:
        return nav.wait('garage_grid',predicate=proved,timeout=.8,stable_frames=1)
    except RuntimeError as exc:
        # A dropped reversible Up gets the existing Jump route, never another
        # Up. Unknown screen/stop/focus errors belong to normal recovery.
        if (str(exc).startswith('Timed out waiting for ') and
            getattr(nav,'last',None) is not None and nav.last.screen=='garage_grid' and
            nav.focus_generation==generation):
            return None
        raise


