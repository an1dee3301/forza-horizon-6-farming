"""Optional owned-house HUD probe from an already-open free-roam pause menu.

Full navigator observations retain focus, sync, stop and dialog
guards. A failed read never sends Enter, and the fallback remains on pause.
"""
import time


def pause_ready(nav,obs):
    if not nav.is_pause(obs):
        return False
    top=(60,100,1770,150)
    return (all(len(obs.doc.find(label,top))==1 for label in
                ('CAMPAIGN','CARS','MY HORIZON','ONLINE','CREATIVE HUB','STORE'))
            and len(obs.doc.find('Back',(220,980,150,60),contains=True))==1)


def owned_signature(nav,obs):
    """Prove the native owned-property interaction, not a Return Home tile."""
    if obs.screen!='unknown' or not nav.is_roam(obs) or nav.is_pause(obs):
        return None
    doc=obs.doc
    fields=(doc.find('Owned',(60,300,600,240)),
            doc.find('Enter House',(60,480,620,150),contains=True),
            doc.find('ANNA',(60,965,1800,100),contains=True))
    if not all(len(matches)==1 for matches in fields):
        return None
    if any(doc.has(label) for label in
           ('Yes','No','Cancel','Confirm','Buy House','Fast Travel Home','Return Home',
            'Quit Event','Restart Event')):
        return None
    return tuple(value for matches in fields for value in matches[0].box)


def fresh_pair(previous,current):
    return (previous is not None and current is not previous
            and current.frame is not previous.frame)


def _probe_owned_house_hud(nav,*,timeout,clock,allow_pause):
    """Shared fresh-frame HUD proof, with no blind fallback input."""
    deadline=clock()+timeout
    previous=None
    previous_signature=None
    pause_count=roam_count=0
    while clock()<deadline:
        current=nav.observe()
        distinct=fresh_pair(previous,current)
        signature=owned_signature(nav,current)
        if (clock()<deadline and distinct and signature is not None and previous_signature is not None
                and all(abs(a-b)<=3 for a,b in zip(signature,previous_signature))):
            nav.emit('log','Owned-house HUD verified on two fresh frames; entering directly.')
            nav.key('enter')
            nav.until(nav.is_home,'entering owned home',timeout=max(60,nav.timeout))
            return 'home'
        pause_count=pause_count+1 if distinct and pause_ready(nav,current) else int(pause_ready(nav,current))
        roam=nav.is_roam(current) and not nav.is_pause(current)
        roam_count=roam_count+1 if distinct and roam else int(roam)
        if pause_count>=2:
            if not allow_pause:
                raise RuntimeError('Pause appeared during owned-house HUD grace; no Escape sent')
            # Escape was ignored; the still-open pause menu is the old fallback.
            nav.emit('log','Owned-house probe left pause unchanged; keeping verified travel fallback.')
            return 'pause'
        if nav.is_home(current):
            nav.until(nav.is_home,'home after entrance check',timeout=timeout)
            return 'home'
        if current.screen not in {'unknown','pause_menu'} and not nav.is_pause(current):
            raise RuntimeError('Unexpected screen during owned-house check; no house Enter sent')
        previous,previous_signature=current,signature
        remaining=deadline-clock()
        if remaining>0:
            nav.pause(min(.06 if nav.fast_navigation else .2,remaining))
    if roam_count>=2:
        return 'roam'
    raise RuntimeError('Owned-house check did not reach a verified HUD or pause; no house Enter sent')


def try_owned_house_from_roam(nav,*,timeout=.6,clock=time.monotonic):
    """Give a late native prompt a short grace before opening travel menus.

    The caller has just observed free roam. True means verified home; False
    guarantees two fresh roam observations so the caller may open pause once.
    """
    result=_probe_owned_house_hud(nav,timeout=timeout,clock=clock,allow_pause=False)
    if result=='roam':
        nav.emit('log','No owned-house prompt after bounded free-roam grace; opening pause once.')
    return result=='home'


def try_owned_house_from_pause(nav,*,timeout=2.0,clock=time.monotonic):
    """Return True at verified home; False leaves a verified pause fallback.

    Called only from ensure_home's already-open pause branch. Two fresh complete
    pause observations authorize Escape. Two fresh stable Owned/Enter House/ANNA
    observations authorize exactly one Enter. If no property prompt appears,
    return to pause from two verified roam frames within the short probe bound.
    """
    try:
        nav.until(lambda obs:pause_ready(nav,obs),'pause menu before owned-house check',timeout=timeout)
    except RuntimeError as exc:
        if str(exc)!='Timed out verifying pause menu before owned-house check; no input retry':
            raise
        # Missing optional footer/complete-row proof does not authorize Escape.
        # Re-establish the normal two-frame pause proof before old navigation.
        nav.until(nav.is_pause,'pause menu after unavailable house proof',timeout=timeout)
        nav.emit('log','Optional house-entry pause proof unavailable; keeping verified travel fallback.')
        return False
    nav.key('esc')
    result=_probe_owned_house_hud(nav,timeout=timeout,clock=clock,allow_pause=True)
    if result=='home':
        return True
    if result=='pause':
        return False
    nav.key('esc')
    nav.until(lambda obs:pause_ready(nav,obs),'pause menu after owned-house check',timeout=timeout)
    nav.emit('log','No unique owned-house prompt in bounded HUD check; using verified travel fallback.')
    return False
