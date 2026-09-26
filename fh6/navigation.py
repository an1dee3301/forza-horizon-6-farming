"""Screen-driven navigation between the existing purchase and mastery modules."""
import re
import time
from dataclasses import dataclass

import cv2
import numpy as np

import forza_cycle as core
from .ocr import normalize
from .points import read_points
from .game_lifecycle import GameCrashed
from .garage import filter_dialog, set_favorites

LEFT = (65, 210, 390, 725)
TABS = (170, 145, 945, 55)
HOME_TABS = (('campaign', 'CAMPAIGN'), ('buy_sell', 'BUY & SELL'), ('cars', 'CARS'),
             ('customizable', 'CUSTOMIZABLE GARAGE'), ('character', 'CHARACTER'))
FOCUS_SETTLE_SCREENS = frozenset({'campaign', 'cars', 'home_tab', 'upgrades',
    'journal', 'discover', 'collection_grid', 'manufacturers', 'garage_grid',
    'garage_filter', 'sort_selection', 'recent_jump', 'paints', 'car_select', 'settings',
    'remove_confirmation', 'no_cars'})

# Calibrated screens keep their fast control bands and also read the center,
# where the observed FHC11, unsaved-change, resource and action dialogs appear.
# Unknown screens still use full-frame OCR, while separate top-level crash and
# sync windows are guarded by GameLifecycle before input.
SPARSE_OCR_REGIONS = {
    'garage_grid': ((0, 0, 1920, 300), (425, 300, 1070, 640),
                    (0, 940, 1920, 140)),
    'mad_mike_mastery': ((0, 0, 1920, 230), (425, 230, 1070, 710),
                         (0, 940, 1920, 140)),
    'sort_selection': ((0, 0, 1920, 230), (425, 230, 1070, 710),
                       (0, 940, 1920, 140)),
}


def focus_settling_allowed(screen, label):
    # Car-action dialogs also contain destructive rows. Only entering the
    # already identified car may use the bounded, input-free focus grace.
    return screen in FOCUS_SETTLE_SCREENS or (screen == 'car_action' and label in {
        'Get In Car', 'Remove Car From Garage'})


def navigation_poll_delay(observation_seconds, fast=True):
    """Keep fresh frame checks; do not add a full delay after expensive OCR."""
    if not fast:
        return .15
    return max(.01, min(.06, .12-max(0., observation_seconds)))


def recent_sort_on_grid(doc, calibrated=False):
    """Accept a split footer caption, never an unrelated Recently Added label."""
    rows = []
    for line in sorted(doc.lines, key=lambda row: row.center[1]):
        x, y = line.center
        if not (65 <= x < 1765 and 975 <= y < 1040):
            continue
        row = next((row for row in rows if abs(row[0]-y) <= 12), None)
        if row is None:
            row = [y, []]
            rows.append(row)
        row[1].append(line)
    captions = [normalize(' '.join(line.text for line in sorted(row, key=lambda item: item.center[0])))
                for _, row in rows]
    matches = sum(' jump to recently added ' in f' {caption} ' for caption in captions)
    conflicting = any(' jump to manufacturer' in f' {caption}' for caption in captions)
    return (matches == 1 or matches == 0 and calibrated is True) and not conflicting


def recent_sort_verified(obs):
    if obs.screen not in {'garage_grid', 'car_select'}:
        return False
    result = getattr(obs, 'result', {})
    # The existing calibrated footer distinguishes Recently Added from
    # Manufacturer in both positive and negative reviewed examples. A
    # contradictory OCR caption still prevents the shortcut.
    calibrated = (obs.screen == result.get('screen') == 'garage_grid' and
                  result.get('recent_jump_available') is True)
    return recent_sort_on_grid(obs.doc, calibrated)


def active_home_tab(obs):
    """Use the verified menu body, otherwise one uniquely selected visible tab."""
    if obs.screen in {'campaign', 'cars', 'home_tab'}:
        # The selected caption can disappear from OCR. Its full-width lime
        # underline remains visible in the calibrated English 1080p tab bar.
        strip = obs.frame[186:196, 176:1107]
        mask = cv2.inRange(cv2.cvtColor(strip, cv2.COLOR_BGR2HSV), (32,160,190), (42,255,255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        choices = []
        edges = (176, 341, 514, 625, 929, 1107)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            x += 176
            if 2 <= h <= 8:
                for index, (left, right) in enumerate(zip(edges, edges[1:])):
                    if abs(x-left) <= 8 and abs(w-(right-left)) <= 12:
                        choices.append(HOME_TABS[index][0])
        if len(choices) == 1:
            return choices[0]
        if choices:
            return None
    if obs.screen in {'campaign', 'cars'}:
        # These classifications require the destination's distinct menu items.
        # OCR can omit the selected white-on-black tab caption itself.
        return obs.screen
    active = []
    for name, label in HOME_TABS:
        matches = obs.doc.find(label, TABS)
        if len(matches) != 1:
            return None
        x, y, w, h = matches[0].box
        region = core.crop(obs.frame, (x-7, y-4, w+14, h+8))
        if np.mean(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) < 65) > .55:
            active.append(name)
    return active[0] if len(active) == 1 else None


def menu_name(doc, result):
    # Calibrated transaction and mastery recognition always takes precedence.
    if result['screen'] != 'unknown':
        return result['screen']
    has = doc.has
    text = normalize(' '.join(line.text for line in doc.lines))
    if ('you have been disconnected' in text and 'please try again later' in text and
            ('view network diagnostics' in text or 'return to freeroam to accept' in text)):
        return 'network_disconnected'
    if (has('Network Diagnostics', (550, 420, 820, 150), contains=True) and
            has('Horizon Solo', (550, 500, 820, 160), contains=True) and
            has('Enter', (65, 965, 300, 100), contains=True)):
        return 'network_diagnostics'
    if (has('Series Update', (65,70,700,110), contains=True) and
            has('Series Ends In', (1400,70,470,110), contains=True) and
            has('Next', (65,975,240,70), contains=True)):
        return 'series_update'
    if (has('Welcome to the Festival Playlist', (400,65,1050,115), contains=True) and
            has('Series Update', (190,975,400,70), contains=True) and
            has('Back', (65,975,145,70), contains=True)):
        return 'festival_playlist'
    # This is a post-reward acknowledgement, not a purchase receipt. Require
    # both exact dialog lines and its keyboard acknowledgement in the footer.
    if (has('New Car Collected!', (625,465,675,80)) and
            has('A new car has been added to your Garage.', (625,540,675,85)) and
            (has('Enter', (65,975,200,70), contains=True) or has('Ok', (65,975,200,70)))):
        return 'new_car_collected'
    if filter_dialog(doc):
        return 'garage_filter'
    if has('Rate Challenge?', (625,365,670,80)) and all(
            has(label, (625,545,670,165)) for label in ('Like', 'Dislike', 'Cancel')):
        return 'challenge_rating'
    if has('Search', (550,300,820,90)) and has('Share Code', contains=True) and has('Confirm'):
        return 'challenge_search'
    if has('Share Code', (620,420,680,90)) and has('Enter Share Code', contains=True):
        return 'share_code'
    if (has('Challenges', (65,85,650,85)) and
            has('Trending', (390,145,270,65)) and
            has('Search', (600,975,240,65), contains=True) and
            has('Challenge Options', (350,975,250,65), contains=True)):
        return 'challenge_browser'
    if has('EventLab', (380,215,400,65)) and has('Play Event') and has('Challenges', contains=True):
        return 'eventlab'
    if (has('Car Already Owned', contains=True) and
            has('Add to Garage', contains=True) and has('Send as a Gift', contains=True) and
            (has('Sell', contains=True) or has('Sell Duplicate', contains=True) or
             has('Sell Car', contains=True) or has('Sell for', contains=True))):
        return 'wheelspin_duplicate'
    if (has('Collect', contains=True) and
            (has('Spin Again', contains=True) or has('Collect Prize', contains=True)) and
            not has('Add to Garage', contains=True)):
        return 'wheelspin_reward'
    if has('MY HORIZON', (240,200,1440,50)) and has('CREATIVE HUB', (240,200,1440,50)):
        return 'pause_menu'
    if ((has('Super Wheelspin', contains=True) or has('Wheelspin', contains=True)) and
            has('Spin', (65,950,500,120), contains=True)):
        return 'wheelspin_menu'
    if has('Settings', (70,150,400,65)) and has('Difficulty', LEFT) and has('HUD & Gameplay', LEFT):
        return 'settings'
    if has('Car Mastery', (65, 80, 1000, 120)) and has('Available Points', contains=True):
        return 'car_mastery'
    if has('Toggle Camera Height', (65, 975, 1700, 65), contains=True) and \
            has('Photo Mode', (65, 975, 1700, 65), contains=True):
        return 'showroom'
    if has('Recently Added', (250, 170, 1410, 90)) and has('All Cars', (250, 250, 1410, 650)):
        return 'recent_jump'
    if has('Manufacturers', (250, 170, 1410, 90)) or has('Manufacturer', (250, 170, 1410, 90)):
        return 'manufacturers'
    if has('Sort Selection'):
        return 'sort_selection'
    if has('Select An Action'):
        return 'car_action'
    # The title appears before the modal body during its short entrance.
    # Callers still wait for stable labels before choosing Yes or No.
    if has('Remove Car From Garage'):
        return 'remove_confirmation'
    if has('No Cars Available') and has('filter settings', contains=True):
        return 'no_cars'
    if has('Car Collection', (100, 80, 650, 110)) and has('Manufacturers', contains=True):
        return 'collection_grid'
    if has('Horizon Legend') and has('Master Explorer'):
        return 'journal'
    if has('Master Explorer', (550, 80, 800, 120)) and has('Car Collection'):
        return 'discover'
    if has('Collection Journal', LEFT) and has('Settings', LEFT):
        return 'campaign'
    if has('Designs & Paints', LEFT) and has('My Cars', LEFT):
        return 'cars'
    if has('Car Mastery', LEFT) and has('Custom Upgrade', LEFT):
        return 'upgrades'
    if has('Choose Car', contains=True) and (has('Paint Car', contains=True) or
                                           has('My Designs', contains=True) or
                                           has('Find New Designs', contains=True)):
        return 'paints'
    if (has('Car Select', (70, 85, 750, 100))) and \
            has('Sort', (65, 975, 1700, 65), contains=True):
        return 'car_select'
    if (has('My Cars', (70, 85, 600, 70)) or has('Choose Car', (70, 85, 750, 100))) and \
            has('Sort', (65, 975, 1700, 65), contains=True):
        return 'garage_grid'
    if has('CUSTOMIZABLE GARAGE', TABS) and has('BUY & SELL', TABS):
        return 'home_tab'
    return 'unknown'


class SelectedCardError(RuntimeError):
    def __init__(self, matches):
        self.matches = matches
        super().__init__(f'Could not distinguish the selected car card ({matches} matches)')


class NetworkDisconnected(RuntimeError):
    """The exact FH6 network-loss flow is visible and can be recovered safely."""


def selected_card(frame):
    """Locate the one lime rectangular card, independent of its grid position."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # FH6's selected-car border is the saturated lime band. Restricting this
    # contour to hue 20..45 fragments the anti-aliased lower-row border on the
    # current renderer even though core.has_focus still proves its lime edges.
    mask = cv2.inRange(hsv, (32, 160, 190), (60, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 300 <= w <= 370 and 230 <= h <= 285 and y >= 200 and y+h <= 980:
            if core.has_focus(frame, (x, y, w, h)):
                boxes.append((x, y, w, h))
    if len(boxes) != 1:
        raise SelectedCardError(len(boxes))
    return boxes[0]


def label_focused(frame, label):
    """Require a complete focus rectangle enclosing this particular OCR label."""
    lx, ly, lw, lh = label.box
    for x,y,w,h in focus_boxes(frame):
        if x <= lx and y <= ly and lx+lw <= x+w and ly+lh <= y+h:
            return True
    return False


def focus_boxes(frame):
    # Lime focus is distinct from the yellow fill of EventLab tiles.
    mask = cv2.inRange(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV), (32,160,190), (42,255,255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if w < 150 or not 35 <= h <= 800:
            continue
        interior=mask[y+8:y+h-8,x+8:x+w-8]
        if interior.size and np.mean(interior > 0) < .4 and core.has_focus(frame,(x,y,w,h)):
            boxes.append((x,y,w,h))
    return boxes


def manufacturer_steps(obs, box, target):
    """Count visible, evenly spaced rows; only reversible arrow keys use this."""
    x,y,w,h=box
    tx,ty=target.center
    if not x <= tx <= x+w:
        return 1
    centers=sorted({line.center[1] for line in obs.doc.lines
                    if x <= line.center[0] <= x+w and 255 <= line.center[1] <= 905})
    selected=[cy for cy in centers if y <= cy <= y+h]
    if len(selected)!=1 or ty not in centers:
        return 1
    lo,hi=sorted((centers.index(selected[0]),centers.index(ty)))
    gaps=[b-a for a,b in zip(centers[lo:hi],centers[lo+1:hi+1])]
    if not gaps or min(gaps)<h*.8 or max(gaps)>h*1.5 or max(gaps)-min(gaps)>5:
        return 1
    return min(4,hi-lo)


def fresh_mazda_card(card):
    # The selected title scrolls horizontally and may hide the race number.
    # Model words, year/manufacturer, and NEW must all belong to this card.
    return (card.has('MAD MIKE 808', contains=True) and
            card.has('1974 MAZDA', contains=True) and card.has('NEW'))


@dataclass
class Observation:
    frame: object
    result: dict
    doc: object
    screen: str
    captured_monotonic: float | None = None


def pointer_target_focused(obs, target):
    boxes = focus_boxes(obs.frame)
    if len(boxes) != 1:
        return False
    x, y, w, h = boxes[0]
    lx, ly, lw, lh = target.box
    return x <= lx and y <= ly and lx+lw <= x+w and ly+lh <= y+h


def mastery_pointer_other_focus(obs, target):
    """Exact upgrade target plus one complete, different known row focus."""
    if obs.screen != 'upgrades':
        return None
    matches = obs.doc.find('Car Mastery', LEFT)
    if len(matches) != 1 or any(abs(a-b) > 3 for a, b in zip(matches[0].box, target.box)):
        return None
    boxes = focus_boxes(obs.frame)
    if len(boxes) != 1:
        return None
    x, y, w, h = boxes[0]
    if not (65 <= x and x+w <= 455 and 210 <= y and y+h <= 935):
        return None
    labels = [normalize(line.text) for line in obs.doc.lines
              if x <= line.box[0] and y <= line.box[1] and
                 line.box[0]+line.box[2] <= x+w and line.box[1]+line.box[3] <= y+h]
    allowed = {'custom upgrade', 'auto upgrade', 'custom tuning',
               'my tuning setups', 'find tuning setups', 'followed players'}
    if len(labels) != 1 or labels[0] not in allowed:
        return None
    return labels[0], (*boxes[0], *matches[0].box)


def complete_home_tab_row(obs):
    """Require every exact caption in its calibrated home-tab cell."""
    if obs.screen not in {'campaign', 'cars', 'home_tab'}:
        return False
    doc = getattr(obs, 'doc', None)
    if doc is None:
        return False
    edges = (176, 341, 514, 625, 929, 1107)
    for (_, label), left, right in zip(HOME_TABS, edges, edges[1:]):
        matches = doc.find(label, TABS)
        if len(matches) != 1:
            return False
        x, y, w, h = matches[0].box
        if not (left <= x and x+w <= right and 155 <= y and y+h <= 187):
            return False
    return active_home_tab(obs) is not None


def visible_collection_target_hint(obs):
    """Text may settle before the card artwork; this permits observation only."""
    if obs.screen != 'collection_grid' or obs.result.get('screen') != 'collection_grid':
        return False
    models = obs.doc.find('#123 Mad Mike 808', (120, 210, 1660, 760), contains=True)
    if len(models) != 1:
        return False
    cx, cy = models[0].center
    columns = [x for x in (129, 459, 789, 1119, 1449) if x <= cx < x+326]
    rows = [y for y in (220, 470, 720) if y+175 <= cy < y+245]
    return (len(columns) == len(rows) == 1 and
            len(obs.doc.find('1974 Mazda', (columns[0], rows[0]+175, 326, 70))) == 1)


class Navigator:
    def __init__(self, recognizer, reader, capture, monitor, title, running, timeout=30, emit=lambda *a: None):
        self.recognizer, self.reader = recognizer, reader
        self.capture, self.monitor = capture, monitor
        self.title, self.running, self.timeout = title, running, timeout
        self.emit = emit
        self.last = None
        self.prefer_keyboard = False
        self.sync_guard = None
        self.display_guard = None
        self.fast_navigation = True
        self.garage_filters_clear = False
        # A successful, screen-verified Recently Added selection remains in
        # force while this worker owns the uninterrupted game session. Missing
        # footer OCR may reuse that proof; contradictory footer text may not.
        self.garage_recent_sort_verified = False
        self._ready = None
        self.performance = None
        self.focus_generation = 0

    def measured(self, name, action):
        performance = getattr(self, 'performance', None)
        return performance.measure(name, action) if performance else action()

    def probe(self, method, *args):
        performance=getattr(self,'performance',None)
        if performance:
            performance.record_probe(method,*args)

    def invalidate_ready(self):
        self._ready = None
        self._menu_sp_proof = None

    def check(self):
        if not self.running.is_set():
            self.garage_filters_clear = False
            self.garage_recent_sort_verified = False
            raise core.MasteryStopped('Stopped with F7')
        if self.sync_guard:
            self.sync_guard.check()
        if self.display_guard:
            self.display_guard.check()
        foreground = core.foreground_title()
        if self.title.casefold() not in foreground.casefold():
            self.garage_filters_clear = False
            # A foreground change cannot alter the in-game garage sort.  Keep
            # the screen-verified session proof; choose_car still rejects an
            # explicit Manufacturer footer before selecting anything.
            self.focus_generation += 1
            self.invalidate_ready()
        restore = getattr(self, 'restore_focus', None)
        if self.title.casefold() not in foreground.casefold() and restore:
            self.invalidate_ready()
            if restore():
                foreground = core.foreground_title()
        if self.title.casefold() not in foreground.casefold():
            raise RuntimeError(f'Game focus lost ({foreground or "no active window"}). Return to the game before starting again.')

    def pause(self, seconds):
        start=time.monotonic()
        end = start+seconds
        try:
            while time.monotonic() < end:
                self.check()
                time.sleep(min(.05, max(0, end-time.monotonic())))
        finally:
            if self.performance:
                self.performance.pacing_seconds+=time.monotonic()-start

    def observe(self):
        self.check()
        image_cache = getattr(self, 'report_images', None)
        obs = self.observe_sync()
        if self.sync_guard:
            self.sync_guard.inspect(obs.doc)
        self.check()
        observer = getattr(self, 'account_observer', None)
        trace = getattr(self, 'entry_trace', None)
        if trace:
            trace.offer(obs)
        confirm_account = False
        try:
            if observer:
                self.measured('account_submit', lambda: observer.observe(obs, reader=self.reader))
                confirm_account = observer.needs_confirmation and observer.visible(obs)
        except Exception:
            pass
        while confirm_account:
            observer.confirmation_attempts += 1
            self.pause(.15)
            obs = self.observe_sync()
            if self.sync_guard:
                self.sync_guard.inspect(obs.doc)
            self.check()
            try:
                observer.observe(obs, reader=self.reader, force=True)
                confirm_account = observer.needs_confirmation and observer.visible(obs)
            except Exception:
                break
        try:
            # The pause classification is already part of control recognition.
            # All report scheduling, policy checks, desktop enumeration,
            # encoding and persistence continue in the report cache/worker.
            if image_cache and obs.screen == 'pause_menu':
                image_cache.offer(obs, self.monitor)
        except Exception:
            pass  # Optional reporting cannot interrupt the game pipeline.
        return obs

    def observe_sync(self, *, allow_disconnect=False):
        # Read-only capture for the sync gate: no focus restoration or inputs.
        self.invalidate_ready()
        if not self.running.is_set():
            raise core.MasteryStopped('Stopped with F7')
        frame = self.measured('capture', lambda: cv2.cvtColor(np.asarray(self.capture.grab(self.monitor)), cv2.COLOR_BGRA2BGR))
        captured_monotonic = time.monotonic()
        if frame.shape[:2] != (1080, 1920):
            raise RuntimeError('Set the game and selected monitor to 1920 × 1080.')
        result = self.measured('recognition', lambda: self.recognizer.inspect(frame))
        regions = SPARSE_OCR_REGIONS.get(result.get('screen'))
        regional = getattr(self.reader, 'read_regions', None)
        sparse = bool(regions and callable(regional))
        doc = self.measured('menu_ocr',
            lambda: regional(frame, regions) if sparse else self.reader.read(frame))
        screen = menu_name(doc, result)
        if screen == 'sort_selection' and not sparse:
            # Full-frame OCR can omit the selected first row against the blurred
            # garage. Reading just the dialog recovers it without guessing.
            doc = self.reader.refine_region(frame, doc, (625, 313, 670, 453))
        self.last = Observation(frame, result, doc, screen, captured_monotonic)
        self.last.focus_generation = self.focus_generation
        self.probe('observe',frame,screen)
        if screen in {'network_disconnected', 'network_diagnostics'} and not allow_disconnect:
            raise NetworkDisconnected('FH6 network connection was lost')
        danger = ('insufficient credits', 'not enough credits', 'cannot afford',
                  'not enough skill points', 'garage is full', 'connection lost',
                  'remove car', 'delete car', 'video card crash',
                  'terminated unexpectedly', 'fhc11', 'unsaved changes',
                  'unsaved progress', 'quit without saving', 'exit without saving')
        text = normalize(' '.join(line.text for line in doc.lines))
        if any(phrase in text for phrase in ('video card crash', 'terminated unexpectedly', 'fhc11')):
            raise GameCrashed('The game crashed (video-card error). The run is saved; no further inputs sent.')
        expected_settings_save = (getattr(self, '_settings_save_expected', False) and
                                  'unsaved changes' in text and
                                  'save and continue' in text and
                                  'cancel' in text)
        if (any(phrase in text for phrase in danger)
                and screen not in {'car_action', 'remove_confirmation'}
                and not expected_settings_save):
            raise RuntimeError('Unexpected dialog or insufficient resources. See the saved screenshot.')
        return self.last

    def recover_disconnect(self, timeout=45):
        """Enter Horizon Solo from the exact disconnect flow, with fresh visual proof."""
        deadline = time.monotonic() + timeout
        diagnostics_stable = 0
        clear_stable = 0
        last = None
        returned_to_roam = False
        opened_diagnostics = False
        selected_solo = False
        while time.monotonic() < deadline:
            self.check()
            obs = self.observe_sync(allow_disconnect=True)
            if obs.screen == 'network_disconnected':
                text = normalize(' '.join(line.text for line in obs.doc.lines))
                if 'return to freeroam to accept' in text:
                    if not returned_to_roam:
                        self.emit('log', 'Network recovery: returning to freeroam before opening diagnostics.')
                        self.key('esc')
                        self.pause(.35)
                        returned_to_roam = True
                    diagnostics_stable = clear_stable = 0
                    last = None
                    continue
                if 'view network diagnostics' in text:
                    if not opened_diagnostics:
                        self.emit('log', 'Network recovery: opening the verified FH6 diagnostics prompt.')
                        self.key('enter')
                        self.pause(.35)
                        opened_diagnostics = True
                    diagnostics_stable = clear_stable = 0
                    last = None
                    continue
                raise RuntimeError('Network alert changed; no recovery input sent')
            if obs.screen == 'network_diagnostics':
                matches = obs.doc.find('Horizon Solo', (550, 500, 820, 160), contains=True)
                focused = len(matches) == 1 and label_focused(obs.frame, matches[0])
                diagnostics_stable = diagnostics_stable + 1 if focused and last == obs.screen else int(focused)
                clear_stable = 0
                last = obs.screen
                if diagnostics_stable >= 2 and not selected_solo:
                    self.emit('log', 'Network recovery: Horizon Solo verified on two fresh frames; selecting once.')
                    self.key('enter')
                    self.pause(.5)
                    selected_solo = True
                    diagnostics_stable = 0
                    last = None
                continue
            diagnostics_stable = 0
            clear_stable = clear_stable + 1 if obs.screen == last and obs.screen != 'unknown' else int(obs.screen != 'unknown')
            last = obs.screen
            if clear_stable >= 2:
                self.emit('log', f'Network recovery complete on verified {obs.screen}.')
                return obs
            self.pause(.08)
        raise NetworkDisconnected('FH6 network diagnostics did not reach a stable game screen')

    def wait(self, screens, previous=(), predicate=None, timeout=None, stable_frames=2):
        screens = {screens} if isinstance(screens, str) else set(screens)
        previous = {previous} if isinstance(previous, str) else set(previous)
        if stable_frames not in {1, 2}:
            raise ValueError('A screen wait needs one or two stable frames')
        # Reuse only the immediately preceding two-frame menu proof, before
        # another input/capture and within 80 ms. The collection grid is a
        # reversible navigation menu; purchase_once independently rechecks the
        # card before spending. Predicates, offers, receipts and mastery always
        # take fresh observations. Sync/focus are checked again.
        ready = self._ready
        safe = {'campaign', 'cars', 'home_tab', 'upgrades', 'journal', 'discover',
                'garage_grid', 'garage_filter', 'sort_selection', 'recent_jump',
                'manufacturers', 'settings', 'collection_grid', 'car_action'}
        if self.fast_navigation and stable_frames == 2 and predicate is None and ready is not None:
            obs, stamp = ready
            try:
                self.check()
            except Exception:
                self.invalidate_ready()
                raise
            if self._ready is ready and time.monotonic()-stamp <= .08 and obs.screen in screens & safe:
                return obs
        check_predicate = predicate or (lambda o: True)
        end, stable, last = time.monotonic()+(timeout or self.timeout), 0, None
        while time.monotonic() < end:
            observation_started = time.monotonic()
            obs = self.observe()
            if obs.screen not in screens | previous | {'unknown'}:
                raise RuntimeError(f'Expected {", ".join(sorted(screens))}; found {obs.screen}')
            good = obs.screen in screens and check_predicate(obs)
            stable = stable+1 if good and obs.screen == last else int(good)
            last = obs.screen
            if stable >= stable_frames:
                self.probe('finish')
                self.emit('screen', obs.screen)
                # A one-frame handoff is used only between reversible menus.
                # It is never cached as the normal two-frame menu proof.
                self._ready = (obs, time.monotonic()) if stable_frames == 2 else None
                return obs
            self.pause(navigation_poll_delay(time.monotonic()-observation_started, self.fast_navigation))
        raise RuntimeError(f'Timed out waiting for {", ".join(sorted(screens))}; no input retry')

    def key(self, key, *, hold_seconds=.06):
        import pyautogui
        if hold_seconds != .06 and (key not in {'backspace', 'delete', *'0123456789'}
                or not .03 <= hold_seconds <= .06):
            raise ValueError('Short key holds are limited to numeric text editing')
        self.invalidate_ready()
        if key == 'y':
            self.garage_filters_clear = False
        self.emit('log', f'Key: {key}')
        self.check()
        try:
            self.probe('input',key)
            pyautogui.keyDown(key)
            self.pause(hold_seconds)
        finally:
            pyautogui.keyUp(key)

    def click_label(self, screen, label, region=None, contains=False):
        import pyautogui
        self.check()
        safe_lists = {'campaign', 'cars', 'upgrades', 'manufacturers', 'sort_selection', 'recent_jump', 'car_action', 'paints', 'journal', 'discover', 'settings', 'pause_menu', 'eventlab', 'challenge_search'}
        expected = {screen} if isinstance(screen, str) else set(screen)
        home_pointer = (expected <= {'campaign', 'cars', 'home_tab'} and region == TABS)
        # These specific entries passed bounded live checks. Pointer selection
        # avoids stepping through every row, while retaining all stability and
        # focus checks below. Other menus keep the verified keyboard route.
        pointer_entry = (
            expected == {'upgrades'} and label == 'Car Mastery' and region == LEFT or
            expected == {'sort_selection'} and label == 'Recently Added' and region is None or
            # Fast mode uses verified arrows here: the live manufacturer
            # picker sometimes activates its old focus when clicked quickly.
            not self.fast_navigation and expected == {'manufacturers'} and label == 'Mazda' and region == (250, 255, 1410, 650)
        )
        if self.prefer_keyboard and expected <= safe_lists and region != TABS and not pointer_entry:
            return self.keyboard_select(expected, label, region, contains)
        # The game's large pointer can completely hide a short tab such as CARS.
        self.invalidate_ready()
        pyautogui.moveTo(self.monitor['left']+1810, self.monitor['top']+970)
        previous_box = None

        def settled(obs):
            nonlocal previous_box
            if home_pointer and not complete_home_tab_row(obs):
                previous_box = None
                return False
            matches = obs.doc.find(label, region, contains)
            box = matches[0].box if len(matches) == 1 else None
            stable = box is not None and previous_box is not None and \
                all(abs(a-b) <= 3 for a, b in zip(box, previous_box))
            previous_box = box
            return stable

        # Menu text can be readable while rows are still sliding into place.
        # wait requires two successful checks, hence three matching positions.
        proof_deadline = time.monotonic()+.7 if home_pointer else None
        for _ in range(3):
            proof_remaining = proof_deadline-time.monotonic() if home_pointer else None
            if home_pointer and proof_remaining <= 0:
                raise RuntimeError('Timed out waiting for home tab proof; no input retry')
            obs = self.wait(screen, predicate=settled, timeout=proof_remaining)
            target = obs.doc.unique(label, region, contains)
            x, y = target.center
            if home_pointer:
                # Inside the visible tab, below its caption. The pointer can
                # otherwise hide the short CARS label during post-hover OCR.
                y = 190
            self.check()
            pyautogui.moveTo(self.monitor['left']+x, self.monitor['top']+y, duration=.04 if self.fast_navigation else .12)
            current = self.observe()
            if home_pointer and time.monotonic() >= proof_deadline:
                raise RuntimeError('Timed out waiting for home tab proof; no input retry')
            matches = current.doc.find(label, region, contains)
            if current.screen == obs.screen and len(matches) == 1 and \
                    all(abs(a-b) <= 3 for a, b in zip(target.box, matches[0].box)) and \
                    (not home_pointer or complete_home_tab_row(current)):
                # Existing three-position proof and fresh post-hover target are
                # unchanged. Only a reversible sort action may use this shortcut.
                if (self.fast_navigation and expected == {'sort_selection'} and
                        label == 'Recently Added' and region is None and
                        pointer_target_focused(current, matches[0])):
                    confirm = self.observe()
                    confirmed = confirm.doc.find(label, region, contains)
                    if not (confirm.screen == current.screen and len(confirmed) == 1 and
                            all(abs(a-b) <= 3 for a, b in zip(target.box, confirmed[0].box))):
                        previous_box = None
                        continue  # Re-establish positions; the outer retry is bounded.
                    if pointer_target_focused(confirm, confirmed[0]):
                        self.emit('log', 'Recently Added pointer target already focused on two fresh frames; activate once.')
                        self.key('enter')
                        self.check()
                        pyautogui.moveTo(self.monitor['left']+1810, self.monitor['top']+970)
                        return
                    # Same target but focus changed: retain the original click path.
                break
            previous_box = None
        else:
            raise RuntimeError(f'{label} kept moving; no click sent')
        self.emit('log', f'Select {label} on {obs.screen} at {x}, {y}')
        self.check()
        try:
            self.probe('input','click '+label)
            pyautogui.mouseDown()
            self.pause(.06)
        finally:
            pyautogui.mouseUp()
        # Park outside text so the cursor cannot obscure the next OCR scan.
        self.check()
        pyautogui.moveTo(self.monitor['left']+1810, self.monitor['top']+970)
        # Some tiles use the first click to focus only. Enter is allowed once,
        # only if the same screen and the exact target's focus border persist.
        self.pause(.12 if self.fast_navigation else .5)
        after = self.observe()
        # Tabs activate on click. Enter here could activate the focused body
        # tile, so their bounded caller alone reconciles any missed click.
        if not home_pointer and after.screen == obs.screen:
            matches = after.doc.find(label, region, contains)
            if len(matches) == 1 and label_focused(after.frame, matches[0]):
                self.pause(.25)
                after = self.observe()
                matches = after.doc.find(label, region, contains)
                if after.screen == obs.screen and len(matches) == 1 and label_focused(after.frame, matches[0]):
                    self.key('enter')
            elif (self.fast_navigation and expected == {'upgrades'} and
                    label == 'Car Mastery' and region == LEFT):
                self.recover_mastery_pointer_noop(after, target)

    def recover_mastery_pointer_noop(self, initial, target):
        """Use keyboard navigation only after a stable, proven no-op click."""
        if mastery_pointer_other_focus(initial, target) is None:
            return
        self.pause(.5)
        previous = None
        for index in range(2):
            current = self.observe()
            if current.screen not in {'upgrades', 'car_mastery', 'mad_mike_mastery', 'unknown'}:
                raise RuntimeError(f'Unexpected screen after Car Mastery click: {current.screen}')
            proof = mastery_pointer_other_focus(current, target)
            if proof is None:
                return  # A transition or uncertain focus cannot authorize input.
            if previous is not None and (proof[0] != previous[0] or
                    any(abs(a-b) > 3 for a, b in zip(proof[1], previous[1]))):
                return
            previous = proof
            if index == 0:
                self.pause(.04)
        self.check()
        self.emit('log', 'Car Mastery click left another upgrade row focused on two fresh frames; using verified keyboard navigation.')
        self.keyboard_select({'upgrades'}, 'Car Mastery', LEFT)

    def settle_keyboard_focus(self, screens, label, region=None, contains=False):
        """Wait briefly for a fading focus border without sending any input."""
        expected = {screens} if isinstance(screens, str) else set(screens)
        end = time.monotonic()+.8
        previous = None
        while time.monotonic() < end:
            obs = self.observe()  # Includes full sync, focus, F7 and dialog guards.
            if obs.screen not in expected | {'unknown'}:
                raise RuntimeError(f'Expected {", ".join(sorted(expected))}; found {obs.screen}')
            if time.monotonic() >= end:
                break
            targets = obs.doc.find(label, region, contains)
            boxes = focus_boxes(obs.frame) if obs.screen in expected and focus_settling_allowed(obs.screen, label) else []
            if len(targets) == 1 and len(boxes) == 1:
                proof = (obs.screen, boxes[0], targets[0].box)
                if (previous is not None and proof[0] == previous[0] and
                        all(abs(a-b) <= 3 for a, b in zip(proof[1], previous[1])) and
                        all(abs(a-b) <= 3 for a, b in zip(proof[2], previous[2]))):
                    self.emit('log', f'Keyboard focus settled on two fresh frames: {label}')
                    return obs, boxes
                previous = proof
            else:
                previous = None
            self.pause(min(.04, max(0., end-time.monotonic())))
        raise RuntimeError(f'Could not identify keyboard focus for {label} after bounded focus settling')

    def keyboard_select(self, screens, label, region=None, contains=False):
        if self.fast_navigation:
            obs = self.wait(screens)
            if len(obs.doc.find(label, region, contains)) != 1:
                # Only park the cursor when it actually obscures the label.
                import pyautogui
                self.invalidate_ready()
                self.check()
                pyautogui.moveTo(self.monitor['left']+1810, self.monitor['top']+970)
                obs = self.wait(screens, predicate=lambda o: len(o.doc.find(label,region,contains)) == 1)
        else:
            import pyautogui
            self.check()
            pyautogui.moveTo(self.monitor['left']+1810, self.monitor['top']+970)
            obs=self.wait(screens, predicate=lambda o: len(o.doc.find(label,region,contains)) == 1)
        focus_grace_used = False
        for _ in range(28):
            target=obs.doc.unique(label,region,contains)
            boxes=focus_boxes(obs.frame)
            if len(boxes) != 1:
                if not self.fast_navigation or focus_grace_used or not focus_settling_allowed(obs.screen, label):
                    raise RuntimeError(f'Could not identify keyboard focus for {label}')
                focus_grace_used = True
                obs, boxes = self.settle_keyboard_focus(screens, label, region, contains)
                target = obs.doc.unique(label, region, contains)
            tx,ty=target.center
            for x,y,w,h in boxes:
                if x <= tx <= x+w and y <= ty <= y+h:
                    self.emit('log', f'Keyboard focus verified: {label}')
                    self.key('enter')
                    return
            x,y,w,h=boxes[0]
            key='left' if tx < x else 'right' if tx > x+w else 'up' if ty < y else 'down'
            # The live client does not wrap Up from Custom Upgrade to Mastery.
            # Follow the observed target direction without probing that dead end.
            count=manufacturer_steps(obs,boxes[0],target) if (
                self.fast_navigation and (obs.screen=='manufacturers' or
                    obs.screen=='upgrades' and label=='Car Mastery') and key in {'up','down'}) else 1
            if count>1:
                self.emit('log',f'{obs.screen} navigation: {count} verified visible rows {key}.')
            for _ in range(count):
                self.key(key)
                self.pause(.04 if self.fast_navigation else .2)
            obs=self.wait(screens, predicate=lambda o: len(o.doc.find(label,region,contains)) == 1)
        raise RuntimeError(f'Keyboard navigation did not reach {label}; no selection sent')

    def back_home(self):
        allowed = {'collection_grid', 'discover', 'journal', 'paints', 'garage_grid', 'car_select',
                   'upgrades', 'mad_mike_mastery', 'car_mastery', 'cars', 'campaign', 'home_tab', 'showroom'}
        obs = self.wait(allowed)
        for _ in range(8):
            if obs.screen in {'campaign', 'cars', 'home_tab'}:
                return obs
            previous = obs.screen
            self.key('esc')
            transitional = {previous, 'car_mastery'} if previous == 'mad_mike_mastery' else {previous}
            if self.fast_navigation:
                try:
                    # Esc is reversible.  Detect a dropped pulse promptly
                    # instead of spending the global 30-second timeout on the
                    # unchanged menu.
                    obs = self.wait(allowed-{previous}, previous=transitional,
                                    timeout=1.0,
                                    # Upgrades paints before it accepts Back.
                                    # One extra observed frame here is cheaper
                                    # than the dropped Esc seen every cycle.
                                    stable_frames=2 if previous == 'car_mastery' else 1)
                except RuntimeError as exc:
                    if (not str(exc).startswith('Timed out waiting for ') or
                            self.last is None or self.last.screen != previous):
                        raise
                    self.emit('log', f'{previous}: unchanged after Esc; retrying one reversible Back pulse.')
                    self.key('esc')
                    obs = self.wait(allowed-{previous}, previous=transitional,
                                    stable_frames=1)
            else:
                obs = self.wait(allowed-{previous}, previous=transitional,
                                stable_frames=2)
        raise RuntimeError('Home menu was not reached within eight verified transitions')

    def wait_home_tab_transition(self, before):
        """Two fresh equal changed-tab observations; no input during animation."""
        previous = None
        require_change = True

        def changed(obs):
            nonlocal previous
            active = active_home_tab(obs)
            valid = active is not None and (not require_change or active != before)
            same = valid and previous is not None and previous == active
            previous = active if valid else None
            return same

        screens = {'campaign', 'cars', 'home_tab'}
        try:
            # `changed` already requires two equal active-tab readings.
            return self.wait(screens, predicate=changed, timeout=2, stable_frames=1)
        except RuntimeError as exc:
            if not str(exc).startswith('Timed out waiting for '):
                raise
            # A dropped reversible pulse may be retried only after fresh proof
            # of the actual known tab. Sync/F7 and unexpected screens propagate.
            previous = None
            require_change = False
            return self.wait(screens, predicate=changed, timeout=2, stable_frames=1)

    def home_tab(self, tab):
        obs = self.back_home()
        if obs.screen == tab:
            return
        if self.prefer_keyboard:
            if self.fast_navigation:
                screens = {'campaign', 'cars', 'home_tab'}
                label = dict(HOME_TABS)[tab]
                if complete_home_tab_row(obs):
                    # The exact tab is a single reversible click. The shared
                    # pointer method re-proves the complete row and target on
                    # three settled positions plus a fresh post-hover frame.
                    try:
                        self.click_label(screens, label, TABS)
                        self.wait(tab, previous=screens, timeout=1.2,
                                  stable_frames=1 if self.fast_navigation else 2)
                        return
                    except RuntimeError as exc:
                        if not (str(exc).startswith('Timed out waiting for ') or
                                str(exc) == f'{label} kept moving; no click sent'):
                            raise
                        # A complete row can disappear while the home menu is
                        # animating. Optional pointer proof must never consume
                        # the global screen timeout. Reconcile the active tab
                        # twice before the existing one-pulse keyboard route.
                        previous_active = None
                        def known_home(current):
                            nonlocal previous_active
                            active = active_home_tab(current)
                            same = active is not None and (previous_active is None or active == previous_active)
                            previous_active = active
                            return same
                        obs = self.wait(screens, predicate=known_home, timeout=.7)
                order = [name for name, _ in HOME_TABS]
                for _ in range(6):
                    active = active_home_tab(obs)
                    if active is None:
                        raise RuntimeError('Home tab is ambiguous; no tab input sent')
                    if active == tab:
                        # The underline can settle before the body classifier.
                        # Never step away just because the fast budget ended.
                        self.wait(tab, previous=screens, timeout=2)
                        return
                    steps = (order.index(tab)-order.index(active)) % len(order)
                    backward = (order.index(active)-order.index(tab)) % len(order)
                    self.key('pgup' if backward < steps else 'pgdn')
                    obs = self.wait_home_tab_transition(active)
                    if obs.screen == tab:
                        return
                if active_home_tab(obs) == tab:
                    self.wait(tab, previous=screens, timeout=2)
                    return
                raise RuntimeError(f'Home tab {tab} did not respond within six verified inputs')
            # Verified on the current client: Page Down changes home tabs,
            # whereas pointer clicks can be ignored despite showing hover.
            for _ in range(6):
                self.key('pgdn')
                self.pause(.3)
                obs = self.wait({'campaign', 'cars', 'home_tab'})
                if obs.screen == tab:
                    return
            raise RuntimeError(f'Home tab {tab} did not respond to verified keyboard navigation')
        # The user's Page Up mapping did not move off Buy & Sell. Select the
        # visible target tab directly, then verify its menu, rather than count keys.
        label = {'campaign': 'CAMPAIGN', 'cars': 'CARS'}[tab]
        for attempt in range(3):
            self.click_label({'campaign', 'cars', 'home_tab'}, label, TABS)
            try:
                self.wait(tab, previous={'campaign', 'cars', 'home_tab'}, timeout=4)
                return
            except RuntimeError as exc:
                # Tabs sometimes consume the first click only to wake/focus.
                # Retry this reversible navigation only on the same home menu.
                if 'Timed out' not in str(exc) or attempt == 2:
                    raise
                current = self.observe()
                if current.screen not in {'campaign', 'cars', 'home_tab'}:
                    raise
                self.emit('log', f'{label} tab did not switch; retrying verified home navigation')

    def collection(self):
        # A resumed collection checkpoint can find the last car's Upgrades
        # or mastery screen. Back out of recognized reversible menus before
        # retrying the journal route; waiting for Home alone never gets there.
        recoverable = {'upgrades', 'mad_mike_mastery', 'showroom', 'paints', 'garage_grid', 'car_select'}
        obs = self.wait({'campaign', 'cars', 'home_tab', 'collection_grid', 'journal', 'discover'} | recoverable)
        if obs.screen in recoverable:
            self.emit('log', f'Resume collection from {obs.screen}: returning to Home.')
            obs = self.back_home()
        if obs.screen not in {'collection_grid', 'journal', 'discover'}:
            self.home_tab('campaign')
            self.click_label('campaign', 'Collection Journal', LEFT)
            obs = self.wait('journal', previous='campaign',
                            stable_frames=1 if self.fast_navigation else 2)
        if obs.screen == 'journal':
            self.click_label('journal', 'Master Explorer')
            obs = self.wait('discover', previous='journal',
                            stable_frames=1 if self.fast_navigation else 2)
        if obs.screen == 'discover':
            self.click_label('discover', 'Car Collection')
            obs = self.wait('collection_grid', previous='discover',
                            stable_frames=1 if self.fast_navigation else 2)
        if len(obs.result.get('mazda_candidates', [])) == 1:
            return
        if (self.fast_navigation and not obs.result.get('mazda_candidates') and
                visible_collection_target_hint(obs) and self.settle_visible_collection_target()):
            return
        self.key('backspace')
        obs = self.wait('manufacturers', previous='collection_grid')
        # The manufacturer list can start at a different scroll position.
        self.find_manufacturer(obs)
        self.click_label('manufacturers', 'Mazda', (250, 255, 1410, 650))
        self.wait('collection_grid', previous='manufacturers',
                  predicate=lambda o: len(o.result.get('mazda_candidates', [])) == 1)

    def settle_visible_collection_target(self):
        """Two fresh strict card matches within a bounded, input-free grace."""
        deadline = time.monotonic()+.45
        previous = None
        previous_observation = previous_frame = None
        stable = 0
        current = None
        fresh = False
        while time.monotonic() < deadline:
            current = self.observe()  # Full screen, sync, focus, F7 and dialog guards.
            if current.screen not in {'collection_grid', 'unknown'}:
                raise RuntimeError(f'Unexpected screen while waiting for visible Mazda: {current.screen}')
            candidates = current.result.get('mazda_candidates', [])
            frame = getattr(current, 'frame', None)
            fresh = (current is not previous_observation and frame is not None and
                     frame is not previous_frame)
            center = (tuple(candidates[0]['center']) if
                      fresh and current.screen == current.result.get('screen') == 'collection_grid' and
                      len(candidates) == 1 else None)
            stable = stable+1 if center is not None and center == previous else int(center is not None)
            previous = center
            previous_observation, previous_frame = current, frame
            if time.monotonic() >= deadline:
                break
            if stable >= 2:
                self.emit('log', 'Visible Mad Mike collection card settled on two fresh strict frames; skipping Manufacturers.')
                return True
            self.pause(min(.025, max(0., deadline-time.monotonic())))
        if current is None or current.screen != 'collection_grid' or not fresh:
            raise RuntimeError('Visible Mazda did not settle on a current collection grid; no navigation input sent')
        return False  # The last fresh frame still authorizes only the existing menu route.

    def find_manufacturer(self, obs):
        """Fall back to arrows when the client ignores wheel scrolling."""
        import pyautogui
        previous_names, unchanged, keyboard = None, 0, False
        for _ in range(40):
            if obs.doc.has('Mazda', (250, 255, 1410, 650)):
                return obs
            names = tuple(sorted(normalize(line.text) for line in obs.doc.lines
                                 if 250 <= line.center[0] <= 1660
                                 and 255 <= line.center[1] <= 905))
            unchanged = unchanged+1 if names and names == previous_names else 0
            previous_names = names
            if unchanged >= 2 and not keyboard:
                keyboard = True
                self.emit('log', 'Manufacturer scrolling made no progress; using verified keyboard navigation.')
            # The manufacturer grid is alphabetical. If its first visible
            # entry follows Mazda, move up; otherwise move down. Only Enter
            # after the separate exact-label/focus verification in collection.
            direction = 'up' if names and names[0] > normalize('Mazda') else 'down'
            if keyboard:
                self.key(direction)
                self.pause(.04 if self.fast_navigation else .2)
            else:
                self.check()
                pyautogui.moveTo(self.monitor['left']+1600, self.monitor['top']+650)
                self.check()
                pyautogui.scroll(3 if direction == 'up' else -3)
                self.pause(.3)
            obs = self.wait('manufacturers')
        raise RuntimeError('Mazda was not found in the manufacturer list')

    def paints(self):
        obs = self.wait({'collection_grid', 'cars', 'campaign', 'home_tab', 'paints', 'car_select'})
        if obs.screen not in {'paints', 'car_select'}:
            self.home_tab('cars')
            self.click_label('cars', 'Designs & Paints', LEFT)
            # Designs & Paints may first ask which car to edit. The actual
            # screen is titled Car Select, not My Cars or Choose Car.
            self.wait({'paints', 'car_select'}, previous='cars')

    def my_cars(self):
        self.home_tab('cars')
        # click_label performs its own fresh Cars-menu/focus proof. Repeating
        # that wait here costs a capture and can reject a harmless fade frame.
        self.click_label('cars', 'My Cars', LEFT)
        # During the opening animation the row labels fade before the home
        # tabs do. This is still the previous menu, not a new input target.
        return self.wait('garage_grid', previous={'cars', 'home_tab'})

    def choose_car(self):
        obs = self.wait({'paints', 'car_select', 'garage_grid', 'garage_filter', 'cars', 'campaign', 'home_tab', 'collection_grid', 'sort_selection', 'recent_jump'})
        if obs.screen in {'sort_selection', 'recent_jump'}:
            previous = obs.screen
            self.key('esc')
            obs = self.wait('garage_grid', previous=previous)
        if obs.screen not in {'garage_grid', 'garage_filter'}:
            obs = self.my_cars()
        obs = set_favorites(self, False)
        grid = 'garage_grid'
        # A successful sort selection persists between My Cars visits. Reuse
        # that session proof when footer OCR is absent, but never when the
        # current footer contradicts it.
        on_screen = recent_sort_verified(obs)
        retained = (self.garage_recent_sort_verified and obs.screen == 'garage_grid'
                    and recent_sort_on_grid(obs.doc, calibrated=True))
        if self.fast_navigation and (on_screen or retained):
            self.garage_recent_sort_verified = True
            self.emit('log', 'Recently Added remains verified; skipping the sort dialog.')
        else:
            self.emit('log', 'Garage sort: Recently Added footer not proved; verifying through the sort dialog.')
            self.key('x')
            obs = self.wait('sort_selection', previous=grid)
            if not obs.doc.has('Recently Added'):
                raise RuntimeError('My Cars does not show Recently Added; no car was selected')
            # A sort-menu pointer click has silently failed in production;
            # verified arrows and focus proof avoid a 30-second no-op wait.
            self.keyboard_select('sort_selection', 'Recently Added')
            obs = self.wait({'garage_grid', 'car_select'}, previous='sort_selection',
                      predicate=recent_sort_verified)
            self.garage_recent_sort_verified = True
        grid = obs.screen
        self.key('backspace')
        self.pause(.04 if self.fast_navigation else .5)
        obs = self.wait({grid, 'recent_jump'})
        if obs.screen == 'recent_jump':
            self.click_label('recent_jump', 'All Cars', (250, 250, 1410, 650))
            obs = self.wait(grid, previous='recent_jump')
        self.enter_fresh_car(obs)

    def selected_car_observation(self, obs, require_new=True):
        try:
            return obs, selected_card(obs.frame), None
        except SelectedCardError as exc:
            exc.failed_observation = obs
            original = exc
            retained_sort = (recent_sort_verified(obs) or
                self.garage_recent_sort_verified and obs.screen == 'garage_grid'
                and recent_sort_on_grid(obs.doc, calibrated=True))
            if (exc.matches != 0 or not require_new or obs.screen != 'garage_grid'
                    or not retained_sort
                    or len(obs.doc.find('All Cars', (425,145,310,65))) != 1):
                raise
        # The grid caption may settle before its lime card border. This grace
        # sends no input and is used only after an otherwise safe zero match.
        started = time.monotonic()
        end = started + .8
        generation = self.focus_generation
        previous, previous_box, stable = obs, None, 0
        while time.monotonic() < end:
            self.pause(min(.02, max(0, end-time.monotonic())))
            if time.monotonic() >= end:
                break
            fresh = self.observe()  # Includes full dialog/sync/F7/focus checks.
            if (fresh is previous or fresh.frame is previous.frame
                    or self.focus_generation != generation):
                raise original
            previous = fresh
            retained_sort = (recent_sort_verified(fresh) or
                self.garage_recent_sort_verified and fresh.screen == 'garage_grid'
                and recent_sort_on_grid(fresh.doc, calibrated=True))
            if (fresh.screen != 'garage_grid' or not retained_sort
                    or len(fresh.doc.find('All Cars', (425,145,310,65))) != 1):
                error = RuntimeError('Garage changed while waiting for the selected car border; no car entered')
                error.failed_observation = fresh
                raise error
            if time.monotonic() >= end:
                break
            try:
                box = selected_card(fresh.frame)
            except SelectedCardError as exc:
                exc.failed_observation = fresh
                if exc.matches != 0:
                    raise
                stable, previous_box = 0, None
                continue
            card = self.reader.read(core.crop(fresh.frame, box))
            if not fresh_mazda_card(card):
                error = RuntimeError('Recently Added did not select an untouched Mad Mike Mazda; stopped before entering it')
                error.failed_observation = fresh
                raise error
            stable = stable+1 if box == previous_box else 1
            previous_box = box
            if stable >= 2 and time.monotonic() <= end:
                self.check()
                if self.focus_generation != generation or time.monotonic() > end:
                    raise original
                self.emit('log', f'Selected car border settled in {time.monotonic()-started:.3f}s; two fresh Mazda checks passed.')
                return fresh, box, card
        original.args = (str(original)+'; focus did not settle within 0.8s (no car entered)',)
        raise original

    def enter_fresh_car(self, obs, require_new=True):
        obs, box, card = self.selected_car_observation(obs, require_new)
        grid = obs.screen
        # Read the card alone: a NEW label on another duplicate cannot pass.
        if card is None:
            card = self.reader.read(core.crop(obs.frame, box))
        valid = fresh_mazda_card(card) if require_new else (card.has('MAD MIKE 808', contains=True) and card.has('1974 MAZDA', contains=True))
        if not valid:
            error = RuntimeError('Recently Added did not select an untouched Mad Mike Mazda; stopped before entering it')
            error.failed_observation = obs
            raise error
        self.emit('log', 'Selected an untouched Mazda through Recently Added; fresh mastery will be checked next.')
        self.key('enter')
        obs = self.wait({'car_action', 'paints', 'cars', 'showroom'}, previous=grid,
                        stable_frames=1 if self.fast_navigation else 2)
        if obs.screen == 'car_action':
            trace_request=core.BASE/'runs/trace_car_entry.request'
            if trace_request.exists():
                from .entry_trace import EntryTrace
                trace_request.unlink()
                self.entry_trace=EntryTrace(core.BASE/'runs/entry_traces')
            try:
                self.car_entry_active=True
                self.click_label('car_action', 'Get In Car')
                obs = self.wait_entered_car()
            finally:
                self.car_entry_active=False
                trace=getattr(self,'entry_trace',None)
                self.entry_trace=None
                if trace:
                    self.emit('log',f'Car-entry diagnostic: {trace.finish()}')
        if obs.screen == 'showroom':
            self.key('esc')
            self.wait({'cars', 'campaign', 'home_tab'}, previous='showroom')

    def pending_car_identity(self, obs):
        """Recovery-only proof; current-car text alone never identifies a copy."""
        from .current_car import current_first_card
        if (obs.screen != 'garage_grid' or not recent_sort_verified(obs) or
                not obs.doc.has('All Cars', (425, 145, 310, 65))):
            return None
        try:
            box = selected_card(obs.frame)
        except RuntimeError:
            return None
        if any(abs(a-b) > 3 for a, b in zip(box, (399, 204, 341, 260))):
            return None
        card = self.reader.read(core.crop(obs.frame, box))
        # The selected caption scrolls. Wait for its full model name instead
        # of accepting a clipped fragment or the unrelated current-car header.
        if not (card.has('MAD MIKE 808', contains=True) and
                card.has('1974 MAZDA', contains=True)):
            return None
        if card.has('NEW'):
            return 'new'
        if current_first_card(obs.frame, box):
            return 'current'
        return None

    def verify_pending_mastery(self, obs, expected_sp):
        """Read one fresh frame; the caller requires two consecutive proofs."""
        nodes = obs.result.get('nodes', {})
        if (obs.screen != 'mad_mike_mastery' or
                set(nodes) != {node[0] for node in core.NODES} or
                any(node.get('state') not in {'available', 'unavailable'}
                    for node in nodes.values()) or
                nodes['Head-Turner']['state'] != 'available'):
            raise RuntimeError('Pending Mazda does not have all six untouched mastery nodes; no points spent')
        if read_points(self.reader, obs.frame) != expected_sp:
            raise RuntimeError('Pending Mazda SP differs from its saved unspent balance; no points spent')
        return True

    def recover_pending_car(self, expected_sp):
        """Re-prove a funded pending copy without purchasing or claiming nodes.

        Called only after the restart ledger/funding checks. A car entered just
        before a crash has lost NEW; it must instead be both the first freshly
        sorted copy and the uniquely CURRENT copy, with an untouched tree.
        """
        if type(expected_sp) is not int or not 21 <= expected_sp <= 999:
            raise RuntimeError('No valid saved unspent SP for pending-car recovery')
        self.my_cars()
        self.garage_filters_clear = False
        set_favorites(self, False)
        # Recovery deliberately resets each premise, independent of the normal
        # conversion route's already-verified menu shortcuts.
        self.key('x')
        obs = self.wait('sort_selection', previous='garage_grid')
        if not obs.doc.has('Recently Added'):
            raise RuntimeError('Recently Added sort is not visible; pending copy not selected')
        self.click_label('sort_selection', 'Recently Added')
        self.wait('garage_grid', previous='sort_selection', predicate=recent_sort_verified)
        self.key('backspace')
        self.wait('recent_jump', previous='garage_grid')
        self.click_label('recent_jump', 'All Cars', (250, 250, 1410, 650))
        identity = None

        def same_identity(frame):
            nonlocal identity
            current = self.pending_car_identity(frame)
            settled = current is not None and (identity is None or current == identity)
            identity = current
            return settled

        obs = self.wait('garage_grid', previous='recent_jump', predicate=same_identity)
        if identity == 'new':
            self.enter_fresh_car(obs)  # Normal NEW requirement is unchanged.
        elif identity == 'current':
            # Escape closes My Cars; no Enter/Get In Car and no duplicate scan.
            self.key('esc')
            self.wait({'cars', 'campaign', 'home_tab'}, previous='garage_grid')
        else:
            raise RuntimeError('Pending copy identity could not be established')
        self.open_mastery()
        self.wait('mad_mike_mastery',
                  predicate=lambda frame: self.verify_pending_mastery(frame, expected_sp))
        self.check()
        return identity

    def wait_entered_car(self):
        # A live early-Escape experiment did not shorten the first-entry
        # animation. Wait for the actual menu; avoid an ineffective extra key.
        return self.wait({'paints','cars','showroom'}, previous='car_action')

    def recover_recent_mazda(self):
        """Find the newest Mazda after other cars were added; never spend SP here."""
        import pyautogui
        obs = self.wait('garage_grid', predicate=lambda o: o.doc.has('Jump to Recently Added', contains=True))
        for _ in range(40):
            labels = sorted(obs.doc.find('1974 MAZDA', (400, 210, 1500, 750)), key=lambda l:(l.center[0],l.center[1]))
            for label in labels:
                x,y = label.center
                if not obs.doc.has('MAD MIKE', (max(400,x-180),y-60,350,55), contains=True):
                    continue
                self.check()
                pyautogui.moveTo(self.monitor['left']+x, self.monitor['top']+y+70)
                try:
                    pyautogui.mouseDown()
                    self.pause(.06)
                finally:
                    pyautogui.mouseUp()
                pyautogui.moveTo(self.monitor['left']+1810,self.monitor['top']+970)
                self.pause(.3)
                chosen = self.wait('garage_grid')
                self.enter_fresh_car(chosen, require_new=False)
                tree = self.open_mastery()
                self.verify_fresh_mastery(tree)
                return
            self.key('right')
            self.pause(.2)
            obs = self.wait('garage_grid')
        raise RuntimeError('No recent Mad Mike Mazda was found; no car bought or mastery claimed')

    def open_mastery(self):
        obs = self.wait({'paints', 'cars', 'campaign', 'home_tab', 'upgrades', 'mad_mike_mastery', 'showroom'})
        if obs.screen == 'mad_mike_mastery':
            return obs
        if obs.screen != 'upgrades':
            self.home_tab('cars')
            self.click_label('cars', 'Upgrades & Tuning', LEFT)
            self.wait('upgrades', previous='cars',
                      stable_frames=1 if self.fast_navigation else 2)
        self.click_label('upgrades', 'Car Mastery', LEFT)
        # The generic heading appears before the model/title animation settles.
        # It is a waiting state only; claiming still requires the calibrated Mazda.
        return self.wait('mad_mike_mastery', previous={'upgrades', 'car_mastery'})

    def verify_fresh_mastery(self, obs, verified_points=None):
        nodes = obs.result.get('nodes', {})
        if len(nodes) != 6 or any(n['state'] in {'owned', 'unknown'} for n in nodes.values()):
            raise RuntimeError('This Mazda does not have a fresh mastery path; no points spent')
        if nodes['Head-Turner']['state'] != 'available':
            raise RuntimeError('The first mastery node is unavailable')
        if verified_points is None:
            if read_points(self.reader, obs.frame) < 21:
                raise RuntimeError('At least 21 skill points are needed; no mastery inputs sent')
        elif type(verified_points) is not int or verified_points < 21:
            raise RuntimeError('Saved Cars-tab SP proof does not cover this mastery claim')
