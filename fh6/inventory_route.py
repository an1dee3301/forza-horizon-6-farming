"""Read actual saved spins at unpaid boundaries; never infer inventory from output."""
import os
import time

from .farm_balance import game_identity


def dialog_free(obs):
    return not any(obs.doc.has(label) for label in ('Yes', 'No', 'Cancel', 'Confirm', 'Buy House',
                                                   'Quit Event', 'Restart Event', 'Select An Action'))


def refresh_inventory(nav, goal, *, interval=600, clock=time.monotonic, stay_pause=False):
    """Once per worker/game start, then at natural batch or farm boundaries.

    Callers must have reconciled any pending purchase first. No route runs while
    driving or in a partially processed car. Reporting remains asynchronous.
    """
    observer = getattr(nav, 'account_observer', None)
    account = getattr(observer, 'gamertag', None)
    if not isinstance(account, str) or not account:
        return None  # Recognition-only and old module configurations have no reader.
    nav.check()
    identity = game_identity(nav)
    if identity is None:
        raise RuntimeError('Inventory refresh needs the current game identity')
    key = (goal['id'], os.getpid(), identity, account.casefold())
    previous = getattr(nav, '_inventory_refreshed', None)
    if (isinstance(previous, tuple) and len(previous) == 3 and previous[0] == key
            and 0 <= clock() - previous[1] < interval):
        return previous[2]
    obs = nav.observe()
    if not dialog_free(obs):
        raise RuntimeError('Inventory refresh is blocked by a dialog; no navigation sent')
    from .house_entry import pause_ready
    previous_tab = None
    return_home = False
    if nav.is_pause(obs):
        # Preserve the fast repeat-farm Cars route after reading the other tab.
        from .pause_tabs import pause_tab_steps, PAUSE_TABS
        previous_tab = next((tab for tab in PAUSE_TABS if pause_tab_steps(obs, tab) == ('pgdn', 0)), None)
        if previous_tab is None or not pause_ready(nav, obs):
            raise RuntimeError('Inventory refresh needs a verified selected pause tab; no navigation sent')
    elif nav.is_roam(obs):
        nav.until(lambda o: dialog_free(o) and nav.is_roam(o), 'free roam before reading saved wheelspins')
        nav.key('esc')
        nav.until(lambda o: dialog_free(o) and pause_ready(nav, o), 'pause menu for saved wheelspins')
    else:
        if obs.screen not in {'cars', 'campaign', 'home_tab', 'upgrades', 'collection_grid',
                              'journal', 'discover', 'manufacturers', 'showroom', 'garage_grid'}:
            raise RuntimeError('Inventory refresh needs a known unpaid menu; no navigation sent')
        nav.ensure_home()
        return_home = not stay_pause
        # Use the same recognized menu action as the farm launcher. The footer
        # shortcut is not consistently present across Home tabs/UI states.
        from .navigation import LEFT
        nav.home_tab('campaign')
        nav.until(lambda o: dialog_free(o) and nav.is_home(o)
                  and o.screen == 'campaign' and o.doc.has('Drive', LEFT),
                  'home Campaign Drive action before inventory refresh')
        nav.click_label('campaign', 'Drive', LEFT)
        nav.until(lambda o: dialog_free(o) and nav.is_roam(o), 'leaving home to read saved wheelspins', timeout=max(60, nav.timeout))
        nav.key('esc')
        nav.until(lambda o: dialog_free(o) and pause_ready(nav, o), 'pause menu for saved wheelspins')
    intent = getattr(nav, '_inventory_restore', None)
    if isinstance(intent, tuple) and len(intent) == 2 and intent[0] == key:
        return_home = intent[1] == 'home'
        previous_tab = None if return_home else intent[1]
    destination = 'home' if return_home else previous_tab
    nav._inventory_restore = (key, destination)
    nav.pause_tab('MY HORIZON')
    from .inventory import verify_inventory
    import forza_cycle as core
    proof = verify_inventory(nav, account, goal_id=goal['id'], root=core.BASE/'runs',
                             worker_run=getattr(nav, 'worker_run', None),
                             mission_rewards=goal.get('rewards'))
    if proof is None:
        raise RuntimeError('Saved wheelspin counters did not agree on two fresh My Horizon readings')
    nav.check()
    if game_identity(nav) != identity:
        raise RuntimeError('Game changed during saved wheelspin inventory refresh')
    correction=(proof.get('hybrid_correction') or {}).get('delta')
    correction_text=f" Hybrid estimate corrected by {correction:+,} SW." if type(correction) is int and correction else ''
    nav.emit('log', f"Actual saved inventory verified: {proof['super_wheelspins']:,} Super Wheelspins; "
                   f"{proof['wheelspins']:,} Wheelspins.{correction_text}")
    if previous_tab and previous_tab != 'MY HORIZON':
        nav.pause_tab(previous_tab)
    elif return_home:
        nav.ensure_home()
    nav.check()
    if game_identity(nav) != identity:
        raise RuntimeError('Game changed while restoring the menu after inventory refresh')
    nav._inventory_restore = None
    nav._inventory_refreshed = (key, clock(), proof)
    return proof
