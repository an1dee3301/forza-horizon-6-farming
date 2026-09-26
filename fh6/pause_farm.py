"""Select the exact favourite farm car without entering the player's house."""
from .ocr import Document
from .house_entry import pause_ready


def current_farm_car(nav, obs, profile):
    from .farming import farm_car
    import forza_cycle as core
    if not pause_ready(nav,obs):
        return False
    lines=[line for line in obs.doc.lines if 535<=line.center[0]<1100 and 95<=line.center[1]<180]
    return (farm_car(Document(lines),profile) or
            farm_car(nav.reader.read(core.crop(obs.frame,(535,100,565,80))),profile))


def select_from_pause(nav, profile):
    """False requests the existing Home route; never infer current car from a menu."""
    obs=nav.observe()
    if not pause_ready(nav,obs):
        return False
    if not current_farm_car(nav,obs,profile):
        nav.pause_tab('CARS')
        # The visible title wraps as Change / Car. Select the uniquely
        # positioned first line; the existing selector verifies tile focus.
        nav.click_label('pause_menu','Change',(535,270,430,95))
        nav.wait('garage_grid',previous='pause_menu')
        from .garage import set_favorites
        set_favorites(nav,True)
        nav.wait_farm_car_card(profile)
        nav.key('enter')
        result=nav.until(lambda o:o.screen=='car_action' or nav.is_roam(o) or pause_ready(nav,o),
                         'favourite Subaru action or delivery')
        if result.screen=='car_action':
            if not result.doc.has('Get In Car'):
                # The already-current car exposes View/Remove actions but no
                # delivery action. Cancel only; Home verifies its exact header.
                from .farming import FOOTER
                result=nav.wait('car_action', predicate=lambda o:
                    len(o.doc.find('Select An Action')) == 1 and
                    len(o.doc.find('Cancel', FOOTER)) == 1, stable_frames=2)
                if not result.doc.has('Get In Car'):
                    nav.key('esc')
                    nav.wait('garage_grid', previous='car_action')
                    nav.emit('log','Current-car action menu canceled; checking exact farm car through Home.')
                    return False
            nav.click_label('car_action','Get In Car')
            result=nav.until(lambda o:nav.is_roam(o) or pause_ready(nav,o),
                             'Subaru delivered outside home',timeout=max(60,nav.timeout))
        if nav.is_roam(result):
            nav.key('esc')
            nav.until(lambda o:pause_ready(nav,o),'pause after Subaru delivery')
    nav.until(lambda o:current_farm_car(nav,o,profile),'current 1998 Subaru 22B on pause')
    nav._farm_selected_from_pause=True
    nav.emit('log','Favourite Subaru verified from pause; skipped Home entry and exit.')
    return True
