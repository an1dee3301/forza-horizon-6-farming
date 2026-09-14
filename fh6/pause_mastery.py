"""Read and activate the wrapped Cars-pause mastery title using fresh UI proof."""
import time

from .navigation import focus_boxes
from .ocr import Text
from .pause_tabs import pause_tab_steps

TITLE = (535, 555, 360, 135)


def target_title(obs):
    """Accept one exact title, or its two aligned lines, only on selected CARS."""
    if obs.screen != 'pause_menu' or pause_tab_steps(obs, 'CARS') != ('pgdn', 0):
        return None
    full = obs.doc.find('Car Mastery', TITLE)
    car = obs.doc.find('Car', TITLE)
    mastery = obs.doc.find('Mastery', TITLE)
    if len(full) == 1 and not car and not mastery:
        result = full[0]
    elif not full and len(car) == len(mastery) == 1:
        a, b = car[0].box, mastery[0].box
        # The actual title wraps vertically, left aligned, with a short gap.
        if abs(a[0]-b[0]) > 12 or not 0 <= b[1]-(a[1]+a[3]) <= 24:
            return None
        x, y = min(a[0],b[0]), a[1]
        result = Text('Car Mastery', (x,y,max(a[0]+a[2],b[0]+b[2])-x,b[1]+b[3]-y))
    else:
        return None
    x,y,w,h = result.box
    rx,ry,rw,rh = TITLE
    return result if w>0 and h>0 and rx<=x and ry<=y and x+w<=rx+rw and y+h<=ry+rh else None


def _stable(a,b):
    return all(abs(x-y)<=3 for x,y in zip(a,b))


def _ready(nav, deadline):
    """Two different fresh observations of the selected tab, title and focus."""
    previous = None
    reason = 'title_or_selected_cars_missing'
    while time.monotonic() < deadline:
        obs = nav.observe()  # Preserves full F7, sync, focus and danger checks.
        if time.monotonic() >= deadline:
            break
        if obs.screen not in {'pause_menu','unknown'}:
            return None, 'unexpected_screen_'+obs.screen
        target = target_title(obs)
        boxes = focus_boxes(obs.frame) if target is not None else []
        if target is not None and len(boxes)==1:
            proof=(obs,target,boxes[0])
            if (previous is not None and obs is not previous[0]
                    and _stable(target.box,previous[1].box) and _stable(boxes[0],previous[2])):
                return proof, None
            previous=proof
            reason='second_fresh_frame_missing'
        else:
            previous=None
            reason='ambiguous_focus' if target is not None else 'title_or_selected_cars_missing'
        nav.pause(min(.04,max(0.,deadline-time.monotonic())))
    return None, reason


def open_pause_mastery(nav, timeout=2.5):
    """No guessed click: derive arrows, verify exact focus, then Enter once."""
    deadline=time.monotonic()+timeout
    for _ in range(6):
        proof,reason=_ready(nav,deadline)
        if proof is None:
            nav.emit('log','Pause mastery proof unavailable: '+reason+'; keeping home fallback.')
            return False
        obs,target,box=proof
        x,y,w,h=box
        tx,ty,tw,th=target.box
        if x<=tx and y<=ty and tx+tw<=x+w and ty+th<=y+h:
            nav.emit('log','Pause Car Mastery title and keyboard focus verified on two fresh Cars frames.')
            nav.key('enter')
            return True
        cx,cy=target.center
        direction='left' if cx<x else 'right' if cx>x+w else 'up' if cy<y else 'down'
        nav.key(direction)
    nav.emit('log','Pause mastery navigation bound reached; keeping home fallback.')
    return False
