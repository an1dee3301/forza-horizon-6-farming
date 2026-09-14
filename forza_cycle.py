"""Read-only recognition, single mastery, and verified purchase loops.

python forza_cycle.py --image screenshot.png
python forza_cycle.py --video "Recording 2026-09-07 231512.mp4"
python forza_cycle.py --live
python forza_cycle.py --mastery
python forza_cycle.py --purchase
python forza_cycle.py --purchase --count 10
python forza_cycle.py --purchase --count 0
python forza_cycle.py --locate-car
"""
import argparse
import ctypes
import json
import time
from datetime import datetime
from pathlib import Path
from threading import Event

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent
PROFILE = BASE / "recognition" / "profile.json"
NODES = [
    ("Head-Turner", 376, 590, 1),
    ("Dori-Kin", 492, 590, 1),
    ("Teamwork Makes The Dream Work", 608, 590, 1),
    ("Free Spirit", 608, 474, 3),
    ("Show Me Your Moves", 608, 358, 5),
    ("Spinball Wizard", 608, 242, 10),
]
CAPTION_BOX = (328, 661, 440, 36)
CAPTION_MIN_SCORE = .96
CAPTION_MIN_MARGIN = .02
PURCHASE_ASSETS = ('collection_mazda_image', 'collection_mazda_year',
                   'purchase_price', 'purchase_buy_selected', 'purchase_yes_selected',
                   'sort_recent_selected', 'recent_jump_hint')


def has_focus(frame, box):
    hsv = cv2.cvtColor(crop(frame, box), cv2.COLOR_BGR2HSV)
    h,s,v = cv2.split(hsv)
    lime = (h >= 20) & (h <= 45) & (s > 160) & (v > 190)
    bands = [lime[:12,:],lime[-12:,:],lime[:,:12],lime[:,-12:]]
    return all(float(band.mean()) > .08 for band in bands)


def price_matches(actual, expected):
    # Restrict the comparison to the price glyphs; a changed digit must not
    # be hidden by the much larger matching dialog background.
    a = cv2.cvtColor(actual,cv2.COLOR_BGR2GRAY) > 165
    b = cv2.cvtColor(expected,cv2.COLOR_BGR2GRAY) > 165
    union = np.logical_or(a,b).sum()
    return union > 50 and float(np.logical_and(a,b).sum()/union) >= .96


def crop(frame, box):
    x, y, w, h = box
    return frame[y:y+h, x:x+w]


def similarity(a, b):
    # Absolute color error retains the white/pink distinction that normalized
    # correlation can lose. No screen-wide search or resize is performed.
    if a.shape != b.shape or not a.size:
        return 0.0
    if a.dtype == np.uint8 and b.dtype == np.uint8 and a.ndim == 3 and a.shape[2] == 3:
        # Screens and calibration images are BGR bytes. Compute the same mean
        # absolute color error without allocating two float images per anchor.
        return 1.0 - sum(cv2.mean(cv2.absdiff(a, b))[:3]) / (3.0 * 255.0)
    return 1.0 - float(np.abs(a.astype(np.float32)-b.astype(np.float32)).mean()) / 255.0


def node_state(frame, x, y):
    # This 48px square remains within the node interior in both focus sizes.
    # The border and connecting lines are deliberately outside this region.
    interior = crop(frame, (x-24, y-24, 48, 48))
    hsv = cv2.cvtColor(interior, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    pink = float(((h >= 140) & (h <= 175) & (s >= 130) & (v >= 120)).mean())
    white = float(((s < 55) & (v > 205)).mean())
    dark = float((v < 95).mean())
    if pink > .30 and white < .65:
        state = "owned"
    elif pink < .04 and white > .30 and dark < .20:
        state = "available"
    elif pink < .04 and white < .10 and dark > .45:
        state = "unavailable"
    else:
        state = "unknown"
    return {"state": state, "pink": round(pink, 3),
            "white": round(white, 3), "dark": round(dark, 3)}


class Recognizer:
    def __init__(self):
        self.profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.templates = {}
        for screen in self.profile["screens"]:
            for anchor in screen["anchors"]:
                path = PROFILE.parent / anchor["file"]
                template = cv2.imread(str(path))
                if template is None:
                    raise RuntimeError(f"Missing recognition template: {path}")
                self.templates[anchor["file"]] = template
        self.captions = []
        for index in range(len(NODES)):
            path = PROFILE.parent / f'node_caption_{index}.png'
            caption = cv2.imread(str(path))
            if caption is None:
                raise RuntimeError(f"Missing node selection caption: {path}")
            self.captions.append(caption)
        for name in PURCHASE_ASSETS:
            path = PROFILE.parent / f'{name}.png'
            template = cv2.imread(str(path))
            if template is None:
                raise RuntimeError(f'Missing purchase template: {path}')
            self.templates[name] = template

    def collection_car(self, frame):
        candidates = []
        for row,y in enumerate((220,470,720)):
            for column,x in enumerate((129,459,789,1119,1449)):
                picture = similarity(crop(frame,(x+11,y+9,304,170)),
                                     self.templates['collection_mazda_image'])
                year = similarity(crop(frame,(x+98,y+216,136,23)),
                                  self.templates['collection_mazda_year'])
                if picture >= .95 and year >= .96:
                    candidates.append({'row':row,'column':column,
                        'center':[x+163,y+122], 'image_score':round(picture,4),
                        'year_score':round(year,4),
                        'focused':has_focus(frame,(x-10,y-10,346,264))})
        return candidates

    def selection(self, frame):
        actual = crop(frame, CAPTION_BOX)
        scores = [similarity(actual, caption) for caption in self.captions]
        ranked = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
        best, second = ranked[:2]
        margin = scores[best] - scores[second]
        # Video compression changes text edges. A modest absolute tolerance
        # plus separation from every other caption also rejects blank bars
        # and ambiguous short names (Dori-Kin versus Free Spirit).
        accepted = scores[best] >= CAPTION_MIN_SCORE and margin >= CAPTION_MIN_MARGIN
        return {
            'name': NODES[best][0] if accepted else None,
            'best_candidate': NODES[best][0],
            'score': round(scores[best], 4),
            'margin': round(margin, 4),
            'scores': {node[0]: round(score, 4) for node, score in zip(NODES, scores)},
        }

    def inspect(self, frame):
        if frame is None:
            raise ValueError("Image could not be read")
        if frame.shape[:2] != (1080, 1920):
            return {"screen": "unknown", "reason": "Expected 1920 x 1080"}
        matches = []
        for screen in self.profile["screens"]:
            scores = [similarity(crop(frame, a["box"]), self.templates[a["file"]])
                      for a in screen["anchors"]]
            if all(s >= .965 for s in scores):
                matches.append((screen["name"], round(min(scores), 4)))
        result = {"screen": "unknown", "matches": matches,
                  "banking_verified": False, "purchased_copy_verified": False}
        if len(matches) != 1:
            result["reason"] = "No unique calibrated screen match"
            return result
        result["screen"], result["score"] = matches[0]
        if result['screen'] == 'collection_grid':
            result['mazda_candidates'] = self.collection_car(frame)
        elif result['screen'] == 'sort_selection':
            result['recently_added_selected'] = (
                has_focus(frame,(618,706,684,68)) and
                similarity(crop(frame,(865,728,200,22)),self.templates['sort_recent_selected']) >= .97)
        elif result['screen'] == 'garage_grid':
            result['recent_jump_available'] = similarity(
                crop(frame,(589,984,390,45)),self.templates['recent_jump_hint']) >= .965
        elif result['screen'] == 'car_action':
            result['get_in_selected'] = has_focus(frame,(618,438,684,58))
            result['remove_selected'] = has_focus(frame,(618,650,684,62))
        elif result['screen'] == 'remove_confirmation':
            result['no_selected'] = has_focus(frame,(618,543,684,56))
            result['yes_selected'] = has_focus(frame,(618,597,684,60))
        elif result['screen'] == 'autoshow_prompt':
            result['no_selected'] = has_focus(frame,(618,570,684,68))
            result['yes_selected'] = (
                has_focus(frame,(618,624,684,68)) and
                similarity(crop(frame,(630,640,659,35)),self.templates['purchase_yes_selected']) >= .97)
        elif result['screen'] == 'purchase_offer_95000':
            result['price_verified'] = bool(price_matches(
                crop(frame,(1080,509,94,27)),self.templates['purchase_price']))
            result['buy_selected'] = (
                has_focus(frame,(618,552,684,68)) and
                similarity(crop(frame,(630,565,659,35)),self.templates['purchase_buy_selected']) >= .97)
        if result["screen"] == "mad_mike_mastery":
            result['selection'] = self.selection(frame)
            result["nodes"] = {name: node_state(frame, x, y)
                               for name, x, y, cost in NODES}
            result["mastery_path_owned"] = all(
                n["state"] == "owned" for n in result["nodes"].values())
            result["reward_requirement_satisfied"] = (
                result["nodes"]["Spinball Wizard"]["state"] == "owned")
            result["reward_evidence"] = "Owned node accepted by user; saved-spin count not checked"
        return result


def inspect_video(recognizer, path, output):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        raise ValueError("Invalid video frame rate")
    index = 0
    previous = None
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("w", encoding="utf-8") as report:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                # Five observations per second, processing every video frame
                # sequentially to avoid seek inaccuracies at transitions.
                if index % max(1, round(fps/5)) == 0:
                    result = recognizer.inspect(frame)
                    states = {k: v["state"] for k, v in result.get("nodes", {}).items()}
                    signature = (result["screen"], tuple(states.items()))
                    if signature != previous:
                        row = {"seconds": round(index/fps, 3), **result}
                        report.write(json.dumps(row) + "\n")
                        print(f'{row["seconds"]:6.2f}s {result["screen"]} {states}')
                        previous = signature
                index += 1
    finally:
        cap.release()
    print(f"Read-only report: {output.resolve()}")


def foreground_title():
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    buf = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(user32.GetForegroundWindow(), buf, len(buf))
    return buf.value


class MasteryStopped(Exception):
    pass


def timing(running, method, *args):
    performance=getattr(running,'performance',None)
    if performance:
        performance.record_probe(method,*args)


def timed_sleep(running,seconds):
    start=time.perf_counter()
    try:
        time.sleep(seconds)
    finally:
        performance=getattr(running,'performance',None)
        if performance:
            performance.pacing_seconds+=time.perf_counter()-start


def timed_observation(running,capture,monitor,recognizer):
    performance=getattr(running,'performance',None)
    def measure(name,action):
        return performance.measure(name,action) if performance else action()
    frame=measure('capture',lambda:cv2.cvtColor(np.asarray(capture.grab(monitor)),cv2.COLOR_BGRA2BGR))
    result=measure('recognition',lambda:recognizer.inspect(frame))
    timing(running,'observe',frame,result['screen'])
    return frame,result


class PurchaseLedger:
    def __init__(self, directory=BASE / 'purchases'):
        self.directory = Path(directory)
        self.path = self.directory / 'latest.json'

    def ready(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('status') not in {'confirmed','resolved_bought','resolved_not_bought'}:
                raise RuntimeError('Previous purchase is uncertain. Inspect the game before '
                                   'using --resolve-purchase bought or not-bought.')

    def save(self, data):
        self.directory.mkdir(exist_ok=True,parents=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,indent=2),encoding='utf-8')
        temporary.replace(self.path)
        (self.directory / f"{data['id']}.json").write_text(json.dumps(data,indent=2),encoding='utf-8')

    def begin(self, frame):
        self.ready()
        data = {'id':datetime.now().strftime('%Y%m%d_%H%M%S_%f'),
                'status':'pending', 'price':95000, 'car':"1974 Mazda #123 Mad Mike 808 Wagon FURSTY"}
        # Persist intent before the only purchase keypress; survives shutdown.
        self.save(data)
        if not cv2.imwrite(str(self.directory / f"{data['id']}_before.png"),frame):
            raise RuntimeError('Could not save pre-purchase screenshot')

    def confirm(self, frame):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data['status'] != 'pending':
            raise RuntimeError('No pending purchase to confirm')
        if not cv2.imwrite(str(self.directory / f"{data['id']}_confirmed.png"),frame):
            raise RuntimeError('Could not save purchase confirmation screenshot')
        data['status'] = 'confirmed'
        self.save(data)

    def resolve(self, outcome):
        if not self.path.exists():
            raise RuntimeError('No purchase record to resolve')
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data['status'] != 'pending':
            raise RuntimeError('No uncertain purchase to resolve')
        data['status'] = 'resolved_' + outcome.replace('-','_')
        data['resolved_at'] = datetime.now().isoformat()
        self.save(data)
        print('Recorded your manual check. No game inputs were sent.')


def purchase_once(recognizer, capture, monitor, title, running, ledger, *, timeout=30, fast=False):
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0
    ledger.ready()
    poll = .05 if fast else .15

    def check():
        if not running.is_set():
            raise MasteryStopped('F7 stop requested')
        if getattr(running, 'input_guard', None):
            running.input_guard()
        if title.casefold() not in foreground_title().casefold():
            raise RuntimeError('Game focus lost')

    def observe():
        check()
        return timed_observation(running,capture,monitor,recognizer)

    def wait_screen(expected, predicate=lambda r:True, seconds=None, previous=None):
        seconds = timeout if seconds is None else seconds
        end, stable = time.monotonic()+seconds, 0
        while time.monotonic() < end:
            frame,result = observe()
            screen = result['screen']
            if screen not in {expected,'unknown',previous}:
                raise RuntimeError(f'Unexpected screen during purchase: {screen}')
            stable = stable+1 if screen == expected and predicate(result) else 0
            if stable >= 3:
                timing(running,'finish')
                return frame,result
            timed_sleep(running,poll)
        raise RuntimeError(f'Purchase stopped waiting for {expected}; no purchase retry')

    def hover(x,y):
        check()
        print(f'Move to {x}, {y}')
        pyautogui.moveTo(monitor['left']+x,monitor['top']+y,duration=.15)

    def press(key):
        check()
        try:
            timing(running,'input',key)
            pyautogui.keyDown(key)
            timed_sleep(running,.06)
        finally:
            pyautogui.keyUp(key)

    # F7 or a slow menu can leave the pre-purchase prompt open. It has no car
    # identity, so cancel it once and verify the collection card again. Never
    # accept an orphaned offer, and never bypass an uncertain purchase ledger.
    deadline, last, stable = time.monotonic()+timeout, None, 0
    dismissed = set()
    while time.monotonic() < deadline:
        _, initial = observe()
        screen = initial['screen']
        if screen not in {'collection_grid', 'collection_detail', 'autoshow_prompt',
                          'purchase_offer_95000', 'unknown'}:
            raise RuntimeError('Open Collection Journal > Car Collection with the Mazda card visible first')
        stable = stable+1 if screen == last else 1
        last = screen
        if stable >= 3 and screen == 'collection_grid':
            break
        if stable >= 3 and screen in {'autoshow_prompt', 'purchase_offer_95000', 'collection_detail'}:
            if screen not in dismissed:
                if screen == 'autoshow_prompt':
                    # This dialog only exposes Enter Select; Esc is ignored.
                    # Cancel via the verified No row before rechecking the car.
                    if not initial.get('no_selected'):
                        press('up')
                    wait_screen('autoshow_prompt', lambda r:r.get('no_selected', False))
                    press('enter')
                else:
                    press('esc')
                dismissed.add(screen)
                stable, last = 0, None
                print('Closed an unfinished purchase dialog; rechecking the Mazda card.')
        timed_sleep(running,poll)
    else:
        raise RuntimeError('Could not return to Car Collection before buying; no purchase sent')
    # The recovery loop has already verified three fresh collection frames.
    # Keep the final one; card identity/focus still gets its own three checks.
    result = initial if fast else wait_screen('collection_grid')[1]
    candidates = result['mazda_candidates']
    if len(candidates) != 1:
        raise RuntimeError('Expected exactly one visible Mad Mike Mazda collection card')
    target = candidates[0]
    def selected(r):
        cars = r['mazda_candidates']
        return len(cars) == 1 and cars[0]['center'] == target['center'] and cars[0]['focused']
    # Returning to this card often leaves the exact Mazda already focused.
    # Moving the pointer can briefly unsettle that focus and cause a needless
    # click into its details. Keep all three fresh selected checks below.
    if not (fast and selected(result)):
        hover(*target['center'])
        timed_sleep(running,.08 if fast else .5)
        _, current = observe()
        if current['screen'] == 'collection_grid' and not selected(current):
            # In keyboard mode, hovering may leave the previous manufacturer
            # selected. Click once; Space still requires independent proof.
            cars = current['mazda_candidates']
            if len(cars) != 1 or cars[0]['center'] != target['center']:
                raise RuntimeError('The Mazda card moved before selection; no purchase sent')
            check()
            try:
                pyautogui.mouseDown()
                timed_sleep(running,.1)
            finally:
                pyautogui.mouseUp()
    # A click can open the verified Mad Mike details card instead of merely
    # focusing its grid tile. Close it once; selection must still be verified.
    deadline, detail_closed, selected_stable = time.monotonic()+timeout, False, 0
    while time.monotonic() < deadline:
        _, current = observe()
        selected_stable = selected_stable+1 if current['screen'] == 'collection_grid' and selected(current) else 0
        if selected_stable >= 3:
            break
        if current['screen'] == 'collection_detail' and not detail_closed:
            wait_screen('collection_detail')
            press('esc')
            detail_closed = True
        elif current['screen'] not in {'collection_grid', 'collection_detail', 'unknown'}:
            raise RuntimeError('Unexpected screen while selecting the Mazda; no purchase sent')
        timed_sleep(running,poll)
    else:
        raise RuntimeError('Mazda selection did not stabilize; no purchase sent')
    press('space')
    _, prompt = wait_screen('autoshow_prompt',previous='collection_grid')
    if not fast:
        hover(960,655)
        _, prompt = wait_screen('autoshow_prompt')
    if not prompt['yes_selected']:
        if not fast:
            hover(1810,970)
        press('down')
    wait_screen('autoshow_prompt',lambda r:r['yes_selected'])
    press('enter')
    _, offer = wait_screen('purchase_offer_95000',lambda r:r['price_verified'],previous='autoshow_prompt')
    if not fast:
        hover(960,582)
        _, offer = wait_screen('purchase_offer_95000', lambda r:r['price_verified'])
    if not offer['buy_selected']:
        if not fast:
            hover(1810,970)
        press('up')
    frame,_ = wait_screen('purchase_offer_95000',lambda r:r['price_verified'] and r['buy_selected'])
    check()
    ledger.begin(frame)
    press('enter')
    hover(1810,970)
    print('Buy sent once. Waiting for the car-added confirmation.')
    frame,_ = wait_screen('purchase_success',previous='purchase_offer_95000')
    ledger.confirm(frame)
    print('PURCHASE COMPLETE: one Mazda bought for 95,000 CR.')


def return_to_collection(recognizer, capture, monitor, title, running, *, timeout=30, fast=False):
    """Dismiss a confirmed success once, then observe the collection grid."""
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0
    poll = .05 if fast else .15

    def check():
        if not running.is_set():
            raise MasteryStopped('F7 stop requested')
        if getattr(running, 'input_guard', None):
            running.input_guard()
        if title.casefold() not in foreground_title().casefold():
            raise RuntimeError('Game focus lost')

    deadline = time.monotonic()+timeout
    last, stable, dismissed = None, 0, False
    while time.monotonic() < deadline:
        check()
        frame = np.asarray(capture.grab(monitor))[:,:,:3].copy()
        result = recognizer.inspect(frame)
        screen = result['screen']
        if screen not in {'purchase_success','collection_grid','unknown'}:
            raise RuntimeError(f'Unexpected screen returning to collection: {screen}')
        stable = stable+1 if screen == last else 1
        last = screen
        if screen == 'collection_grid' and stable >= 3:
            return
        if screen == 'purchase_success' and stable >= 3 and not dismissed:
            check()
            # This acknowledges a previously verified purchase, never an offer.
            try:
                pyautogui.keyDown('enter')
                time.sleep(.06)
            finally:
                pyautogui.keyUp('enter')
            dismissed = True
            stable, last = 0, None
            deadline = time.monotonic()+timeout
        time.sleep(poll)
    raise RuntimeError('Collection grid did not return after purchase; stopped without another buy')


class PurchaseBatch:
    def __init__(self, limit=1):
        if not isinstance(limit,int) or isinstance(limit,bool) or limit < 0:
            raise ValueError('Purchase count must be a whole number, zero or greater')
        self.limit = limit  # Zero means continue until F7 or a failure.
        self.completed = 0
        self.needs_return = False

    def run(self, recognizer, capture, monitor, title, running, ledger):
        ledger.ready()
        while self.limit == 0 or self.completed < self.limit:
            if not running.is_set():
                raise MasteryStopped('F7 stop requested')
            if self.needs_return:
                return_to_collection(recognizer,capture,monitor,title,running)
                self.needs_return = False
            purchase_once(recognizer,capture,monitor,title,running,ledger)
            # Preserve progress even if F7 interrupts the return to the grid.
            self.completed += 1
            self.needs_return = True
            target = str(self.limit) if self.limit else 'continuous'
            print(f'BOUGHT {self.completed}/{target} | {self.completed * 95000:,} CR confirmed')
        if self.needs_return:
            return_to_collection(recognizer,capture,monitor,title,running)
            self.needs_return = False
        print(f'Purchase limit reached: {self.completed} cars. Returned to Car Collection.')


def locate_recent_car(recognizer, capture, monitor, title, running, directory=BASE/'garage_checks'):
    """Observe the Recently Added jump. Never enter, claim, or remove a car."""
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0

    def check():
        if not running.is_set():
            raise MasteryStopped('F7 stop requested')
        if getattr(running, 'input_guard', None):
            running.input_guard()
        if title.casefold() not in foreground_title().casefold():
            raise RuntimeError('Game focus lost')

    def wait_for(screen, predicate=lambda result:True, previous=None):
        deadline, stable = time.monotonic()+8, 0
        while time.monotonic() < deadline:
            check()
            frame = np.asarray(capture.grab(monitor))[:,:,:3].copy()
            result = recognizer.inspect(frame)
            if result['screen'] not in {screen,'unknown',previous}:
                raise RuntimeError(f'Unexpected garage menu: {result["screen"]}')
            stable = stable+1 if result['screen'] == screen and predicate(result) else 0
            if stable >= 3:
                return frame,result
            time.sleep(.15)
        raise RuntimeError(f'Garage lookup timed out waiting for {screen}')

    def press(key):
        check()
        try:
            pyautogui.keyDown(key)
            time.sleep(.06)
        finally:
            pyautogui.keyUp(key)

    before,_ = wait_for('garage_grid')
    press('x')
    wait_for('sort_selection',previous='garage_grid')
    check()
    pyautogui.moveTo(monitor['left']+960,monitor['top']+740,duration=.15)
    wait_for('sort_selection',lambda result:result['recently_added_selected'])
    press('enter')
    sorted_frame,_ = wait_for('garage_grid',lambda result:result['recent_jump_available'],
                            previous='sort_selection')
    press('backspace')
    # Let the jump start before requiring consecutive stable captures.
    time.sleep(.3)
    after,result = wait_for('garage_grid',lambda result:result['recent_jump_available'])
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    for label,frame in [('before',before),('sorted',sorted_frame),('after_jump',after)]:
        if not cv2.imwrite(str(directory/f'{stamp}_{label}.png'),frame):
            raise RuntimeError('Could not save garage lookup screenshot')
    report = {'status':'needs_local_selection_check',
              'purchased_copy_verified':False,
              'note':'Recently Added shortcut sent once; verify which duplicate is selected.',
              'recognition':result}
    (directory/f'{stamp}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'GARAGE LOOKUP COMPLETE: stopped on the selected car. Screenshots: {directory}')
    print('Purchased-copy identity is not yet verified. No car was entered or removed.')


def mastery_once(recognizer, capture, monitor, title, running, *, fast=True):
    """One claim per node, no retries after Enter and no navigation away."""
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0 if fast else .05
    poll = .05 if fast else .15
    observed_at = 0.0

    def check():
        if not running.is_set():
            raise MasteryStopped("F7 stop requested")
        if getattr(running, 'input_guard', None):
            running.input_guard()
        if title.casefold() not in foreground_title().casefold():
            raise RuntimeError("Game focus lost")

    def observe(allow_transition=False):
        nonlocal observed_at
        check()
        frame,result=timed_observation(running,capture,monitor,recognizer)
        observed_at = time.perf_counter()
        if result['screen'] != 'mad_mike_mastery' and not (
                allow_transition and result['screen'] == 'unknown'):
            raise RuntimeError("Expected the Mad Mike mastery screen; stopped")
        return frame, result

    def wait_state(name, allowed, seconds=8):
        end = time.monotonic() + seconds
        previous, count = None, 0
        while time.monotonic() < end:
            frame, result = observe(allow_transition=True)
            if result['screen'] == 'unknown':
                # Claim flashes can briefly obscure anchors. Wait without
                # inputs; a persistent dialog reaches the same timeout.
                previous, count = None, 0
                timed_sleep(running,poll)
                continue
            state = result['nodes'][name]['state']
            count = count+1 if state == previous else 1
            previous = state
            if state in allowed and count >= 3:
                timing(running,'finish')
                return frame, result
            check()
            timed_sleep(running,poll)
        raise RuntimeError(f"{name}: state did not stabilize; no Enter retry")

    check()
    pyautogui.moveTo(monitor['left']+1810, monitor['top']+970)
    # The first claim still needs 3 fresh selected/interior proofs after the
    # pointer moves. Those screen observations replace a fixed park delay.
    if not fast:
        timed_sleep(running,.2)
    for index, (name,x,y,cost) in enumerate(NODES):
        if fast:
            # Available nodes are still proven three times with the exact
            # selected caption immediately before Enter. Avoid duplicating
            # that wait before navigation; skipping an owned node still needs
            # three matching owned readings.
            check()
            # The preceding claim ended on a fresh whole-tree observation.
            # With no intervening input it also identifies the next node. An
            # aged observation is recaptured; ownership still needs 3 reads.
            if index == 0 or time.perf_counter() - observed_at > .08:
                frame, result = observe(allow_transition=True)
            if result['screen'] != 'mad_mike_mastery' or result['nodes'][name]['state'] != 'available':
                frame, result = wait_state(name, {'available','owned'})
        else:
            frame, result = wait_state(name, {'available','owned'})
        if result['nodes'][name]['state'] == 'owned':
            print(f"{name}: already owned")
            continue
        if any(result['nodes'][prior[0]]['state'] != 'owned' for prior in NODES[:index]):
            raise RuntimeError("Earlier mastery node is not confirmed owned")
        # Navigate from an identified node. Mouse hover is not reliable in the
        # game and its pointer can obscure the interior used for ownership.
        selected_observation = False
        for attempt in range(8):
            if attempt or not fast:
                frame, result = observe()
            selected = result['selection']['name']
            if selected == name:
                selected_observation = True
                break
            origin = next((node for node in NODES if node[0] == selected), None)
            if origin is None:
                raise RuntimeError(f'{name}: current mastery selection is ambiguous; no input sent')
            _, sx, sy, _ = origin
            direction = 'left' if x < sx else 'right' if x > sx else 'up' if y < sy else 'down'
            check()
            try:
                timing(running,'input',direction)
                pyautogui.keyDown(direction)
                timed_sleep(running,.06)
            finally:
                pyautogui.keyUp(direction)
            timed_sleep(running,.07 if fast else .2)
        # Claim only after the exact caption and available interior stabilize.
        deadline, stable = time.monotonic()+3, 0
        while time.monotonic() < deadline:
            # Navigation just captured the selected caption and interior.
            # Count it once as the first proof, then capture the remaining
            # fresh proofs. Never reuse a frame taken before a direction key.
            if fast and selected_observation and time.perf_counter() - observed_at <= .08:
                check()
            else:
                frame, result = observe()
            selected_observation = False
            chosen = result['selection']['name'] == name
            available = result['nodes'][name]['state'] == 'available'
            stable = stable+1 if chosen and available else 0
            if stable >= 3:
                timing(running,'finish')
                break
            timed_sleep(running,poll)
        else:
            selection = result['selection']
            raise RuntimeError(
                f"{name}: selected node was not verified "
                f"(best={selection['best_candidate']}, score={selection['score']:.4f}, "
                f"margin={selection['margin']:.4f})")
        check()
        # Exactly one key press. Always release the key, including on F7.
        try:
            timing(running,'input','claim '+name)
            pyautogui.keyDown('enter')
            timed_sleep(running,.06)
        finally:
            pyautogui.keyUp('enter')
        print(f"{name}: Enter sent once; verifying ownership")
        frame, result = wait_state(name, {'owned'})
        print(f"{name}: owned")
    # The last node already has three fresh owned readings, including when
    # resumed as owned. Check that same final observation's entire path.
    if not result['mastery_path_owned']:
        raise RuntimeError("Final mastery path verification failed")
    print("MASTERY COMPLETE: Super Wheelspin node owned (your accepted reward check).")


def live(recognizer, monitor_number, title, timeout, mastery=False, purchase=False, count=1, locate=False):
    import keyboard
    import mss

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
    running = Event()
    # Hotkey callbacks only change the flag; captures/inputs stay in one thread.
    start_key = keyboard.add_hotkey("f6", running.set)
    stop_key = keyboard.add_hotkey("f7", running.clear)
    batch = PurchaseBatch(count)
    ledger = PurchaseLedger()
    if locate:
        print('GARAGE LOOKUP: open My Cars, then F6. F7 stops.')
        print('Selects Recently Added, uses its jump shortcut, and saves screenshots without entering a car.')
    elif purchase:
        ledger.ready()
        print('PURCHASE LOOP: open Car Collection with the Mad Mike Mazda card visible.')
        if count:
            print(f'Target: {count} cars, up to {count * 95000:,} CR.')
        else:
            print('Continuous buying: 95,000 CR per car until F7 or a failure.')
        print('F6 starts/resumes; F7 stops. Ctrl+C exits.')
    elif mastery:
        print("SINGLE MASTERY TEST: open the correct car's mastery screen first.")
        print("F6 claims up to six nodes (21 points total); F7 stops. Ctrl+C exits.")
    else:
        print("READ ONLY: F6 starts observing; F7 stops. Ctrl+C exits. No game inputs.")
    previous = None
    unknown_since = None
    failures = BASE / "failures"
    try:
        # MSS is created and used in this same thread.
        with mss.mss() as capture:
            if monitor_number < 1 or monitor_number >= len(capture.monitors):
                raise ValueError("Requested monitor does not exist")
            monitor = capture.monitors[monitor_number]
            while True:
                if not running.is_set():
                    previous, unknown_since = None, None
                    time.sleep(.1)
                    continue
                frame = np.asarray(capture.grab(monitor))[:, :, :3].copy()
                result = recognizer.inspect(frame)
                failure = None
                if title.casefold() not in foreground_title().casefold():
                    failure = "Game is not focused"
                elif frame.shape[:2] != (1080, 1920):
                    failure = "Expected a 1920 x 1080 monitor capture"
                elif locate:
                    try:
                        locate_recent_car(recognizer,capture,monitor,title,running)
                    except MasteryStopped as exc:
                        print(str(exc))
                    except Exception as exc:
                        failure = str(exc)
                        frame = np.asarray(capture.grab(monitor))[:,:,:3].copy()
                        result = recognizer.inspect(frame)
                    finally:
                        running.clear()
                elif purchase:
                    try:
                        batch.run(recognizer,capture,monitor,title,running,ledger)
                    except MasteryStopped as exc:
                        print(str(exc))
                    except Exception as exc:
                        failure = str(exc)
                        frame = np.asarray(capture.grab(monitor))[:,:,:3].copy()
                        result = recognizer.inspect(frame)
                    finally:
                        running.clear()
                elif mastery:
                    try:
                        mastery_once(recognizer, capture, monitor, title, running)
                    except MasteryStopped as exc:
                        print(str(exc))
                    except Exception as exc:
                        failure = str(exc)
                        frame = np.asarray(capture.grab(monitor))[:, :, :3].copy()
                        result = recognizer.inspect(frame)
                    finally:
                        running.clear()
                elif result["screen"] == "unknown":
                    unknown_since = unknown_since or time.monotonic()
                    if time.monotonic() - unknown_since >= timeout:
                        failure = "Unrecognized screen timed out"
                else:
                    unknown_since = None
                signature = (result["screen"], tuple(
                    (k, v["state"]) for k,v in result.get("nodes", {}).items()))
                if signature != previous:
                    print(json.dumps(result))
                    previous = signature
                if failure:
                    running.clear()
                    failures.mkdir(exist_ok=True)
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    path = failures / f"recognition_{stamp}.png"
                    cv2.imwrite(str(path), frame)
                    path.with_suffix(".json").write_text(json.dumps(
                        {"failure": failure, **result}, indent=2), encoding="utf-8")
                    print(f"STOPPED: {failure}. Screenshot: {path}")
                time.sleep(.2)
    finally:
        keyboard.remove_hotkey(start_key)
        keyboard.remove_hotkey(stop_key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--gui', action='store_true', help='Open the desktop dashboard (default)')
    source.add_argument("--image", type=Path)
    source.add_argument("--video", type=Path)
    source.add_argument("--live", action="store_true")
    source.add_argument("--mastery", action="store_true", help="Explicit single mastery test; sends Enter")
    source.add_argument('--purchase',action='store_true',help='Buy Mazdas from the visible collection card')
    source.add_argument('--locate-car',action='store_true',help='Test Recently Added garage navigation; no car entry')
    source.add_argument('--resolve-purchase',choices=['bought','not-bought'],
                        help='Record your manual check of an uncertain purchase; sends no inputs')
    parser.add_argument("--report", type=Path, default=BASE / "video_review" / "recognition.jsonl")
    parser.add_argument("--monitor", type=int, default=1)
    parser.add_argument("--game-title", default="Forza Horizon 6")
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument('--count',type=int,default=None,
                        help='Purchase limit (default 1); 0 buys continuously until F7 or a failure')
    args = parser.parse_args()
    if args.gui or not any((args.image, args.video, args.live, args.mastery,
                           args.purchase, args.locate_car, args.resolve_purchase)):
        from fh6.gui import main as gui_main
        gui_main()
        return
    if args.timeout <= 0 or not args.game_title.strip():
        parser.error("Timeout and game title must be valid")
    if args.count is not None and (not args.purchase or args.count < 0):
        parser.error('--count requires --purchase and must be zero or greater')
    if args.resolve_purchase:
        PurchaseLedger().resolve(args.resolve_purchase)
        return
    recognizer = Recognizer()
    if args.image:
        print(json.dumps(recognizer.inspect(cv2.imread(str(args.image))), indent=2))
    elif args.video:
        inspect_video(recognizer, args.video, args.report)
    else:
        live(recognizer, args.monitor, args.game_title, args.timeout, args.mastery, args.purchase,
             1 if args.count is None else args.count, args.locate_car)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped")
