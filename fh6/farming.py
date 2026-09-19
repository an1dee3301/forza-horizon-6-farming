"""Mega V6 challenge module. All transitions require visible UI evidence.

The creator's advertised yield is never used as a spendable balance. A farm run
is complete only after returning home and reading a larger actual SP balance.
"""
import json
import re
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

import forza_cycle as core
from .navigation import Navigator, LEFT, Observation, selected_card, navigation_poll_delay
from .ocr import normalize, Document, Text
from .points import read_points, recent_sp, remember_sp
from .profiles import load_profile
from .game_lifecycle import GameCrashed
from .garage import set_favorites
from .telemetry import duration
from .farm_polling import active_countdown_only
from .farm_notices import planned_farm_remaining
from .pause_tabs import pause_tab_steps
from .farm_result_prompt import refine_failed_prompt, result_exit_action, RepeatedResultExit

TOP = (60, 100, 1770, 150)
FOOTER = (60, 965, 1800, 100)
FARM_TIMER = (35, 25, 390, 175)
FARM_FULL_AUDIT_SECONDS = 1.5
FARM_OPTIMIZER_VERSION = 'mega_bank_pulse_v2'
BANK_PULSE_SECONDS = 20.0
BANK_PULSE_HOLD_SECONDS = .06
SETTINGS_PENDING = core.BASE/'runs'/'farm_settings_pending.json'

# These waits already use the base navigator's complete recognition and safety
# checks. Unknown animation frames between them do not need farm HUD OCR too.
CONVERSION_WAIT_SCREENS = frozenset({
    'cars', 'campaign', 'home_tab', 'upgrades', 'mad_mike_mastery', 'car_mastery',
    'collection_grid', 'collection_detail', 'journal', 'discover', 'garage_grid',
    'garage_filter', 'sort_selection', 'recent_jump', 'manufacturers', 'car_action',
    'showroom', 'paints', 'car_select', 'autoshow_prompt', 'purchase_offer_95000',
    'purchase_success',
})


def timer_visible(doc):
    labels = ('Time Remaining', 'Time Left', 'Time Limit', 'Challenge Time')
    return any(doc.has(s, contains=True) for s in labels) and any(
        re.search(r'\b\d{1,2}:\d{2}(?:[.:]\d{2,3})?\b', line.text) for line in doc.lines)


def remaining_seconds(doc):
    labels = doc.find('Time Remaining', (40,35,350,165), contains=True)
    if len(labels) != 1:
        return None
    row = labels[0].center[1]
    values = []
    for line in doc.lines:
        if abs(line.center[1]-row) <= 18 and 40 <= line.center[0] <= 400:
            values.extend(re.findall(r'\b(\d{1,2}):(\d{2})(?:[.:](\d{2,3}))?\b', line.text))
    if len(values) != 1:
        return None
    minutes, seconds, fraction = values[0]
    if int(seconds) >= 60:
        return None
    return 60*int(minutes)+int(seconds)+(float('0.'+fraction) if fraction else 0)


class TimerWatch:
    def __init__(self, clock=time.monotonic, timeout=60):
        self.clock, self.timeout = clock, timeout
        self.value, self.changed = None, clock()

    def observe(self, value):
        if value is None:
            return
        if value != self.value:
            self.value, self.changed = value, self.clock()
        elif self.clock()-self.changed >= self.timeout:
            raise GameCrashed('The focused challenge timer froze for 60 seconds; restarting the game')


def result_visible(doc):
    if (doc.has('Try Again', (40,150,950,200), contains=True) and
            doc.has('Retry', FOOTER, contains=True) and doc.has('Quit', FOOTER, contains=True)):
        return True
    return (doc.has('Continue', FOOTER, contains=True) or doc.has('Retry', FOOTER, contains=True)) and any(
        doc.has(s, contains=True) for s in ('Challenge Complete', 'Challenge Completed', 'Challenge Failed', 'Success', 'Completed', 'Failed'))


def event_paused(doc):
    if doc.has('Restart Event', contains=True) and doc.has('Quit Event', contains=True):
        return True
    # Both labels wrap onto two OCR lines on the actual event pause screen.
    left, right = (230,260,320,600), (1390,260,320,600)
    return (doc.has('Restart', left, contains=True) and doc.has('Event', left, contains=True)
            and doc.has('Quit', right, contains=True) and doc.has('Event', right, contains=True))


def farm_car(doc, profile):
    # Do not let the model of a neighbouring duplicate satisfy this check.
    return (doc.has(profile.manufacturer, contains=True) and doc.has(profile.year, contains=True)
            and doc.has('22B', contains=True) and doc.has('IMPREZA', contains=True))


def owned_home_entry(doc):
    return (not timer_visible(doc) and doc.has('ANNA', FOOTER, contains=True)
            and doc.has('Enter House', (60, 480, 620, 150), contains=True))


def refine_home_prompt(reader, frame, doc):
    # White HUD lettering overlaps textured scenery. Read only the known
    # entrance and ANNA regions; preserve every other region's evidence.
    for x, y, w, h in ((60, 375, 470, 215), (90, 995, 225, 60)):
        crop = frame[y:y+h, x:x+w]
        mask = cv2.inRange(crop, (215, 215, 215), (255, 255, 255))
        local = reader.read(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR))
        retained = [line for line in doc.lines if not
                    (x <= line.center[0] < x+w and y <= line.center[1] < y+h)]
        retained.extend(Text(line.text, (line.box[0]+x, line.box[1]+y, *line.box[2:]))
                        for line in local.lines)
        doc = Document(retained)
    return doc


def farm_tree_owned(frame):
    nodes = [(376,242),(492,242),(724,242), (492,358),(608,358),(724,358),
             (376,474),(492,474),(608,474),(724,474), (376,590),(492,590),(608,590),(724,590)]
    return all(core.node_state(frame,x,y)['state'] == 'owned' for x,y in nodes)


def difficulty_value(doc, label):
    """Return one normalized value from the exact difficulty row."""
    rows = doc.find(label)
    if len(rows) != 1:
        return None
    row = rows[0]
    values = [normalize(line.text) for line in doc.lines
              if line.center[0] > row.center[0]+250
              and abs(line.center[1]-row.center[1]) < 22
              and normalize(line.text) not in {'o'}]
    return values[0] if len(values) == 1 else None


def settings_save_dialog(doc):
    return (doc.has('Unsaved Changes', contains=True)
            and len(doc.find('Save and Continue', contains=True)) == 1
            and len(doc.find('Discard and Continue', contains=True)) == 1
            and len(doc.find('Cancel')) == 1)


def pending_settings_save(nav):
    from .analytics import read
    data = read(SETTINGS_PENDING)
    setup = getattr(nav, 'setup_checks', None)
    if not isinstance(data, dict) or setup is None or data.get('status') != 'pending':
        return False
    try:
        # The worker is constructed with a fresh timestamp and restores the
        # mission id only after the startup/sync gate.  A settings-save dialog
        # can be the very screen that gate observes, so bind recovery to the
        # persisted active goal instead of the temporary worker id.  Normalize
        # identity containers because JSON turns tuples into lists.
        goal = read(core.BASE/'runs'/'goal.json')
        safe_goal = (isinstance(goal, dict)
                     and goal.get('id') == data.get('goal_id')
                     and goal.get('phase') == 'farm'
                     and goal.get('batch') is None
                     and goal.get('reservation') is None)
        saved_identity = tuple(data.get('game_identity') or ())
        live_identity = tuple(setup.identity() or ())
        return safe_goal and bool(saved_identity) and saved_identity == live_identity
    except (OSError, TypeError, ValueError):
        return False


def remember_settings_save(nav):
    from .analytics import save
    setup = getattr(nav, 'setup_checks', None)
    if setup is None:
        raise RuntimeError('Farm settings identity unavailable; no setting changed')
    save(SETTINGS_PENDING, dict(goal_id=setup.run_id, status='pending',
        game_identity=setup.identity(), setting='Shifting', value='Manual',
        optimizer_version=FARM_OPTIMIZER_VERSION))


def clear_settings_save():
    try:
        SETTINGS_PENDING.unlink()
    except FileNotFoundError:
        pass


class FarmNavigator(Navigator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefer_keyboard = True
        self.verified_farm_profile = None
        self.setup_checks = None

    def observe(self):
        if pending_settings_save(self):
            self._settings_save_expected = True
        if getattr(self, '_farm_countdown_fast', False):
            now = time.monotonic()
            if now < getattr(self, '_farm_full_audit_due', 0):
                quick = self._observe_active_countdown()
                if quick is not None:
                    return quick
            self._farm_full_audit_due = now + FARM_FULL_AUDIT_SECONDS
        obs = super().observe()
        if getattr(self,'car_entry_active',False):
            # Car-entry proof uses the normal frame/menu read. Farm timer,
            # result and free-roam refinements cannot help this transition.
            return obs
        if obs.screen == 'unknown' and getattr(self, '_conversion_wait_active', False):
            return obs
        if obs.screen == 'unknown' or timer_visible(obs.doc):
            # Moving walls/scenery can overwhelm full-frame OCR. The timer is
            # fixed in this HUD region, independently of the camera and car.
            obs.doc = self.reader.refine_region(obs.frame, obs.doc, (40,35,350,165))
        if obs.screen == 'unknown' and not active_countdown_only(obs.doc,remaining_seconds(obs.doc)):
            obs.doc = self.reader.refine_region(obs.frame, obs.doc, (45,970,600,80))
            if any(obs.doc.has(s, FOOTER, contains=True) for s in ('Retry', 'Quit', 'Continue', 'Exit')):
                obs.doc = self.reader.refine_region(obs.frame, obs.doc, (45,155,1100,185))
            if (not timer_visible(obs.doc) and not result_visible(obs.doc) and
                    any(obs.doc.has(s, FOOTER, contains=True) for s in ('Retry', 'Quit', 'Continue', 'Exit'))):
                obs.doc = refine_failed_prompt(self.reader, obs.frame, obs.doc)
            if not timer_visible(obs.doc) and not result_visible(obs.doc):
                obs.doc = refine_home_prompt(self.reader, obs.frame, obs.doc)
        return obs

    def _observe_active_countdown(self):
        """Read only the native timer between periodic complete safety scans.

        The old farm loop performed full-frame OCR and then a second timer OCR
        roughly twice a second for the entire challenge.  This path keeps fresh
        capture, visual recognition, process/focus/F7 and external sync checks
        on every sample.  Any missing timer or visual menu match immediately
        falls back to the complete scan; a complete scan is also forced every
        1.5 seconds for overlays that leave the timer visible underneath.
        """
        self.check()
        frame = self.measured('capture', lambda:
            cv2.cvtColor(np.asarray(self.capture.grab(self.monitor)), cv2.COLOR_BGRA2BGR))
        captured = time.monotonic()
        if frame.shape[:2] != (1080, 1920):
            raise RuntimeError('Set the game and selected monitor to 1920 × 1080.')
        result = self.measured('recognition', lambda: self.recognizer.inspect(frame))
        if result.get('screen') not in {None, 'unknown'}:
            return None
        x, y, w, h = FARM_TIMER
        local = self.measured('farm_timer_ocr', lambda: self.reader.read(frame[y:y+h, x:x+w]))
        doc = Document([Text(line.text, (line.box[0]+x, line.box[1]+y, *line.box[2:]))
                        for line in local.lines])
        if not active_countdown_only(doc, remaining_seconds(doc)):
            return None
        obs = Observation(frame, result, doc, 'unknown', captured)
        self.last = obs
        obs.focus_generation = self.focus_generation
        self.probe('observe', frame, 'farm_countdown')
        if self.sync_guard:
            self.sync_guard.inspect(doc)
        self.check()
        return obs

    def wait(self, screens, previous=(), predicate=None, timeout=None, stable_frames=2):
        targets = {screens} if isinstance(screens, str) else set(screens)
        prior = getattr(self, '_conversion_wait_active', False)
        self._conversion_wait_active = bool(targets) and targets <= CONVERSION_WAIT_SCREENS
        try:
            return super().wait(targets, previous=previous, predicate=predicate,
                                timeout=timeout, stable_frames=stable_frames)
        finally:
            self._conversion_wait_active = prior

    def until(self, predicate, description, timeout=None):
        # A challenge/menu predicate nested inside a conversion wait needs the
        # complete farm refinements again; never inherit the outer shortcut.
        prior = getattr(self, '_conversion_wait_active', False)
        self._conversion_wait_active = False
        try:
            return self._until(predicate, description, timeout)
        finally:
            self._conversion_wait_active = prior

    def _until(self, predicate, description, timeout=None):
        end, stable = time.monotonic() + (timeout or self.timeout), 0
        notification, notification_frames, acknowledged = None, 0, None
        while time.monotonic() < end:
            observation_started = time.monotonic()
            obs = self.observe()
            stable = stable + 1 if predicate(obs) else 0
            if stable >= 2:
                return obs
            if stable == 0 and obs.screen in {'series_update', 'festival_playlist', 'new_car_collected'}:
                notification_frames = notification_frames + 1 if notification == obs.screen else 1
                notification = obs.screen
                if notification_frames >= 2 and acknowledged != obs.screen:
                    self.emit('log', f'Verified {obs.screen} notification; acknowledging once.')
                    self.key('esc' if obs.screen == 'festival_playlist' else 'enter')
                    acknowledged = obs.screen
            else:
                notification, notification_frames = None, 0
            self.pause(navigation_poll_delay(time.monotonic()-observation_started)
                       if self.fast_navigation else .2)
        raise RuntimeError(f'Timed out verifying {description}; no input retry')

    def select(self, label, region=None, contains=False):
        # This observation only routes to the existing selector. That selector
        # independently verifies stable screen/target/focus before sending input.
        # Do not pay for another two-frame preflight on already visible menus.
        obs = self.observe() if self.fast_navigation else None
        if (obs is None or obs.screen not in {'pause_menu', 'eventlab', 'challenge_search',
                'settings', 'campaign', 'cars', 'upgrades'} or
                len(obs.doc.find(label, region, contains)) != 1):
            obs = self.until(lambda o: len(o.doc.find(label, region, contains)) == 1, label)
        self.click_label(obs.screen, label, region, contains)

    @staticmethod
    def is_home(obs):
        return obs.doc.has('BUY & SELL', TOP) and obs.doc.has('CUSTOMIZABLE GARAGE', TOP)

    @staticmethod
    def is_roam(obs):
        return obs.doc.has('ANNA', FOOTER, contains=True) and not timer_visible(obs.doc)

    @staticmethod
    def is_pause(obs):
        return obs.doc.has('MY HORIZON', TOP) and obs.doc.has('CREATIVE HUB', TOP)

    def open_pause_menu(self, label='free-roam pause menu'):
        """Open Pause, retrying one dropped reversible Esc without a 30s stall."""
        self.key('esc')
        if self.fast_navigation:
            try:
                return self.until(self.is_pause,label,timeout=1.5)
            except RuntimeError as exc:
                current=getattr(self,'last',None)
                if (not str(exc).startswith('Timed out ') or current is None
                        or not (self.is_roam(current) or owned_home_entry(current.doc))):
                    raise
                self.emit('log','Free-roam Esc was dropped; retrying the reversible pause pulse immediately.')
                self.key('esc')
        return self.until(self.is_pause,label)

    def pause_tab(self, label):
        def target_selected(obs):
            if not self.is_pause(obs):
                return False
            matches = obs.doc.find(label, TOP)
            if len(matches) != 1:
                return False
            x, y, w, h = matches[0].box
            region = core.crop(obs.frame, (x-7, y-4, w+14, h+8))
            return np.mean(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) < 65) > .55

        reverse_tried = False
        for _ in range(7):
            obs = self.until(self.is_pause, 'free-roam menu tabs')
            obs.doc.unique(label, TOP)
            if target_selected(obs):
                # The generic pause-menu predicate only proves tab captions
                # exist. Confirm the selected destination in a second fresh
                # observation before the caller can act on that tab's tiles.
                self.pause(.06 if self.fast_navigation else .2)
                if target_selected(self.observe()):
                    self.emit('log', f'Verified pause tab: {label}')
                    return
                # A fading/missing caption is not a reason to send another
                # tab key. Reacquire the menu within the existing bounded loop.
                continue
            plan = pause_tab_steps(obs, label) if self.fast_navigation and not reverse_tried else None
            if plan is not None and plan[1] > 0:
                direction, steps = plan
                # With six tabs, a strictly shorter reverse route is at most
                # two keys. If it fails to reach the target, fall back to the
                # existing forward route from fresh observations.
                reverse_tried = direction == 'pgup'
                self.emit('log', f'Pause tabs: {steps} {direction} from the complete verified tab row.')
                for _ in range(steps):
                    self.key(direction)
                    self.pause(.12)
            else:
                self.key('pgdn')
                self.pause(.4)
        raise RuntimeError(f'The {label} pause tab was not reached')

    def ensure_home(self):
        self._farm_direct_pause_tree=False
        self._farm_selected_from_pause=False
        self._farm_pause_mastery=False
        self._farm_pause_balance=False
        self._farm_mastery_origin_unknown=False
        for _ in range(10):
            obs = self.observe()
            if obs.screen == 'no_cars':
                # My Cars can preserve an empty filter across a stopped cleanup.
                # This native modal has one harmless acknowledgement and must be
                # cleared before the normal garage -> Home recovery can proceed.
                self.wait('no_cars', predicate=lambda o:
                    len(o.doc.find('No Cars Available')) == 1 and
                    len(o.doc.find('filter settings', contains=True)) == 1 and
                    len(o.doc.find('Enter', (65,975,240,70), contains=True)) == 1)
                self.emit('log', 'Acknowledging the verified empty My Cars filter before Home recovery.')
                self.key('enter')
                # FH6 returns this acknowledgement to Filter Selection, not
                # the empty grid. Reset the now-visible filter explicitly so
                # the garage has a valid destination for Home recovery.
                self.wait('garage_filter', previous='no_cars')
                from .garage import set_favorites
                set_favorites(self, False)
                continue
            if obs.screen in {'series_update', 'festival_playlist'}:
                previous = obs.screen
                self.wait(previous)
                self.key('esc' if previous == 'festival_playlist' else 'enter')
                self.until(lambda o: o.screen != previous, 'closing seasonal notification')
                continue
            if settings_save_dialog(getattr(obs, 'doc', Document([]))) and pending_settings_save(self):
                self._settings_save_expected = True
                self.emit('log', 'Recovered the exact pending Manual-shifting save dialog after restart.')
                self.click_label(obs.screen, 'Save and Continue', contains=True)
                self.until(lambda o: o.screen == 'settings' and o.doc.has('Difficulty'),
                           'settings after recovered save')
                clear_settings_save()
                self._settings_save_expected = False
                continue
            if obs.screen == 'new_car_collected':
                self.wait('new_car_collected')
                self.emit('log', 'Verified New Car Collected notification; acknowledging once before returning home.')
                self.key('enter')
                self.until(lambda o: o.screen != 'new_car_collected', 'closing new-car notification')
                continue
            if obs.screen == 'car_action':
                # A failed Get In Car focus check can leave this dialog open.
                # Cancel it rather than activating a stale car selection. A
                # predicate forces two fresh frames instead of a ready-token
                # handoff; the normal garage route then rechecks car identity.
                self.wait('car_action', predicate=lambda o:
                    len(o.doc.find('Select An Action')) == 1 and
                    len(o.doc.find('Get In Car')) == 1 and
                    len(o.doc.find('Cancel', FOOTER)) == 1)
                self.emit('log', 'Canceling the verified car-action dialog before rechecking the farm car.')
                self.key('esc')
                self.wait('garage_grid', previous='car_action')
                continue
            if obs.screen == 'settings':
                self.key('esc')
                self.pause(.5)
                continue
            if obs.screen in {'manufacturers', 'sort_selection', 'recent_jump', 'garage_filter'}:
                previous = obs.screen
                self.key('esc')
                self.until(lambda o: o.screen not in {previous, 'unknown'}, 'closing car navigation dialog')
                self.pause(.6)
                continue
            if self.is_home(obs):
                return
            if owned_home_entry(obs.doc):
                # Challenge exit can leave the car at its owned home entrance.
                # Verify the prompt twice before Enter; no travel menu is needed.
                self.until(lambda o: owned_home_entry(o.doc), 'owned home entrance')
                self.key('enter')
                self.until(self.is_home, 'entering owned home', timeout=max(60, self.timeout))
                return
            if obs.screen in {'mad_mike_mastery', 'car_mastery', 'upgrades', 'collection_grid',
                              'journal', 'discover', 'cars', 'campaign', 'garage_grid', 'showroom'} \
                    and not self.is_pause(obs):
                previous = obs.screen
                self.key('esc')
                same_destination, destination_screen = 0, None
                def back_destination(o):
                    nonlocal same_destination, destination_screen
                    good = o.screen not in {previous, 'unknown'} or self.is_home(o) or self.is_roam(o)
                    same_destination = same_destination + 1 if good and o.screen == destination_screen else int(good)
                    destination_screen = o.screen
                    return good
                destination = self.until(back_destination, 'back to home')
                # Farm setup only: Esc is the next possible input on these
                # reversible menus. It does not depend on a settled focus
                # border. The loop obtains another full observation before
                # input; all sync/focus/danger/F7 checks still run normally.
                # Mixed/unknown destinations retain the original padding.
                ready_back = (self.fast_navigation and
                    getattr(self, '_farm_setup_home_return', False) and
                    same_destination >= 2 and
                    destination.screen in {'upgrades', 'cars', 'campaign', 'home_tab'})
                if not ready_back:
                    self.pause(.6)
                continue
            if self.fast_navigation and self.is_pause(obs):
                # A paused car may already be at the owned-property entrance.
                # Expose and prove the native HUD before opening travel menus.
                from .house_entry import try_owned_house_from_pause
                if try_owned_house_from_pause(self):
                    return
            elif self.is_roam(obs):
                if self.fast_navigation:
                    # ANNA can appear before the native ownership interaction.
                    # Give that HUD a brief fresh-frame grace before Escape.
                    from .house_entry import try_owned_house_from_roam
                    if try_owned_house_from_roam(self):
                        return
                self.open_pause_menu()
            else:
                self.until(self.is_pause, 'free-roam pause menu')
            self.pause_tab('MY HORIZON')
            # The large Return/Home title wraps onto separate OCR lines.
            # Its subtitle stays on one line inside the same verified tile.
            self.select('Fast Travel Home', (520,250,880,310))
            confirmation = self.until(lambda o: o.doc.has('Yes') and any(o.doc.has(s, contains=True)
                for s in ('Travel', 'Return Home', 'Home')), 'return-home confirmation')
            self.click_label(confirmation.screen, 'Yes')
            self.until(self.is_home, 'arrival at home', timeout=max(60, self.timeout))
            return
        raise RuntimeError('Home was not reached within ten verified transitions')

    def return_collection(self):
        obs = self.observe()
        if obs.screen == 'manufacturers':
            self.key('esc')
            self.wait('collection_grid', previous='manufacturers')
            return
        if obs.screen == 'collection_grid':
            return
        self.ensure_home()
        self.collection()

    def available_sp(self, *, allow_menu=True):
        if allow_menu:
            from .farm_balance import recent_menu_sp, read_tile_sp
            menu_proof=recent_menu_sp(self)
            if menu_proof is not None:
                return menu_proof.points
        proof = recent_sp(self)
        if proof is not None:
            self.emit('log', 'Reusing the just-verified SP balance before any new input or capture.')
            return proof.points
        self._verified_sp = None
        obs = self.observe()
        if allow_menu and obs.screen in {'pause_menu','campaign','cars','home_tab'}:
            points=read_tile_sp(self)
            if points is None:
                if obs.screen == 'pause_menu':
                    self.pause_tab('CARS')
                    points=read_tile_sp(self)
            if points is not None:
                return points
        if obs.screen=='pause_menu' and getattr(self,'_farm_selected_from_pause',False) is True:
            from .pause_mastery import open_pause_mastery
            self.pause_tab('CARS')
            if open_pause_mastery(self):
                obs=self.wait({'mad_mike_mastery','car_mastery'},previous='pause_menu')
                self._farm_direct_pause_tree=True
            self._farm_selected_from_pause=False
        if obs.screen not in {'mad_mike_mastery', 'car_mastery'}:
            self.ensure_home()
            self.home_tab('cars')
            self.click_label('cars', 'Upgrades & Tuning', LEFT)
            self.wait('upgrades', previous='cars')
            self.click_label('upgrades', 'Car Mastery', LEFT)
            obs = self.wait({'mad_mike_mastery', 'car_mastery'}, previous='upgrades')
        before = read_points(self.reader, obs.frame)
        self.pause(.25)
        again = self.wait({'mad_mike_mastery', 'car_mastery'})
        after = read_points(self.reader, again.frame)
        if before != after:
            raise RuntimeError('SP changed while reading it; stopped before making a spending plan')
        self.check()
        remember_sp(self, after)
        self.emit('log', f'Verified available SP: {after}')
        return after

    def resume_mastery(self):
        """Reopen the current Mazda's tree after a stopped run left its menu."""
        obs = self.observe()
        if obs.screen == 'mad_mike_mastery':
            return
        header = (100, 35, 1200, 155)
        if not obs.doc.has('123 Mad Mike 808', header, contains=True):
            raise RuntimeError('Cannot resume mastery: the current car is not the saved Mad Mike Mazda')
        self.emit('log', 'Saved mastery is outside its tree; returning home with the current Mazda before reopening mastery.')
        self.ensure_home()
        home = self.until(self.is_home, 'current Mazda at home')
        if not home.doc.has('123 Mad Mike 808', header, contains=True):
            raise RuntimeError('The current car changed while returning home; mastery was not resumed')
        self.open_mastery()

    def select_farm_car(self, profile):
        if self.fast_navigation:
            from .pause_farm import select_from_pause
            if select_from_pause(self,profile):
                return
        self.ensure_home()
        obs = self.observe()
        current = self.reader.read(core.crop(obs.frame, (150, 35, 850, 50)))
        if farm_car(current, profile):
            self.emit('log', 'The verified 1998 Subaru 22B is already the current car')
            return
        self.my_cars()
        set_favorites(self, True)
        self.wait_farm_car_card(profile)
        self.key('enter')
        obs = self.wait({'car_action', 'showroom', 'cars'}, previous='garage_grid')
        if obs.screen == 'car_action':
            self.click_label('car_action', 'Get In Car')
            self.wait({'showroom', 'cars'}, previous='car_action')
        self.ensure_home()

    def wait_farm_car_card(self, profile):
        # The long model name scrolls inside its card. Filtering may finish
        # while "IMPREZA" or "22B" is clipped; wait without changing selection
        # until the same card shows its full identifying text twice.
        previous_box = None

        def identified(obs):
            nonlocal previous_box
            if obs.screen != 'garage_grid':
                previous_box = None
                return False
            box = selected_card(obs.frame)
            stable = previous_box is not None and all(abs(a-b) <= 3 for a, b in zip(box, previous_box))
            previous_box = box
            card = self.reader.read(core.crop(obs.frame, box))
            return stable and farm_car(card, profile)

        return self.until(identified, 'the selected Favorite 1998 Subaru Impreza 22B name')

    def verify_farm_settings(self):
        self.home_tab('campaign')
        self.click_label('campaign', 'Settings', LEFT)
        self.select('Difficulty')
        obs = self.until(lambda o: o.doc.has('Braking') and o.doc.has('Steering'), 'driving-assist settings')
        for label, allowed in [('Braking', {'anti lock on', 'anti lock off', 'abs on', 'abs off'}),
                               ('Steering', {'standard', 'simulation'})]:
            row = obs.doc.unique(label)
            y = row.center[1]
            values = [normalize(l.text) for l in obs.doc.lines if l.center[0] > row.center[0]+100
                      and abs(l.center[1]-y) < 22]
            if not any(v in allowed for v in values):
                raise RuntimeError(f'Mega V6 needs automatic {label.lower()} off. Check Settings → Difficulty.')
        shifting = difficulty_value(obs.doc, 'Shifting')
        changed_shifting = False
        if shifting == 'automatic':
            # Current Mega V6 testing reports materially faster banking in
            # first gear. The exact Shifting row supplies Y; the fixed native
            # right arrow supplies X. Readback must prove Manual twice.
            import pyautogui
            row = obs.doc.unique('Shifting')
            self.check()
            self.emit('log', 'Mega V6 optimizer: changing Shifting from Automatic to Manual for first-gear farming.')
            self.probe('input', 'difficulty Shifting right')
            pyautogui.moveTo(self.monitor['left']+1413,
                             self.monitor['top']+row.center[1], duration=.04)
            try:
                pyautogui.mouseDown()
                self.pause(.06)
            finally:
                pyautogui.mouseUp()
            pyautogui.moveTo(self.monitor['left']+1810, self.monitor['top']+970)
            # The first pointer activation can focus the row without cycling
            # its value. Prove that exact focus, then send one reversible Right
            # pulse. This matches the live settings behavior.
            from .navigation import label_focused
            focused = self.until(lambda o: o.screen == 'settings' and
                len(o.doc.find('Shifting')) == 1 and
                difficulty_value(o.doc, 'Shifting') == 'automatic' and
                label_focused(o.frame, o.doc.find('Shifting')[0]),
                'focused Automatic shifting row')
            if difficulty_value(focused.doc, 'Shifting') == 'automatic':
                remember_settings_save(self)
                self.key('right')
            obs = self.until(lambda o: o.screen == 'settings' and
                             difficulty_value(o.doc, 'Shifting') == 'manual',
                             'Manual shifting readback')
            shifting = difficulty_value(obs.doc, 'Shifting')
            changed_shifting = shifting == 'manual'
        if shifting != 'manual':
            raise RuntimeError('Mega V6 optimizer requires Settings → Difficulty → Shifting = Manual; no farm launched.')
        if changed_shifting:
            self._settings_save_expected = True
            try:
                self.key('esc')
                dialog = self.until(lambda o: settings_save_dialog(o.doc),
                    'verified settings save dialog')
                self.click_label(dialog.screen, 'Save and Continue', contains=True)
                self.until(lambda o: o.screen == 'settings' and o.doc.has('Difficulty'),
                           'settings after saving Manual shifting')
                clear_settings_save()
            finally:
                self._settings_save_expected = False
        else:
            self.key('esc')
        self.select('HUD & Gameplay', LEFT)
        # Move only through the verified settings list. Wheel scrolling skips
        # inconsistently here; Down changes focus without changing any setting.
        for _ in range(80):
            obs = self.observe()
            if obs.doc.has('Skills'):
                break
            if not obs.doc.has('HUD & Gameplay', contains=True):
                raise RuntimeError('HUD settings were not recognized')
            self.key('down')
            self.pause(.3)
        else:
            raise RuntimeError('The Skills HUD setting was not found')
        row = obs.doc.unique('Skills')
        if not any(normalize(l.text) == 'off' and l.center[0] > row.center[0]+100
                   and abs(l.center[1]-row.center[1]) < 22 for l in obs.doc.lines):
            raise RuntimeError('Mega V6 needs Settings → HUD and Gameplay → Skills set to Off')
        self.key('esc')
        self.until(lambda o: o.doc.has('Difficulty'), 'settings menu')
        from .video import verify_frame_rate
        verify_frame_rate(self)
        self.key('esc')
        self.until(self.is_home, 'home after settings')

    def ensure_farm_settings(self, profile):
        if self.setup_checks is not None:
            result = self.setup_checks.ensure(profile, self.verify_farm_settings, self.verify_farm_video)
            self.emit('log', {'cached':'Farm settings already verified for this mission; skipping Settings.',
                'video':'Frame-rate check complete; reusing this mission’s assist and Skills HUD verification.',
                'full':'Assist, difficulty, Skills HUD and frame rate verified once for this mission.'}[result])
        elif self.verified_farm_profile != profile:
            self.verify_farm_settings()
            self.verified_farm_profile = profile

    def verify_farm_video(self):
        self.home_tab('campaign')
        self.click_label('campaign', 'Settings', LEFT)
        self.until(lambda o: o.doc.has('Difficulty'), 'settings menu')
        from .video import verify_frame_rate
        verify_frame_rate(self)
        self.key('esc')
        self.until(self.is_home, 'home after frame-rate check')

    def invalidate_farm_video(self):
        if self.setup_checks is not None:
            self.setup_checks.invalidate_video()
        else:
            self.verified_farm_profile = None

    def invalidate_farm_settings(self):
        if self.setup_checks is not None:
            self.setup_checks.invalidate_full()
        else:
            self.verified_farm_profile = None

    def search_challenge(self, profile):
        obs = self.observe()
        if obs.screen == 'challenge_browser':
            self.wait('challenge_browser')
            self.key('backspace')
            obs = self.wait('challenge_search', previous='challenge_browser')
        from .farm_search import reuse_search
        if obs.screen == 'challenge_search' and reuse_search(self,profile.share_code):
            return
        if obs.screen not in {'share_code', 'challenge_search'}:
            if obs.screen != 'eventlab' and not self.is_pause(obs):
                if not self.is_roam(obs):
                    self.ensure_home()
                    self.home_tab('campaign')
                    self.click_label('campaign', 'Drive', LEFT)
                    self.until(self.is_roam, 'free roam', timeout=max(60, self.timeout))
                self.open_pause_menu('pause menu')
            if obs.screen != 'eventlab':
                self.pause_tab('CREATIVE HUB')
                self.select('Create & Browse Events', contains=True)
            self.select('Challenges', contains=True)
            self.until(lambda o: o.doc.has('Search', FOOTER, contains=True), 'challenge browser')
            self.key('backspace')
            obs=self.wait('challenge_search',previous='challenge_browser')
            if reuse_search(self,profile.share_code):
                return
        if obs.screen != 'share_code':
            self.select('Share Code', contains=True)
        # After Enter, the search form can remain visible while the editor
        # opens. Wait for two stable editor frames before typing any digits.
        self.wait('share_code', previous='challenge_search')
        # This game editor can retain a digit after Ctrl+A during a resumed
        # entry. Clear both sides of the caret in this verified numeric editor.
        # Backspace/Delete cannot submit a search or a transaction here.
        from .share_editor import verify_empty_share_editor
        if self.fast_navigation and verify_empty_share_editor(self):
            self.emit('log','Two fresh blank share-code editor frames verified; skipped 32 clearing keys.')
        else:
            self.wait('share_code', previous='challenge_search')
            for _ in range(16):
                self.key('backspace', hold_seconds=.03 if self.fast_navigation else .06)
                self.key('delete', hold_seconds=.03 if self.fast_navigation else .06)
        # Only digits are accepted by the profile; never paste arbitrary commands.
        for digit in profile.share_code:
            self.key(digit, hold_seconds=.03 if self.fast_navigation else .06)
        from .share_editor import exact_share_code
        self.until(lambda o: exact_share_code(o, profile.share_code), 'exact entered share code')
        self.key('enter')
        retained = self.wait('challenge_search', previous='share_code',
                  predicate=lambda o: o.doc.has(profile.share_code, contains=True))
        # Windows OCR frequently confuses one retained digit on the next run.
        # This frame has just passed exact editor and exact search-form OCR, so
        # it can safely seed the profile-bound interior-pixel proof used later.
        from .farm_search import remember_retained_code
        if remember_retained_code(retained, profile.share_code):
            self.emit('log', 'Saved exact retained-code pixels for faster repeat farm search.')
        self.select('Confirm')
        self.wait_challenge_result()

    def wait_challenge_result(self):
        self.until(lambda o: o.doc.has('Search Results', contains=True) and
                   o.doc.has('Select', FOOTER, contains=True) and
                   not o.doc.has('No results', contains=True), 'challenge search result')

    def dismiss_challenge_rating(self):
        from .navigation import label_focused
        region=(625,650,670,65)
        finished=lambda o:self.is_roam(o) or self.is_pause(o) or self.is_home(o)
        def cancel_focused(o):
            matches=o.doc.find('Cancel',region)
            return o.screen=='challenge_rating' and len(matches)==1 and label_focused(o.frame,matches[0])
        self.click_label('challenge_rating','Cancel',region)
        # A click can focus Cancel after the generic click handler's quick check.
        # Wait for two focused frames, then Enter only on that exact dialog row.
        obs=self.until(lambda o:finished(o) or cancel_focused(o),'rating dismissal or focused Cancel',timeout=60)
        if not finished(obs):
            self.key('enter')
            self.until(finished,'leaving challenge rating',timeout=60)


class Challenge:
    def __init__(self, nav, path=core.BASE/'runs'/'challenge.json', profile=None, emit=lambda *a: None):
        self.nav, self.path = nav, Path(path)
        self.profile, self.emit = profile or load_profile(), emit
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        if profile is None and self.data.get('phase') not in {None,'complete'} and self.data.get('share_code')=='169055890':
            self.profile=replace(self.profile,name='Mini Farm V2',share_code='169055890',duration_seconds=300,
                                 source='User-provided Mini V2 share code; live trial')

    def save(self, **changes):
        self.data.update(changes)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, indent=2), encoding='utf-8')
        tmp.replace(self.path)

    def _press_throttle(self, key_down):
        proof = self._throttle_proof
        pressed = proof.press(key_down)
        if pressed and not self._farm_active_emitted:
            self._farm_active_emitted = True
            self.emit('farm_active', dict(id=self.data.get('id'),
                proof='two_fresh_native_countdown_frames', guard_current=True,
                **proof.last_accepted))
        return pressed

    def _reacquire_throttle(self, description, timeout, *, allow_pause=False):
        import pyautogui
        nav, proof = self.nav, self._throttle_proof
        proof.reset()
        def recognized(obs):
            proof.observe(obs)
            return timer_visible(obs.doc) or result_visible(obs.doc) or (allow_pause and event_paused(obs.doc))
        nav.until(recognized, description, timeout=timeout)
        return self._press_throttle(pyautogui.keyDown)

    def _refresh_anti_afk(self, pyautogui):
        """Refresh both accelerator and steering before Mega's AFK cutoff."""
        nav, p, proof = self.nav, self.profile, self._throttle_proof
        nav.check()
        pyautogui.keyUp(p.accelerator)
        if proof.changed():
            proof.reset()
            return False
        try:
            pyautogui.keyDown(p.movement_key)
            nav.pause(p.movement_seconds)
        finally:
            pyautogui.keyUp(p.movement_key)
        proof.reset()
        return self._reacquire_throttle(
            'challenge timer after accelerator refresh', 10)

    def _pulse_bank(self, pyautogui, index):
        """Tiny alternating steering input while preserving continuous throttle.

        Mega V6 banks repeated skill-chain segments. Community observations
        report that movement between those segments prevents weak/empty banks.
        The pulse is authorized by the same two-frame countdown, focus, sync,
        process-identity and F7 proof used for throttle acquisition.
        """
        nav, proof = self.nav, self._throttle_proof
        key = 'a' if index % 2 == 0 else 'd'
        def pulse():
            pyautogui.keyDown(key)
            try:
                nav.pause(BANK_PULSE_HOLD_SECONDS)
            finally:
                pyautogui.keyUp(key)
        return proof.run_input(pulse)

    def _reverse_stationary_car(self, pyautogui, seconds=5.0):
        """Back away from a verified obstruction, then re-prove forward drive.

        The reverse key is sent only from the same fresh countdown, focus,
        sync and process proof used for throttle. ``nav.pause`` keeps checking
        F7 and game focus throughout the five-second recovery.
        """
        nav, p, proof = self.nav, self.profile, self._throttle_proof
        nav.check()
        pyautogui.keyUp(p.accelerator)

        def reverse():
            pyautogui.keyDown('s')
            try:
                nav.pause(seconds)
            finally:
                pyautogui.keyUp('s')

        if not proof.run_input(reverse):
            pyautogui.keyUp('s')
            proof.reset()
            return False
        proof.reset()
        return self._reacquire_throttle(
            'challenge timer after five-second reverse recovery', 10)

    def _recover_drive_ended_at_house(self, current):
        """Move a crash-ended drive to retained-SP inspection without input."""
        def house_document(obs):
            document = getattr(obs, 'doc', None)
            if document is None:
                return Document([])
            if (not owned_home_entry(document) and
                    document.has('Enter House', (60, 480, 620, 150), contains=True) and
                    getattr(obs, 'frame', None) is not None and
                    getattr(self.nav, 'reader', None) is not None and
                    hasattr(obs.frame, '__getitem__')):
                document = refine_home_prompt(self.nav.reader, obs.frame, document)
            return document
        if not owned_home_entry(house_document(current)):
            return False
        self.nav.pause(.25)
        settled = self.nav.observe()
        if (settled is current or
                getattr(settled, 'frame', None) is getattr(current, 'frame', None) or
                not owned_home_entry(house_document(settled))):
            return False
        self.emit('log', 'Challenge ended during recovery; verified the owned house twice. Reading retained SP before relaunching.')
        self.save(phase='read_sp', recovered_from_house=True)
        return True

    def _recover_drive_ended_at_home(self, current):
        """Accept a late-settling main home menu as a completed drive endpoint."""
        if self.nav.is_home(current) is not True:
            return False
        self.nav.pause(.25)
        settled = self.nav.observe()
        if (settled.screen != current.screen or
                self.nav.is_home(settled) is not True):
            return False
        self.emit('log', 'Challenge is no longer active; verified the garage twice. Reading retained SP before continuing.')
        self.save(phase='read_sp', recovered_from_garage=True)
        return True

    def drive(self):
        import pyautogui
        nav, p = self.nav, self.profile
        from .farm_throttle import ThrottleProof
        proof = self._throttle_proof = ThrottleProof(nav, p, remaining_seconds)
        self._farm_active_emitted = False
        def observed_start(o):
            proof.observe(o)
            # Recovery screens can settle after the phase-level precheck. Keep
            # recognizing them during this wait instead of timing out for 60s.
            if self.nav.is_home(o) is True:
                return True
            document = o.doc
            if (document.has('Enter House', (60, 480, 620, 150), contains=True) and
                    getattr(o, 'frame', None) is not None and
                    getattr(self.nav, 'reader', None) is not None):
                document = refine_home_prompt(self.nav.reader, o.frame, document)
                o.doc = document
            return (owned_home_entry(document) or timer_visible(document) or
                    result_visible(document) or event_paused(document))
        obs = nav.until(observed_start, 'active or paused challenge', timeout=60)
        if self._recover_drive_ended_at_house(obs) or self._recover_drive_ended_at_home(obs):
            return
        if event_paused(obs.doc):
            nav.key('esc')
            proof.reset()
            obs = nav.until(observed_start, 'active challenge timer', timeout=60)
        # until() already supplied two verified active/result frames. Reuse that
        # proof; an unpaused challenge needs no second identical startup wait.
        initial = obs
        if result_visible(initial.doc):
            self.save(exit_reason='natural_completion')
            return
        deadline = time.monotonic()+p.duration_seconds+120
        from .farm_motion import (StationaryWatch, scene_is_moving,
                                  speed_from_frame, motion_evidence,
                                  anti_afk_interval)
        refresh_interval = anti_afk_interval(p)
        movement = time.monotonic()
        bank_pulse_at = time.monotonic() + BANK_PULSE_SECONDS
        bank_pulse_index = int(self.data.get('bank_pulses', 0))
        remaining = remaining_seconds(initial.doc)
        if remaining is not None:
            self.save(timer_start=max(remaining,self.data.get('timer_start',0)))
        if remaining is not None and remaining <= p.duration_seconds-refresh_interval:
            # A resumed worker cannot know when the old worker last steered.
            # Send a pulse on the next verified active frame rather than
            # restarting a full interval and exceeding the event's AFK window.
            movement -= refresh_interval
        watch = TimerWatch()
        motion = StationaryWatch()
        stationary_retries = int(self.data.get('stationary_reverse_recoveries', 0))
        previous_motion_frame = None
        motion_check_at = time.monotonic() + 7
        held = False
        last_report = 0
        last_observation=time.monotonic()
        nav._farm_countdown_fast = True
        nav._farm_full_audit_due = time.monotonic() + FARM_FULL_AUDIT_SECONDS
        try:
            # Start throttle from the two-frame active proof, with fresh
            # focus/sync/F7 checks, instead of waiting for another full OCR pass.
            if timer_visible(initial.doc):
                held = self._press_throttle(pyautogui.keyDown)
            while time.monotonic() < deadline:
                obs = nav.observe()
                if proof.changed():
                    pyautogui.keyUp(p.accelerator)
                    held = False
                    self.data['focus_throttle_reacquisitions'] = self.data.get('focus_throttle_reacquisitions', 0) + 1
                proof.observe(obs)
                observed=time.monotonic()
                self.data['max_observation_gap_seconds']=round(max(self.data.get('max_observation_gap_seconds',0),observed-last_observation),3)
                self.data['observation_count']=self.data.get('observation_count',0)+1
                last_observation=observed
                if event_paused(obs.doc):
                    pyautogui.keyUp(p.accelerator)
                    held = False
                    paused_at = time.monotonic()
                    nav.key('esc')
                    held = self._reacquire_throttle('unpaused challenge', 30)
                    deadline += time.monotonic()-paused_at
                    watch = TimerWatch()
                    continue
                if result_visible(obs.doc):
                    self.save(exit_reason='natural_completion')
                    return
                if not timer_visible(obs.doc):
                    pyautogui.keyUp(p.accelerator)
                    held = False
                    self.data['throttle_interruptions']=self.data.get('throttle_interruptions',0)+1
                    # Release immediately, but allow a short HUD transition to
                    # settle before stopping. No driving input while uncertain.
                    held = self._reacquire_throttle(
                        'challenge timer after a brief interruption', 10, allow_pause=True)
                    continue
                nav.check()
                if proof.changed():
                    pyautogui.keyUp(p.accelerator)
                    held = False
                    proof.reset()
                    continue
                remaining = remaining_seconds(obs.doc)
                watch.observe(remaining)
                if remaining is not None:
                    elapsed=max(0,self.data.get('timer_start',remaining)-remaining)
                    self.data['drive_seconds']=elapsed
                    if (p.share_code == '155439962' and held and
                            time.monotonic() >= motion_check_at):
                        # Existing active-countdown, focus and sync guards ran
                        # above. Read only a small speed HUD crop every 7s.
                        visual_motion = scene_is_moving(previous_motion_frame, obs.frame)
                        previous_motion_frame = obs.frame.copy()
                        # Animated tunnel props can move while the car is
                        # wedged. Read the numeric speedometer on every sample;
                        # an exact zero overrides that misleading scene motion.
                        speed = speed_from_frame(nav.reader, obs.frame)
                        effective_speed = motion_evidence(speed, visual_motion)
                        nav.check()
                        self.data['motion_speed_reads'] = self.data.get('motion_speed_reads', 0)+1
                        if effective_speed is not None:
                            self.data['motion_valid_reads'] = self.data.get('motion_valid_reads', 0)+1
                        if self.data['motion_speed_reads'] % 9 == 1:
                            self.emit('log', f'Farm motion sample: speed={speed}; visual={visual_motion}; valid '
                                      f'{self.data.get("motion_valid_reads", 0)}/{self.data["motion_speed_reads"]}.')
                        stationary = motion.observe(effective_speed, elapsed, time.monotonic())
                        motion_check_at = time.monotonic()+7
                        if stationary and not proof.changed():
                            samples = motion.samples
                            if stationary_retries < 1:
                                held = self._reverse_stationary_car(pyautogui, 5.0)
                                if held:
                                    stationary_retries += 1
                                    self.data['stationary_reverse_recoveries'] = stationary_retries
                                    self.emit('log', 'Stationary car recovered: reversed for 5s, re-proved the active challenge, and resumed forward throttle.')
                                    motion = StationaryWatch()
                                    previous_motion_frame = None
                                    motion_check_at = time.monotonic()+7
                                    movement = time.monotonic()
                                    continue
                            pyautogui.keyUp(p.accelerator)
                            pyautogui.keyUp('s')
                            held = False
                            self.emit('log', 'Stationary recovery was unavailable or the car stalled again; exiting this attempt to verify retained SP.')
                            self.save(phase='early_leave', exit_reason='stationary_recovery_exit',
                                      drive_seconds=elapsed, stationary_speed_samples=samples,
                                      stationary_reverse_recoveries=stationary_retries)
                            return
                    plan=self.data.get('refill_plan',{})
                    if plan.get('planned_exit')=='target_top_up' and elapsed>=plan['planned_drive_seconds']:
                        pyautogui.keyUp(p.accelerator)
                        held=False
                        self.save(phase='early_leave',exit_reason='intentional_target_top_up',drive_seconds=elapsed)
                        return
                if remaining is not None and time.monotonic() - last_report >= 15:
                    self.emit('screen', p.name+' active')
                    mode='TOP-UP' if self.data.get('refill_plan',{}).get('planned_exit')=='target_top_up' else 'BULK'
                    self.emit('status', f'Farming SP — {mode} · {duration(elapsed)} elapsed · {duration(planned_farm_remaining(remaining, elapsed, self.data.get('refill_plan')))} left in {p.name}. SP checked after exit.')
                    last_report = time.monotonic()
                if not held:
                    held = self._press_throttle(pyautogui.keyDown)
                    if not held:
                        nav.pause(.06)
                        continue
                if (p.share_code == '155439962' and held and
                        time.monotonic() >= bank_pulse_at):
                    if self._pulse_bank(pyautogui, bank_pulse_index):
                        bank_pulse_index += 1
                        self.data['bank_pulses'] = bank_pulse_index
                    bank_pulse_at = time.monotonic() + BANK_PULSE_SECONDS
                if time.monotonic()-movement >= refresh_interval:
                    nav.check()
                    if proof.changed():
                        pyautogui.keyUp(p.accelerator)
                        held = False
                        proof.reset()
                        continue
                    held = self._refresh_anti_afk(pyautogui)
                    movement = time.monotonic()
                    self.emit('log', 'Refreshed accelerator and sent the short anti-AFK movement for '+p.name)
                nav.pause(.15 if remaining is not None and remaining<=3 else .5)
            raise RuntimeError('Challenge exceeded its duration; accelerator released')
        finally:
            nav._farm_countdown_fast = False
            pyautogui.keyUp(p.accelerator)
            pyautogui.keyUp(p.movement_key)
            pyautogui.keyUp('s')

    def run(self, identifier, *, return_collection=True):
        nav = self.nav
        skipped=(self.data.get('phase')=='complete' and self.data.get('skipped_refill') is True
                 and not self.data.get('launch_attempts',0))
        if self.data.get('id') != identifier or skipped:
            if self.data and self.data.get('phase') != 'complete':
                raise RuntimeError('An unfinished challenge exists; resume it before starting another')
            from .farm_motion import anti_afk_interval
            self.data = dict(id=identifier, phase='prepare', share_code=self.profile.share_code,
                             optimizer_version=FARM_OPTIMIZER_VERSION,
                             anti_afk_interval_seconds=anti_afk_interval(self.profile))
            self.save()
        if self.data['share_code'] != self.profile.share_code:
            raise RuntimeError('The challenge profile changed during an unfinished farm run')
        if 'refill_plan' not in self.data and isinstance(self.data.get('before_sp'),int):
            from .refill_control import decision_from_files, describe
            target=getattr(self,'target_sp',999)
            policy=decision_from_files(self.data['before_sp'],target,self.path.parent,self.profile,
                            reserve=getattr(self,'reserve_sp',0),check=nav.check)
            if getattr(self, 'force_target_sp', False):
                from .refill_control import force_exact_target
                policy = force_exact_target(policy, self.data['before_sp'], target, self.profile)
            self.save(refill_plan=policy,target_sp=target)
            self.emit('log',describe(policy,self.profile.name))
        if (self.data.get('refill_plan',{}).get('mode')=='convert' and
                self.data['phase'] in {'prepare','search','launch'} and not self.data.get('launch_attempts',0)):
            # Re-prove the balance on the owned farm car before skipping a
            # persisted but unlaunched search. An active drive is never replanned.
            self.save(phase='prepare')
        if self.data['phase'] != 'complete':
            self.emit('farm_started', dict(id=identifier, before_sp=self.data.get('before_sp'),share_code=self.profile.share_code,profile_name=self.profile.name))
        while self.data['phase'] != 'complete':
            nav.check()
            phase = self.data['phase']
            self.emit('stage', f'farm_{phase}')
            if phase == 'prepare':
                from .farm_balance import recent_menu_sp, menu_farm_ready, remember_farm_tree
                menu_proof=recent_menu_sp(nav)
                proof = recent_sp(nav)
                current = (menu_proof.observation if menu_proof is not None else
                           proof.observation if proof is not None else nav.observe())
                menu_ready=menu_farm_ready(nav,self.profile,current)
                ready = (current.screen == 'car_mastery' and
                    farm_car(nav.reader.read(core.crop(current.frame, (810,190,610,100))), self.profile) and
                    farm_tree_owned(current.frame))
                if menu_ready:
                    self.emit('log','Same-process owned Subaru proof and current pause car verified; repeat farm skips mastery.')
                elif ready:
                    self.emit('log', 'Verified maxed Subaru mastery is already open; skipping the repeat garage trip.')
                else:
                    nav.select_farm_car(self.profile)
                from .farm_balance import selected_farm_balance
                points = selected_farm_balance(nav,self.profile) if not menu_ready else None
                if points is not None:
                    menu_ready=True
                else:
                    points = nav.available_sp(allow_menu=menu_ready)
                if not menu_ready:
                    title = nav.reader.read(core.crop(nav.last.frame, (810,190,610,100)))
                    if not farm_car(title, self.profile) or not farm_tree_owned(nav.last.frame):
                        raise RuntimeError('The selected 1998 Subaru 22B does not have its full mastery tree owned')
                    remember_farm_tree(nav,self.profile)
                target=getattr(self,'target_sp',999)
                from .refill_control import decision_from_files, describe
                policy=decision_from_files(points,target,self.path.parent,self.profile,
                                reserve=getattr(self,'reserve_sp',0),check=nav.check)
                if getattr(self, 'force_target_sp', False):
                    from .refill_control import force_exact_target
                    policy = force_exact_target(policy, points, target, self.profile)
                self.emit('log',describe(policy,self.profile.name))
                if points >= target or policy.get('mode')=='convert':
                    self.save(phase='return',before_sp=points,after_sp=points,refill_plan=policy,
                              target_sp=target,skipped_refill=True,exit_reason='refill_convert_existing')
                    continue
                from .farm_route import prepare_search
                prepare_search(nav,self.profile)
                self.save(phase='search', before_sp=points,refill_plan=policy,target_sp=target)
            elif phase == 'search':
                nav.search_challenge(self.profile)
                # Save before launching; a crash can never blindly launch twice.
                self.save(phase='launch')
            elif phase == 'launch':
                obs = nav.observe()
                if not timer_visible(obs.doc) and not result_visible(obs.doc):
                    if not (obs.doc.has('Search Results', contains=True) and obs.doc.has('Select', FOOTER, contains=True)):
                        raise RuntimeError('The searched challenge result is no longer visible')
                    self.save(phase='drive', launch_attempts=self.data.get('launch_attempts', 0)+1)
                    nav.key('enter')
                else:
                    self.save(phase='drive')
            elif phase == 'drive':
                # A stopped challenge may have been exited before the worker
                # resumes. Confirm the garage twice before reading retained SP.
                current = nav.observe()
                if self._recover_drive_ended_at_house(current):
                    continue
                if nav.is_home(current):
                    if self._recover_drive_ended_at_home(current):
                        continue
                self.drive()
                if self.data['phase']=='drive':
                    self.save(phase='leave')
            elif phase == 'early_leave':
                self.leave_early()
                self.save(phase='leave')
            elif phase == 'leave':
                obs = nav.observe()
                if result_visible(obs.doc):
                    # In the repo's challenge UI Enter retries a failure and Esc
                    # retries a success. Select the visible Continue/Exit action.
                    action = result_exit_action(obs.doc, result_visible, FOOTER)
                    if action is None:
                        raise RuntimeError('No verified exit action on the challenge result')
                    repeated = RepeatedResultExit(action, result_visible, FOOTER)
                    repeated(obs)
                    nav.until(repeated, 'fresh repeated challenge result exit', timeout=10)
                    nav.key(action)
                exited = nav.until(lambda o: nav.is_roam(o) or nav.is_pause(o) or nav.is_home(o)
                                   or o.screen == 'challenge_rating', 'leaving challenge', timeout=60)
                if exited.screen == 'challenge_rating':
                    # The optional rating is not part of farming. Verify and
                    # select Cancel instead of submitting a Like or Dislike.
                    nav.dismiss_challenge_rating()
                self.save(phase='read_sp')
            elif phase == 'read_sp':
                from .farm_route import read_after_run
                points = read_after_run(nav,self.profile)
                if points < self.data['before_sp']:
                    raise RuntimeError('SP decreased after the challenge. No purchase or reward was inferred.')
                if points == self.data['before_sp']:
                    if self.profile.share_code=='169055890':
                        self.emit('log','Mini V2 retained no SP; ending this trial run and reverting to Mega V6.')
                        self.save(phase='return',after_sp=points,exit_reason='mini_no_retained_sp')
                        continue
                    if self.data.get('exit_reason')=='intentional_target_top_up':
                        from .analytics import save
                        save(core.BASE/'runs/early_exit_validation.json',dict(disabled=True,reason='Early exit retained no SP',challenge_id=identifier))
                    nav.invalidate_farm_settings()
                    self.emit('log', 'No retained SP increase. Rechecking farm difficulty, Skills HUD and frame rate before retrying.')
                    self.save(phase='prepare', empty_attempts=self.data.get('empty_attempts', 0)+1)
                    nav.ensure_home()
                    continue
                from .farm_yield_health import assess
                from .analytics import read as read_analytics
                health = assess(dict(self.data, gained_sp=points-self.data['before_sp'],
                                     capped=points == 999),
                                read_analytics(self.path.parent/'analytics.json').get('farms', []),
                                self.profile.duration_seconds)
                self.data['yield_health'] = health
                if ((points-self.data['before_sp'] < 21 or health['degraded']) and points < 999):
                    nav.invalidate_farm_settings()
                    self.emit('log', f'Low farm yield: {points-self.data["before_sp"]} SP; '
                              f'recent full-run median {health.get("expected_sp", "unavailable")}. '
                              'Rechecking farm difficulty, Skills HUD and frame rate before the next challenge; cause not established.')
                policy=self.data.get('refill_plan',{})
                if self.data.get('exit_reason')=='intentional_target_top_up':
                    from .analytics import save
                    save(core.BASE/'runs/early_exit_validation.json',dict(disabled=False,challenge_id=identifier,
                        before_sp=self.data['before_sp'],after_sp=points,retained=points-self.data['before_sp'],drive_seconds=self.data.get('drive_seconds')))
                rate=policy.get('estimated_sp_per_second')
                raw=rate*self.data.get('drive_seconds',0) if rate else None
                self.save(phase='return', after_sp=points,raw_estimated_sp=raw,
                    estimated_cap_loss_sp=max(0,raw-(points-self.data['before_sp'])) if raw is not None and points==999 else 0)
            elif phase == 'return':
                if return_collection:
                    nav.return_collection()
                self.save(phase='complete')
            else:
                raise RuntimeError(f'Unknown saved challenge stage: {phase}')
        if self.data.get('skipped_refill') is True:
            self.emit('farm_skipped',dict(id=identifier,reason='verified_balance_already_funds_conversion',
                                        before_sp=self.data['before_sp'],after_sp=self.data['after_sp']))
            return self.data['after_sp']
        self.emit('farm_completed', dict(id=identifier, before_sp=self.data.get('before_sp'),share_code=self.profile.share_code,profile_name=self.profile.name,
            after_sp=self.data['after_sp'], empty_attempts=self.data.get('empty_attempts', 0),
            launch_attempts=self.data.get('launch_attempts', 0),**{k:self.data.get(k) for k in
                ('exit_reason','drive_seconds','raw_estimated_sp','estimated_cap_loss_sp',
                 'max_observation_gap_seconds','observation_count','throttle_interruptions',
                 'yield_health','motion_speed_reads','motion_valid_reads',
                 'stationary_speed_samples')},target_sp=self.data.get('target_sp',999)))
        return self.data['after_sp']

    def leave_early(self):
        """Quit only from the verified event pause menu and its quit dialog."""
        nav=self.nav
        def confirmation(o):
            text=normalize(' '.join(l.text for l in o.doc.lines))
            return any(s in text for s in ('quit event','quit this event','quit the event','quit challenge','quit this challenge')) and o.doc.has('Yes') and o.doc.has('No')
        obs=nav.observe()
        if nav.is_roam(obs) or nav.is_home(obs) or obs.screen=='challenge_rating': return
        if timer_visible(obs.doc):
            nav.key('esc')
            obs=nav.until(lambda o:event_paused(o.doc),'event pause before planned early exit')
        if event_paused(obs.doc):
            label='Quit Event' if obs.doc.has('Quit Event') else 'Quit'
            nav.click_label(obs.screen,label,(1390,260,320,600),contains=True)
            obs=nav.until(lambda o:confirmation(o) or nav.is_roam(o) or o.screen=='challenge_rating','quit confirmation')
        if confirmation(obs):
            nav.click_label(obs.screen,'Yes')
            nav.until(lambda o:nav.is_roam(o) or nav.is_home(o) or o.screen=='challenge_rating','planned early exit',timeout=60)
        elif not (nav.is_roam(obs) or nav.is_home(obs) or obs.screen=='challenge_rating'):
            raise RuntimeError('Unexpected early-exit screen; no confirmation sent')
