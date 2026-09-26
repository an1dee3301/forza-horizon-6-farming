"""Acknowledge only the observed Challenges empty-content notification."""
import math
from .ocr import normalize

TITLE=(600,450,700,75)
BODY=(600,525,700,110)
FOOTER=(60,965,200,100)
MESSAGE='this user has not uploaded any content of this type please try again later'


def inside(line,box):
    x,y=line.center;rx,ry,w,h=box
    return rx<=x<rx+w and ry<=y<ry+h


def empty_content_modal(obs):
    if obs.screen not in {'unknown','challenge_browser','challenge_search'}:return False
    title=[t for t in obs.doc.lines if inside(t,TITLE)]
    body=sorted((t for t in obs.doc.lines if inside(t,BODY)),key=lambda t:(t.box[1],t.box[0]))
    footer=[t for t in obs.doc.lines if inside(t,FOOTER)]
    return (len(title)==1 and normalize(title[0].text)=='challenges' and
            normalize(' '.join(t.text for t in body))==MESSAGE and len(footer) in (1,2) and
            normalize(' '.join(t.text for t in sorted(footer,key=lambda t:t.box[0]))) in
            {'ok','0k','enter ok','enter 0k'})


def dismiss_empty_content(nav,obs):
    if not empty_content_modal(obs):return obs
    fresh=nav.observe()
    stamps=[getattr(o,'captured_monotonic',None) for o in (obs,fresh)]
    if (not empty_content_modal(fresh) or fresh.frame is obs.frame or
        any(type(t) not in (int,float) or not math.isfinite(t) for t in stamps) or stamps[1]<=stamps[0]):
        raise RuntimeError('Challenges notification changed before acknowledgement; no input sent')
    nav.check();nav.key('enter')
    # Only a recognized search destination proves dismissal; never repeat Enter.
    return nav.until(lambda o:not empty_content_modal(o) and o.screen in
                     {'challenge_browser','challenge_search','eventlab','share_code'},
                     'Challenges notification dismissed',timeout=5)
