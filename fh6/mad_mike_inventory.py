"""Read-only proof that the filtered Mad Mike garage is empty."""
from .analytics import save
from .garage import FILTER_REGION
from .garage_cleanup import mad_mike_lines
from .navigation import selected_card, SelectedCardError


FILTERS = ('Duplicates', 'S1', 'Drift Cars')


def toggle_filter(nav, label):
    aliases = ('S1', 'Sl') if label == 'S1' else (label,)
    for _ in range(65):
        obs = nav.wait('garage_filter')
        matches = [line for name in aliases for line in obs.doc.find(name, FILTER_REGION)]
        if len(matches) == 1:
            nav.keyboard_select('garage_filter', matches[0].text, FILTER_REGION)
            nav.pause(.15)
            return
        nav.key('down')
        nav.pause(.08)
    raise RuntimeError(f'Filter {label} was not found; no selection inferred')


def prepare_filter(nav):
    """Reset My Cars, then establish the exact Mad Mike cleanup filter."""
    from .garage import set_favorites
    from .profiles import load_profile

    # Cleanup cannot remove the active car. The single Favorite is the 22B.
    nav.select_farm_car(load_profile())
    nav.ensure_home()
    grid = nav.my_cars()
    grid = set_favorites(nav, False)
    if not grid.doc.has('Filter', (65, 975, 1700, 65), contains=True):
        raise RuntimeError('My Cars filter control is unavailable')
    nav.key('y')
    nav.wait('garage_filter', previous='garage_grid')
    for label in FILTERS:
        toggle_filter(nav, label)
    nav.key('esc')
    return nav.wait('garage_grid', previous='garage_filter')


def empty_grid(obs):
    if mad_mike_lines(obs.doc):
        return False
    try:
        selected_card(obs.frame)
    except SelectedCardError as exc:
        return exc.matches == 0
    return False


def remaining_mazda(nav):
    """Use the filtered manufacturer index to reveal any final Mazda copy."""
    nav.key('backspace')
    obs = nav.wait('manufacturers', previous='garage_grid')
    region = (250,255,1410,650)
    if obs.doc.has('MAZDA', region):
        nav.keyboard_select('manufacturers', 'MAZDA', region)
        return nav.wait('garage_grid', previous='manufacturers')
    # This account's complete S1 Drift index fits its first row. Requiring
    # every known remaining manufacturer twice avoids an OCR-empty shortcut.
    expected = {'DEBERTI', 'FORMULA DRIFT', 'JAGUAR'}
    def absent(current):
        names = {line.text.upper().replace("DEBERT'", 'DEBERTI') for line in current.doc.lines
                 if 250 <= line.center[0] <= 1660 and 255 <= line.center[1] <= 905}
        return names == expected
    nav.wait('manufacturers', predicate=absent)
    nav.key('esc')
    nav.wait('garage_grid', previous='manufacturers')
    return None


def verify_zero(nav, tracker):
    """Prove both current and toggled Duplicates filter states are empty."""
    first = prepare_filter(nav)
    if not empty_grid(first):
        raise RuntimeError('Mad Mike inventory is not empty; mission remains paused')
    if not first.doc.has('Filter', (65,975,1700,65), contains=True):
        raise RuntimeError('Garage filter control is unavailable; mission remains paused')
    nav.key('y')
    nav.wait('garage_filter', previous='garage_grid')
    # Reopening starts at the first row.
    toggle_filter(nav, 'Duplicates')
    nav.key('esc')
    second = nav.wait('garage_grid', previous='garage_filter')
    if not empty_grid(second) and remaining_mazda(nav) is not None:
        raise RuntimeError('Mad Mike inventory is not empty after toggling Duplicates; mission remains paused')
    tracker.event('garage_cleanup_completed', {'verified_empty': True})
    tracker.data['garage_cleanup']['completion_source'] = 'screen_verified_both_duplicate_states_empty'
    save(tracker.root/'analytics.json', tracker.data)
    return 0
