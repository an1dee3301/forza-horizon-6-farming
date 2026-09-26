"""Screen-verified removal of filtered Mad Mike duplicates.

The caller must already be on My Cars with S1, Drift Cars and Duplicates
selected. Every destructive input is preceded by a fresh identity or dialog
check; an empty result completes cleanup and any ambiguity stops it.
"""
import time
import configparser
from pathlib import Path

import cv2
import numpy as np
import forza_cycle as core
from .navigation import selected_card, SelectedCardError, label_focused
from .garage import FILTER_REGION
from .cleanup_spacing import spaced_four_to_focus


FILTER_NAME = 'S1 + Drift Cars + Duplicates'
_panel_updated_at = 0.0


def update_panel(tracker, message, *, force=False):
    """Expose cleanup stock counts in the currently open local panel."""
    global _panel_updated_at
    current = time.monotonic()
    if not force and current-_panel_updated_at < .75:
        return
    root = Path(__file__).resolve().parent.parent
    state_root = root/'Forza-Horizon-6-Wheelspin-Macro-main'/'LocalState'
    candidates = [p for p in state_root.glob('*/status.ini') if p.is_file()]
    if not candidates:
        return
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    progress = tracker.data.get('progress') or {}
    cleanup = tracker.data.get('garage_cleanup') or {}
    bought = progress.get('bought', 0) if type(progress.get('bought', 0)) is int else 0
    processed = min(bought, progress.get('rewards', 0)) if type(progress.get('rewards', 0)) is int else 0
    removed = cleanup.get('removed', 0) if type(cleanup.get('removed', 0)) is int else 0
    actual_zero = cleanup.get('verified_empty') is True
    for _ in range(3):
        try:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(path, encoding='utf-16')
            if not parser.has_section('run'):
                return
            run = parser['run']
            run.update(stage='garage cleanup', message=message,
                       mad_mike_bought=str(bought), mad_mike_processed=str(processed),
                       mad_mike_removed=str(removed),
                       mad_mike_left=str(0 if actual_zero else max(0, bought-removed)),
                       mad_mike_left_prefix='' if actual_zero else '≤')
            temp = path.with_suffix('.cleanup.tmp')
            with temp.open('w', encoding='utf-16') as stream:
                parser.write(stream)
            temp.replace(path)
            _panel_updated_at = current
            return
        except (OSError, configparser.Error):
            time.sleep(.05)


def mad_mike_lines(doc):
    return doc.find('MAD MIKE', contains=True)


def complete_confirmation(obs):
    return len(obs.doc.find('Yes')) == 1 and len(obs.doc.find('No')) == 1


def complete_action(obs):
    return (len(obs.doc.find('Remove Car From Garage')) == 1 and
            len(obs.doc.find('Get In Car')) == 1)


def focused(obs, label):
    matches = obs.doc.find(label)
    return len(matches) == 1 and label_focused(obs.frame, matches[0])


def pulse_to_focus(nav, obs, start, target, pulses):
    """Move through a proven reversible menu, then prove the target focus."""
    if not focused(obs, start):
        return None
    for _ in range(pulses):
        nav.key('down')
    try:
        return nav.wait(obs.screen, timeout=1.2, stable_frames=1,
                        predicate=lambda current: focused(current, target))
    except RuntimeError as exc:
        if 'Timed out' not in str(exc):
            raise
        return None


def visual_gate(nav, screen, flag, timeout=.65):
    """Wait on calibrated pixels only; fall back to OCR on any uncertainty."""
    if not isinstance(getattr(nav, 'monitor', None), dict) or not getattr(nav, 'recognizer', None):
        return False
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        nav.check()
        frame = nav.measured('capture', lambda: cv2.cvtColor(
            np.asarray(nav.capture.grab(nav.monitor)), cv2.COLOR_BGRA2BGR))
        result = nav.measured('recognition', lambda: nav.recognizer.inspect(frame))
        nav.check()
        if result.get('screen') == screen and result.get(flag) is True:
            nav.probe('observe', frame, screen)
            return True
        nav.pause(.01)
    return False


def wait_after_removal_yes(nav):
    """Observe acknowledgement of one verified Yes; never repeat confirmation."""
    prior = getattr(nav, '_garage_remove_pending', False)
    nav._garage_remove_pending = True
    try:
        return nav.wait('garage_grid', previous='remove_confirmation', timeout=12,
                        predicate=lambda obs: True, stable_frames=2)
    finally:
        nav._garage_remove_pending = prior


def selected_mad_mike(nav, obs):
    """Prove that the focused card is the exact filtered Mazda."""
    box = selected_card(obs.frame)
    card = nav.reader.read(core.crop(obs.frame, box))
    # The selected lime border can obscure most of its title. Require the
    # stable year/class on that card and multiple exact neighboring results
    # from the already verified duplicate filter instead of guessing letters.
    if not card.has('1974', contains=True):
        raise RuntimeError('Selected duplicate is not the 1974 Mad Mike Mazda; no removal sent')
    if not obs.doc.has('MAZDA', (400, 140, 350, 80)):
        raise RuntimeError('Mazda manufacturer header is missing; no removal sent')
    if not obs.doc.has('702', box, contains=True):
        raise RuntimeError('Selected duplicate is not verified S1 702; no removal sent')
    if len(mad_mike_lines(obs.doc)) < 1:
        raise RuntimeError('Mad Mike duplicate-filter evidence is insufficient; no removal sent')
    if obs.doc.has('MAD MIKE', (0, 0, 500, 100), contains=True):
        raise RuntimeError('The active car is Mad Mike; switch cars before cleanup')
    return box


class GarageCleanup:
    def __init__(self, nav, tracker, emit=lambda *args: None):
        self.nav, self.tracker, self.emit = nav, tracker, emit

    def recover_pending_removal(self):
        """Reconcile before any Escape/filter input; unresolved is never a count."""
        from .cleanup_removal_journal import RemovalJournal, identity
        journal = RemovalJournal(self.tracker)
        row = journal.read()
        if row is None:
            return 0
        if row.get('goal_id') != self.tracker.data.get('goal_id'):
            journal.finish(row, 'unresolved_goal_changed')
            return 0
        if row.get('state') == 'acknowledged':
            return journal.commit(row)
        if row.get('state') not in {'prepared', 'submitted'} or row.get('game_identity') != identity(self.nav):
            journal.finish(row, 'unresolved_submission_or_process')
            return 0
        try:
            wait_after_removal_yes(self.nav)
        except RuntimeError as exc:
            if str(exc) != 'Timed out waiting for garage_grid; no input retry':
                raise
            # A still-visible confirmation cannot establish removal. Preserve
            # the unresolved attempt; normal fresh No cancellation may proceed.
            journal.finish(row, 'unresolved_acknowledgement_timeout')
            return 0
        journal.acknowledged(row, self.nav)
        return journal.commit(row)

    def return_to_grid(self):
        """Cancel a saved No/action checkpoint without confirming removal."""
        obs=self.nav.wait({'garage_grid','car_action','remove_confirmation','manufacturers','no_cars'})
        for _ in range(6):
            if obs.screen == 'garage_grid':
                return obs
            previous=obs.screen
            if obs.screen == 'no_cars':
                self.nav.key('enter')
                obs = self.nav.wait('garage_grid', previous='no_cars')
                continue
            # This native destructive dialog intentionally ignores Escape.
            # Activate the freshly verified No row, then Escape the action menu.
            if obs.screen == 'remove_confirmation':
                if (len(obs.doc.find('Yes')) != 1 or len(obs.doc.find('No')) != 1):
                    raise RuntimeError('Saved removal dialog is ambiguous; recovery sent no input')
                self.nav.keyboard_select('remove_confirmation', 'No')
                # Builds differ: No may return to the action sheet or directly
                # to the garage grid. Both are safe, recognizable outcomes.
                target = {'car_action','garage_grid'}
            else:
                self.nav.key('esc')
                target = {'garage_grid'}
            try:
                obs=self.nav.wait(target,previous=previous,timeout=3)
            except RuntimeError as exc:
                if 'Timed out' not in str(exc):
                    raise
                obs=self.nav.wait({'garage_grid','car_action','remove_confirmation','no_cars'})
        raise RuntimeError('Could not safely cancel the saved garage dialog')

    def disable_duplicates(self):
        """Reveal the last copy while retaining S1 and Drift Cars filters."""
        obs = self.nav.wait('garage_grid')
        if not obs.doc.has('Filter', (65, 975, 1700, 65), contains=True):
            raise RuntimeError('Garage Filter control is unavailable; final copy remains untouched')
        self.nav.key('y')
        dialog = self.nav.wait('garage_filter', previous='garage_grid', predicate=lambda o:
            len(o.doc.find('Duplicates', FILTER_REGION)) == 1)
        # The current filter was explicitly established with Duplicates on.
        # Select the exact row once; keyboard_select verifies its live focus.
        self.nav.keyboard_select('garage_filter', 'Duplicates', FILTER_REGION)
        self.nav.wait('garage_filter', predicate=lambda o:
            len(o.doc.find('Duplicates', FILTER_REGION)) == 1)
        self.nav.key('esc')
        result = self.nav.wait({'garage_grid', 'no_cars'}, previous='garage_filter')
        if result.screen == 'no_cars':
            self.nav.key('enter')
            self.nav.wait('garage_grid', previous='no_cars')
        self.tracker.event('garage_duplicates_disabled', {})
        self.emit('status', 'Duplicate filter cleared; removing the final Mad Mike copy')
        update_panel(self.tracker, 'Duplicate filter cleared; removing final Mad Mike')

    def run(self, limit=2000, *, reset_filter_state=False):
        self.return_to_grid()
        self.emit('stage', 'garage_cleanup')
        if reset_filter_state:
            # The caller has just rebuilt the exact filter from Reset, so an
            # earlier cleanup's final-copy state must not leak into this pass.
            self.tracker.data.setdefault('garage_cleanup', {})['duplicates_disabled'] = (
                getattr(self.nav, 'cleanup_duplicates_disabled', False) is True)
        self.tracker.event('garage_cleanup_started', {'filter': FILTER_NAME})
        update_panel(self.tracker, 'Removing all Mad Mike cars; F7 cancels', force=True)
        if getattr(self.nav, 'cleanup_verified_empty', False) is True:
            self.tracker.event('garage_cleanup_completed', {'verified_empty': True})
            update_panel(self.tracker, 'Mad Mike inventory verified: zero', force=True)
            self.emit('status', 'All Mad Mike cars removed; both duplicate filter states are empty')
            return 0
        final_filter = bool((self.tracker.data.get('garage_cleanup') or {}).get('duplicates_disabled'))
        removed = 0
        obs = self.nav.wait('garage_grid')
        try:
            for _ in range(limit):
                if not mad_mike_lines(obs.doc):
                    try:
                        selected_card(obs.frame)
                    except SelectedCardError as exc:
                        if exc.matches == 0:
                            if not final_filter:
                                self.disable_duplicates()
                                final_filter = True
                                obs = self.nav.wait('garage_grid')
                                continue
                            self.tracker.event('garage_cleanup_completed', {'verified_empty': True})
                            update_panel(self.tracker, 'Garage cleanup complete; all Mad Mike cars removed', force=True)
                            self.emit('log', f'Garage cleanup complete: {removed} Mad Mike cars removed in this pass.')
                            return removed
                    if final_filter:
                        from .mad_mike_inventory import remaining_mazda
                        remaining = remaining_mazda(self.nav)
                        if remaining is None:
                            self.tracker.event('garage_cleanup_completed', {'verified_empty': True})
                            update_panel(self.tracker, 'Mad Mike inventory verified: zero', force=True)
                            self.emit('status', 'All Mad Mike cars removed; Mazda absent from the filtered manufacturer index')
                            return removed
                        obs = remaining
                        continue
                    raise RuntimeError('Filtered grid changed without a provably empty result')
                selected_mad_mike(self.nav, obs)
                action = None
                burst_attempted = False
                for attempt in range(3):
                    self.nav.key('enter')
                    if visual_gate(self.nav, 'car_action', 'get_in_selected'):
                        burst_attempted = True
                        if getattr(self.nav, 'fast_navigation', False) is True:
                            ready = spaced_four_to_focus(self.nav,
                                lambda current: focused(current, 'Remove Car From Garage')) is not None
                        else:
                            for _ in range(4):
                                self.nav.key('down')
                            ready = visual_gate(self.nav, 'car_action', 'remove_selected', timeout=.4)
                        if ready:
                            self.nav.key('enter')
                            break
                    try:
                        action = self.nav.wait('car_action', previous='garage_grid', timeout=4,
                                               predicate=complete_action, stable_frames=1)
                        break
                    except RuntimeError as exc:
                        if 'Timed out' not in str(exc) or attempt == 2:
                            raise
                        obs = self.nav.wait('garage_grid')
                        selected_mad_mike(self.nav, obs)
                confirmation = None
                if action is not None:
                    if (len(action.doc.find('Remove Car From Garage')) != 1 or
                            len(action.doc.find('Get In Car')) != 1):
                        raise RuntimeError('Mad Mike action menu is ambiguous; no removal sent')
                    if burst_attempted:
                        ready = None  # Fresh OCR selector, never another pulse group.
                    elif (getattr(self.nav, 'fast_navigation', False) is True and
                          focused(action, 'Get In Car')):
                        ready = spaced_four_to_focus(self.nav,
                            lambda current: focused(current, 'Remove Car From Garage'))
                    else:
                        ready = pulse_to_focus(self.nav, action, 'Get In Car',
                                               'Remove Car From Garage', 4)
                    if ready is not None:
                        self.nav.key('enter')
                    else:
                        self.nav.keyboard_select('car_action', 'Remove Car From Garage')
                if not visual_gate(self.nav, 'remove_confirmation', 'no_selected'):
                    confirmation = self.nav.wait(
                        'remove_confirmation', previous='car_action', timeout=4,
                        predicate=complete_confirmation, stable_frames=1)
                    if (len(confirmation.doc.find('Yes')) != 1 or
                            len(confirmation.doc.find('No')) != 1):
                        raise RuntimeError('Removal confirmation is ambiguous; no confirmation sent')
                for attempt in range(3):
                    if confirmation is None:
                        self.nav.key('down')
                        ready = visual_gate(self.nav, 'remove_confirmation', 'yes_selected', timeout=.4)
                    else:
                        ready = pulse_to_focus(self.nav, confirmation, 'No', 'Yes', 1)
                    from .cleanup_removal_journal import RemovalJournal
                    removal_journal = RemovalJournal(self.tracker)
                    removal_operation = removal_journal.begin(self.nav)
                    if ready:
                        self.nav.key('enter')
                    else:
                        if confirmation is None:
                            confirmation = self.nav.wait('remove_confirmation', predicate=complete_confirmation,
                                                         stable_frames=1)
                        self.nav.keyboard_select('remove_confirmation', 'Yes')
                    removal_journal.submitted(removal_operation)
                    obs = wait_after_removal_yes(self.nav)
                    removal_journal.acknowledged(removal_operation, self.nav)
                    break
                removed += 1
                removal_journal.commit(removal_operation)
                if removed == 1 or removed % 5 == 0:
                    self.emit('status', f'Garage cleanup: {removed} Mad Mike duplicates removed')
                update_panel(self.tracker, f'Garage cleanup running · {self.tracker.data["garage_cleanup"]["removed"]:,} removed')
            raise RuntimeError(f'Garage cleanup safety limit reached ({limit})')
        except Exception as exc:
            self.tracker.event('garage_cleanup_completed', {'error': str(exc)})
            update_panel(self.tracker, f'Garage cleanup retrying · {self.tracker.data.get("garage_cleanup",{}).get("removed",0):,} removed', force=True)
            raise
