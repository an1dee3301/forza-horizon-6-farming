"""Bounded live checks for the application's navigation modules, with F7 stop."""
import argparse
import json
import time
from datetime import datetime
from threading import Event

import cv2
import keyboard
import mss
import forza_cycle as core
from .controller import set_dpi_awareness
from .farming import FarmNavigator
from .navigation import LEFT
from .ocr import WindowsOCR
from .ownership import WorkerLease
from .cloud_sync import SyncGuard, SyncPending
from .game_lifecycle import WindowsGame, GameLifecycle


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['inspect', 'startup', 'sync', 'sp', 'mastery-menu', 'menu-speed', 'route-speed', 'cycle-speed', 'finish-cycle', 'garage', 'filter', 'recent', 'recover', 'farm-car', 'farm-settings', 'video-settings', 'collection', 'cleanup-mad-mike', 'verify-mad-mike-empty'])
    p.add_argument('--baseline', action='store_true', help='Use prior menu pacing for a comparison benchmark')
    args = p.parse_args()
    set_dpi_awareness()
    from .input import install_pointer_input
    install_pointer_input()
    run = Event()
    run.set()
    from .reporting import RuntimeFeed, AccountObserver
    feed = RuntimeFeed()
    def emit(kind, value):
        feed.event(kind, value)
        print(kind, value, flush=True)
    hotkey = keyboard.add_hotkey('f7', run.clear)
    reader = WindowsOCR()
    output = core.BASE/'runs'/'live_checks'
    output.mkdir(exist_ok=True)
    stem = output/datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        with WorkerLease(), mss.mss() as cap:
            nav = FarmNavigator(core.Recognizer(), reader, cap, cap.monitors[1], 'Forza Horizon 6', run,
                                emit=emit)
            nav.account_observer = AccountObserver()
            from .report_images import ScreenshotCache
            from .report_secrets import enabled as reports_enabled
            nav.report_images = ScreenshotCache(enabled=reports_enabled())
            feed.event('activity', True)
            feed.event('status', 'Bounded validation: '+args.action)
            nav.fast_navigation = not args.baseline
            if args.baseline:
                import pyautogui
                pyautogui.PAUSE = .05
            nav.sync_guard = SyncGuard(WindowsGame.sync_windows, run)
            from .display import DisplayGuard
            if args.action not in {'inspect', 'sync'}:
                nav.display_guard = DisplayGuard(nav.monitor)
            def input_guard():
                nav.sync_guard.check()
                if nav.display_guard:
                    nav.display_guard.check()
            run.input_guard = input_guard
            try:
                if args.action == 'startup':
                    lifecycle = GameLifecycle(run, emit=emit)
                    lifecycle.sync_guard = nav.sync_guard
                    try:
                        lifecycle.ensure(nav, bring_to_front=True)
                    except SyncPending:
                        lifecycle.wait_sync(nav)
                        lifecycle.ensure(nav, bring_to_front=True)
                    nav.sync_guard.require_verified(lifecycle.game.identity())
                elif args.action == 'sync':
                    lifecycle = GameLifecycle(run, emit=lambda k,v: print(k,v,flush=True))
                    lifecycle.sync_guard = nav.sync_guard
                    lifecycle.wait_sync(nav)
                    nav.sync_guard.require_verified(lifecycle.game.identity())
                elif args.action != 'inspect':
                    nav.sync_guard.require_verified(WindowsGame().identity())
                    nav.key('shift')
                    import pyautogui
                    nav.check()
                    pyautogui.moveTo(nav.monitor['left']+1810, nav.monitor['top']+970)
                    nav.pause(.3)
                    initial = nav.observe()
                    print('Initial OCR:', [(l.text, l.box) for l in initial.doc.lines], flush=True)
                    cv2.imwrite(str(stem.with_name(stem.name+'_start').with_suffix('.png')), initial.frame)
                if args.action == 'garage':
                    nav.home_tab('cars')
                    nav.click_label('cars', 'My Cars', LEFT)
                    nav.wait('garage_grid', previous='cars')
                elif args.action == 'cleanup-mad-mike':
                    from .analytics import Tracker
                    from .garage_cleanup import GarageCleanup
                    GarageCleanup(nav, Tracker(), emit=emit).run()
                elif args.action == 'verify-mad-mike-empty':
                    from .analytics import Tracker
                    from .mad_mike_inventory import verify_zero
                    print('MAD MIKE INVENTORY:', verify_zero(nav, Tracker()), flush=True)
                elif args.action in {'finish-cycle', 'cycle-speed'}:
                    from .session import Session
                    from .pipeline import Pipeline, ledger_data
                    from .production import GoalSession, Production
                    cars = Session()
                    goal = GoalSession(core.BASE/'runs/goal.json')
                    ledger = core.PurchaseLedger()
                    data, record = cars.data, ledger_data(ledger)
                    if data.get('mode') != 'Full pipeline' or \
                            (goal.data.get('batch') or {}).get('id') != data.get('id'):
                        raise RuntimeError('No matching saved mission car to finish')
                    if args.action == 'cycle-speed':
                        funding = data.get('funding', {})
                        batch = goal.data['batch']
                        idle = data.get('phase') == 'collection' or (data.get('phase') == 'buy' and
                            record.get('id') == data.get('purchase_before') and
                            record.get('status') in {'confirmed', 'resolved_bought'})
                        if not idle or \
                                data.get('bought') != data.get('completed') or \
                                data.get('rewards') != data.get('completed') or \
                                funding.get('goal_id') != goal.data.get('id') or \
                                funding.get('points') != 999 or \
                                data['completed'] >= min(data['limit'], funding.get('count', 0),
                                    batch.get('completed_start', 0)+batch.get('cycles', 0)) or \
                                goal.data['rewards'] >= goal.data['limit']:
                            raise RuntimeError('One-cycle timing requires a funded, idle, unfinished mission batch')
                        ledger.ready()
                        if nav.observe().screen == 'collection_detail':
                            nav.key('esc')
                            nav.wait('collection_grid', previous='collection_detail')
                        points = nav.available_sp()
                        if points < 21+goal.data.get('reserve_sp', 0):
                            raise RuntimeError('Insufficient verified SP for the one-cycle test')
                        nav.return_collection()
                    elif data.get('phase') == 'buy':
                        if not record.get('id') or record['id'] == data.get('purchase_before') or \
                                record.get('status') not in {'pending', 'confirmed', 'resolved_bought'}:
                            raise RuntimeError('No existing purchase attempt; this check never starts a new buy')
                    elif data.get('phase') not in {'bought', 'choose', 'open_mastery', 'mastery', 'return'} or \
                            data.get('bought') != data.get('completed', 0)+1:
                        raise RuntimeError('No single purchased car is awaiting completion')
                    goal.start_goal(goal.data['limit'], goal.data.get('reserve_sp', 0))
                    cars.start(data['mode'], data['limit'])
                    timings, stage = {}, [None, time.perf_counter()]
                    def report(kind, value):
                        if kind == 'stage':
                            now = time.perf_counter()
                            if stage[0] is not None:
                                timings[stage[0]] = timings.get(stage[0], 0)+now-stage[1]
                            stage[:] = [value, now]
                        if kind != 'progress':
                            emit(kind, value)
                    production = Production(nav, ledger, goal, cars, None, emit=report)
                    try:
                        started = time.perf_counter()
                        Pipeline(nav, ledger, cars, production.car_event).run(max_cycles=1)
                        print('CYCLE CHECK SECONDS:', time.perf_counter()-started, flush=True)
                        print('STAGE SECONDS:', json.dumps(timings), flush=True)
                    finally:
                        production.sync()
                        cars.pause()
                        goal.pause()
                elif args.action == 'filter':
                    nav.wait('garage_grid')
                    nav.key('y')
                    nav.wait('garage_filter', previous='garage_grid')
                elif args.action == 'sp':
                    print('VERIFIED SP:', nav.available_sp(), flush=True)
                elif args.action == 'mastery-menu':
                    # Navigation-only timing check: never claims a node or buys.
                    nav.ensure_home()
                    nav.home_tab('cars')
                    nav.click_label('cars', 'Upgrades & Tuning', LEFT)
                    nav.wait('upgrades', previous='cars')
                    started = time.monotonic()
                    nav.prefer_keyboard = False
                    nav.click_label('upgrades', 'Car Mastery', LEFT)
                    obs = nav.wait({'mad_mike_mastery', 'car_mastery'}, previous='upgrades')
                    print('POINTER MASTERY MENU SECONDS:', round(time.monotonic()-started, 3), flush=True)
                    from .points import read_points
                    print('UNCHANGED SP:', read_points(reader, obs.frame), flush=True)
                    nav.prefer_keyboard = True
                    nav.return_collection()
                elif args.action == 'farm-car':
                    from .profiles import load_profile
                    nav.select_farm_car(load_profile())
                elif args.action == 'route-speed':
                    # Time the real reversible menus. Never enter a different
                    # car, purchase, or claim; leave the current car's tree open
                    # so an unfinished choose checkpoint remains resumable.
                    from .garage import set_favorites
                    before = nav.available_sp()
                    nav.return_collection()
                    samples = {}
                    started = time.perf_counter()
                    nav.my_cars()
                    set_favorites(nav, False)
                    nav.key('x')
                    nav.wait('sort_selection', previous='garage_grid')
                    nav.click_label('sort_selection', 'Recently Added')
                    nav.wait('garage_grid', previous='sort_selection',
                             predicate=lambda o: o.doc.has('Jump to Recently Added', contains=True))
                    nav.key('backspace')
                    obs = nav.wait({'garage_grid', 'recent_jump'})
                    if obs.screen == 'recent_jump':
                        nav.click_label('recent_jump', 'All Cars', (250,250,1410,650))
                        nav.wait('garage_grid', previous='recent_jump')
                    samples['collection_to_recent_cars'] = time.perf_counter()-started
                    started = time.perf_counter()
                    after = nav.available_sp()
                    samples['garage_to_mastery_and_sp_read'] = time.perf_counter()-started
                    if before != after:
                        raise RuntimeError('SP changed during navigation-only benchmark')
                    started = time.perf_counter()
                    nav.return_collection()
                    samples['mastery_to_collection'] = time.perf_counter()-started
                    print('ROUTE SECONDS:', json.dumps(samples), flush=True)
                    print('ROUTE TOTAL:', sum(samples.values()), flush=True)
                    # Restore the unchanged current-car tree after the timed route.
                    if nav.available_sp() != before:
                        raise RuntimeError('SP changed while restoring the current-car tree')
                    print('UNCHANGED SP:', before, flush=True)
                elif args.action == 'menu-speed':
                    # Bounded navigation only: never enter a car, buy or claim.
                    nav.return_collection()
                    nav.home_tab('cars')
                    nav.click_label('cars', 'My Cars', LEFT)
                    nav.wait('garage_grid', previous='cars')
                    nav.key('x')
                    nav.wait('sort_selection', previous='garage_grid')
                    started = time.monotonic()
                    nav.prefer_keyboard = False
                    nav.click_label('sort_selection', 'Recently Added')
                    nav.wait('garage_grid', previous='sort_selection',
                             predicate=lambda o: o.doc.has('Jump to Recently Added', contains=True))
                    print('POINTER SORT MENU SECONDS:', round(time.monotonic()-started, 3), flush=True)
                    nav.prefer_keyboard = True
                    nav.return_collection()
                    nav.key('backspace')
                    nav.wait('manufacturers', previous='collection_grid')
                    started = time.monotonic()
                    nav.prefer_keyboard = False
                    nav.click_label('manufacturers', 'Mazda', (250, 255, 1410, 650))
                    nav.wait('collection_grid', previous='manufacturers',
                             predicate=lambda o: len(o.result.get('mazda_candidates', [])) == 1)
                    print('POINTER MAZDA MENU SECONDS:', round(time.monotonic()-started, 3), flush=True)
                    nav.prefer_keyboard = True
                elif args.action == 'recent':
                    nav.wait('garage_grid')
                    nav.key('x')
                    nav.wait('sort_selection', previous='garage_grid')
                    nav.click_label('sort_selection', 'Recently Added')
                    nav.wait('garage_grid', previous='sort_selection')
                    nav.key('backspace')
                    obs = nav.wait({'garage_grid', 'recent_jump'})
                    if obs.screen == 'recent_jump':
                        nav.click_label('recent_jump', 'All Cars')
                        nav.wait('garage_grid', previous='recent_jump')
                elif args.action == 'recover':
                    nav.recover_recent_mazda()
                elif args.action == 'farm-settings':
                    nav.ensure_home()
                    nav.verify_farm_settings()
                elif args.action == 'video-settings':
                    # Read-only settings inspection for post-crash diagnostics.
                    # Selecting a category never changes a video setting.
                    obs = nav.observe()
                    if obs.screen != 'settings':
                        nav.ensure_home()
                        nav.home_tab('campaign')
                        nav.click_label('campaign', 'Settings', LEFT)
                    nav.select('Video', LEFT)
                    nav.until(lambda o: o.doc.has('Resolution', contains=True) and
                              o.doc.has('Frame Rate', contains=True), 'video settings')
                elif args.action == 'collection':
                    nav.return_collection()
            finally:
                try:
                    obs = nav.observe()
                except Exception:
                    obs = nav.last
                if obs is not None:
                    cv2.imwrite(str(stem.with_suffix('.png')), obs.frame)
                    report = dict(screen=obs.screen, text=[dict(text=l.text,box=l.box) for l in obs.doc.lines],
                                  recognition=obs.result)
                    stem.with_suffix('.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                    print(stem, flush=True)
    finally:
        import sys
        error = sys.exc_info()[1]
        feed.event('status', 'Stopped: '+str(error) if error else 'Paused after bounded validation: '+args.action)
        feed.event('done', None)
        reader.close()
        keyboard.remove_hotkey(hotkey)


if __name__ == '__main__':
    main()
