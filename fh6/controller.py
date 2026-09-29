"""Background worker; UI and global hotkeys never send game inputs themselves."""
import contextlib
import ctypes
import json
import threading
import time
import traceback
from datetime import datetime

import cv2
import numpy as np

import forza_cycle as core
from .navigation import Navigator, NetworkDisconnected
from .ocr import WindowsOCR
from .pipeline import Pipeline
from .session import Session
from .farming import FarmNavigator, Challenge
from .production import Production, GoalSession, MODE as GOAL_MODE
from .ownership import WorkerLease
from .game_lifecycle import GameLifecycle, WindowsGame, reconcile_after_restart
from .cloud_sync import SyncGuard, SyncPending
from .supervision import validate_resume, RetryDelay
from .runtime_limits import RunSignal


class LogSink:
    def __init__(self, emit, file):
        self.emit, self.file, self.pending = emit, file, ''

    def write(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            if line.strip():
                self.emit('log', line)
        return len(text)

    def flush(self):
        self.file.flush()


class Controller:
    def terminal_cleanup(self, nav, emit):
        from .garage_cleanup import GarageCleanup
        from .mad_mike_inventory import prepare_filter
        from .background import BackgroundStream
        stream = self.background
        if stream:
            stream.close()
            self.background = None
        try:
            from .cleanup_removal_journal import RemovalJournal
            cleanup = GarageCleanup(nav, self.analytics, emit=emit)
            had_pending = RemovalJournal(self.analytics).read() is not None
            recovered = cleanup.recover_pending_removal()
            if had_pending:
                garage = {'garage_grid', 'car_action', 'remove_confirmation',
                          'manufacturers', 'no_cars'}
                start = nav.wait(garage | {'collection_grid', 'cars', 'campaign',
                                         'home_tab', 'pause_menu'})
                if start.screen in garage:
                    cleanup.return_to_grid()
            prepare_filter(nav)
            return recovered + cleanup.run(reset_filter_state=True)
        finally:
            if stream:
                self.background = BackgroundStream()

    def __init__(self, emit):
        self.report_feed = None
        self.callback = emit
        self.log_path = None
        self.running = RunSignal()
        self.thread = None
        self._last_failure = None
        self._last_failure_time = 0
        from .failure_evidence import FailureEvidence
        self.failure_evidence = FailureEvidence()
        self.retry_delay = RetryDelay()
        self.analytics = None
        self.performance = None
        self.performance_flushed = 0
        self.background = None
        self.optimization_review_attempted = None

    def emit(self, kind, value):
        observer = getattr(self, 'account_observer', None)
        performance = getattr(self, 'performance', None)
        if performance:
            try:
                # Only timing markers stay on the input thread. Aggregation,
                # snapshots, disk writes, report state and UI callbacks all run
                # on the ordered diagnostics stream below.
                performance.mark_event(kind,value)
            except Exception:
                pass
        if observer:
            try:
                if kind == 'cycle_stage' and value.get('phase') in {'choose', 'return'}:
                    observer.begin_event(f"{value['batch_id']}:{value['cycle']}:{value['phase']}",
                        'Car purchase' if value['phase'] == 'choose' else 'Wheelspin claimed')
                elif kind == 'stage' and value in {'farm_prepare', 'farm_search', 'farm_read_sp'}:
                    challenge = json.loads((core.BASE/'runs/challenge.json').read_text(encoding='utf-8'))
                    observer.begin_event(f"{challenge['id']}:{challenge.get('launch_attempts',0)}:{value}",
                        'Farm result' if value == 'farm_read_sp' else 'Farm preparation')
            except Exception:
                pass  # Account reporting never authorizes or blocks game actions.
        self.retry_delay.observe(kind, value)
        stamp=time.monotonic()
        if self.background:
            import copy
            self.background.submit(self.deliver_event,kind,copy.deepcopy(value),stamp)
        else:
            self.deliver_event(kind,value,stamp)

    def deliver_event(self,kind,value,stamp):
        performance = getattr(self, 'performance', None)
        observer = getattr(self, 'account_observer', None)
        if performance:
            try:
                performance.enrich_event(kind,value)
                if kind in {'cycle_complete','farm_completed','done'} or (
                        kind == 'status' and time.monotonic()-self.performance_flushed >= 10):
                    # deliver_event itself is the background worker. Write the
                    # snapshot here instead of copying it on the game thread.
                    performance.flush(observer,self.background,direct=True)
                    self.performance_flushed = time.monotonic()
            except Exception:
                pass
        if self.analytics:
            try:
                if self.background:
                    self.analytics.data['telemetry_dropped']=self.background.dropped
                self.analytics.event(kind, value,event_time=stamp)
                if self.background:
                    self.refresh_optimization_review(kind)
            except Exception:
                pass  # Analytics must never interrupt game execution.
        if self.report_feed:
            self.report_feed.event(kind, value)
        if self.log_path and kind != 'done':
            with self.log_path.open('a', encoding='utf-8') as log:
                rendered = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
                log.write(f'{datetime.now().isoformat(timespec="milliseconds")} [{kind}] {rendered}\n')
        self.callback(kind, value)

    def refresh_optimization_review(self, kind):
        """Called only on the existing diagnostics stream, after tracking."""
        if not self.background or not self.analytics or kind not in {'status', 'cycle_complete', 'farm_completed', 'done'}:
            return
        now = time.monotonic()
        if self.optimization_review_attempted is not None and now - self.optimization_review_attempted < 60:
            return
        # Throttle attempts as well as successes. A broken diagnostic must not
        # turn each game event into another expensive read or write attempt.
        self.optimization_review_attempted = now
        try:
            from .optimization_review import snapshot
            from .analytics import save
            review = snapshot(self.analytics.root)
            if review.get('primary_inputs_complete') is not True:
                # A locked or incomplete checkpoint is not a new empty mission.
                # Retain the last valid review and its actual freshness stamp.
                return
            save(self.analytics.root / 'optimization_review.json', review)
        except Exception:
            pass  # Keep the prior timestamp; the app will mark it stale.

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, config, delay=0):
        if self.busy:
            return
        self.running.set()
        self.thread = threading.Thread(target=self._worker, args=(dict(config), delay), daemon=True)
        self.thread.start()

    def stop(self):
        self.running.clear()

    def _worker(self, config, delay):
        reader, nav, session = None, None, None
        lease = None
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        folder = core.BASE/'runs'
        folder.mkdir(exist_ok=True)
        self.log_path = folder/f'{stamp}.log'
        try:
            lease = WorkerLease()
            lease.__enter__()
            from .analytics import Tracker
            self.analytics = Tracker()
            from .background import BackgroundStream
            self.background=BackgroundStream()
            from .reporting import RuntimeFeed, AccountObserver
            self.report_feed = RuntimeFeed()
            self.running.configure(GoalSession(core.BASE/'runs/goal.json').data
                                   if config['mode'] == GOAL_MODE else {})
            if config.get('resume_goal_id'):
                validate_resume(GoalSession(core.BASE/'runs/goal.json').data, config['resume_goal_id'])
            with self.log_path.open('a', encoding='utf-8') as logfile, \
                    contextlib.redirect_stdout(LogSink(self.emit, logfile)):
                self.emit('config', config)
                for remaining in range(delay, 0, -1):
                    if not self.running.is_set():
                        raise core.MasteryStopped('Start cancelled')
                    self.emit('status', f'Switch to the game — starting in {remaining}…')
                    # Event.wait cannot wait on an event whose set state means running.
                    import time
                    for _ in range(10):
                        if not self.running.is_set():
                            raise core.MasteryStopped('Start cancelled')
                        time.sleep(.1)
                import mss
                from .input import install_pointer_input
                install_pointer_input()
                reader = WindowsOCR()
                recognizer = core.Recognizer()
                with mss.mss() as capture:
                    number = config['monitor']
                    if not 1 <= number < len(capture.monitors):
                        raise RuntimeError('The selected monitor does not exist')
                    nav = FarmNavigator(recognizer, reader, capture, capture.monitors[number],
                                    config['title'], self.running, config['timeout'], self.emit)
                    nav.worker_run = self.report_feed.data.get('worker_run')
                    from .performance import Performance
                    nav.performance = self.performance = Performance(
                        GoalSession(core.BASE/'runs/goal.json').data.get('id',stamp),
                        stream=self.background)
                    from .account_async import AsyncAccountObserver
                    nav.account_observer = AsyncAccountObserver()
                    self.account_observer = nav.account_observer
                    try:
                        self.account_observer.begin_event(stamp, 'Worker resumed')
                    except OSError:
                        pass
                    from .report_images import ScreenshotCache
                    from .report_secrets import enabled as reports_enabled
                    nav.report_images = ScreenshotCache(enabled=reports_enabled())
                    from .display import DisplayGuard
                    nav.display_guard = DisplayGuard(nav.monitor)
                    lifecycle = GameLifecycle(self.running, self.emit,
                        enabled=config.get('steam_backup', True) and config['mode'] != 'Recognition only',
                        max_restarts=config.get('max_restarts', 0), priority=config.get('game_priority', True))
                    nav.restore_focus = lifecycle.restore_focus
                    from .farm_setup import FarmSetupChecks
                    nav.setup_checks = FarmSetupChecks(stamp, lifecycle.game.identity)
                    sync = SyncGuard(WindowsGame.sync_windows, self.running, self.emit)
                    nav.sync_guard = lifecycle.sync_guard = sync
                    lifecycle.display_guard = nav.display_guard
                    def input_guard():
                        sync.check()
                        nav.display_guard.check()
                    self.running.input_guard = input_guard
                    self.running.performance = self.performance
                    pending_crash = None
                    while self.running.is_set():
                        try:
                            if pending_crash is not None:
                                lifecycle.recover(pending_crash, nav)
                                pending_crash = None
                            else:
                                lifecycle.ensure(nav, bring_to_front=config['mode'] == 'Open game')
                            if config['mode'] not in {'Recognition only', 'Open game'}:
                                sync.require_verified(lifecycle.game.identity())
                            if config['mode'] == GOAL_MODE:
                                from .garage import FilterReader
                                FilterReader().validate()
                            if lifecycle.path.exists() and config['mode'] not in {
                                    'Recognition only', 'Open game', 'Tokyo Delivery'}:
                                reconcile_after_restart(nav, core.PurchaseLedger(), Session(),
                                    Challenge(nav, emit=self.emit), GoalSession(core.BASE/'runs/goal.json'))
                                lifecycle.path.unlink()
                            self.emit('status', 'Running')
                            if config['mode'] != 'Recognition only':
                                from .keyboard_layout import ensure_game_keyboard
                                ensure_game_keyboard(nav)
                                if config['mode'] != 'Tokyo Delivery':
                                    # Wake the idle garage camera without selecting a menu item.
                                    nav.key('shift')
                                    nav.pause(.3)
                            if config['mode'] == 'Recognition only':
                                while self.running.is_set():
                                    obs = nav.observe()
                                    self.emit('screen', obs.screen)
                                    self.emit('status', f'Recognition only: {obs.screen} — no inputs')
                                    nav.pause(.5)
                                self.emit('status', 'Recognition stopped')
                            elif config['mode'] == 'Open game':
                                self.emit('status', 'Game is open — saved run has not been started')
                            elif config['mode'] == 'Wheelspin Lab':
                                from .wheelspin import WheelspinLab
                                self.emit('activity', True)
                                WheelspinLab(nav, self.running, self.emit).run(
                                    config['limit'], config.get('spin_type', 'SUPER'),
                                    config.get('dry_run', True), config.get('stop_on_unknown', True))
                            elif config['mode'] == 'Tokyo Delivery':
                                from .tokyo_delivery import TokyoDelivery
                                pending = Session().data
                                if pending and pending.get('phase') != 'complete':
                                    raise RuntimeError('Finish the saved car before starting Tokyo Delivery')
                                self.emit('activity', True)
                                TokyoDelivery(nav, self.running, self.emit).run(config['limit'])
                                break
                            elif config['mode'] == GOAL_MODE:
                                session = GoalSession(core.BASE/'runs'/'goal.json')
                                validate_resume(session.data, config.get('resume_goal_id'))
                                session.start_goal(config['limit'], config.get('reserve_sp', 0))
                                from .credit_stop_floor import configure as configure_credit_floor
                                configure_credit_floor(session, config.get('credit_floor'),
                                    account=getattr(nav.account_observer, 'gamertag', None))
                                from .credit_stop_floor import configure_cleanup
                                configure_cleanup(session, config.get('cleanup_policy'))
                                nav.setup_checks.run_id = session.data['id']
                                self.emit('activity', True)
                                Production(nav, core.PurchaseLedger(), session, Session(),
                                             Challenge(nav, emit=self.emit), self.emit,
                                             terminal_cleaner=self.terminal_cleanup).run()
                                self.emit('status', 'Credit reserve protected — Mad Mike cleanup complete; farming stopped'
                                    if session.data.get('end_reason') == 'credit_stop_floor' else
                                    'Credit limit reached — next Mazda is unaffordable; earned Super Wheelspins remain saved'
                                    if session.data.get('end_reason') == 'insufficient_credits' else
                                    'Target complete — Super Wheelspins earned and saved; Car Collection is ready')
                            elif config['mode'] == 'Farm SP only':
                                pending = Session().data
                                if pending and pending.get('phase') != 'complete':
                                    raise RuntimeError('Finish the saved car before changing to the farm car')
                                core.PurchaseLedger().ready()
                                challenge = Challenge(nav, emit=self.emit)
                                identifier = challenge.data.get('id') if challenge.data.get('phase') != 'complete' else None
                                points = challenge.run(identifier or f'{stamp}_farm')
                                self.emit('status', f'Farm complete — {points} SP verified; returned to Car Collection')
                            elif config['mode'] == 'Return to collection':
                                nav.return_collection()
                                self.emit('status', 'Car Collection is ready')
                            elif config['mode'] == 'Check farm setup':
                                from .profiles import load_profile
                                profile = load_profile()
                                nav.ensure_home()
                                nav.verify_farm_settings()
                                self.emit('status', f'Mega V6 assist and Skills HUD settings verified. Use a fully upgraded, max-mastery 1998 22B.')
                            elif config['mode'] == 'Mastery only':
                                self.emit('stage', 'mastery')
                                core.mastery_once(recognizer, capture, nav.monitor, nav.title, self.running)
                                self.emit('status', 'Mastery complete')
                            else:
                                session = Session()
                                session.start(config['mode'], config['limit'], config.get('skill_points'), config.get('reserve_sp', 0))
                                self.emit('activity', True)
                                Pipeline(nav, core.PurchaseLedger(), session, self.emit).run()
                                self.emit('status', 'Finished — returned to Car Collection')
                            break
                        except Exception as exc:
                            nav.garage_filters_clear = False
                            nav.garage_recent_sort_verified = False
                            if not isinstance(exc,(core.MasteryStopped,SyncPending)):
                                self.emit('failure',dict(message=str(exc),stage=self.performance.stage if self.performance else 'unknown'))
                            if session is not None:
                                session.pause()
                                self.emit('progress', dict(session.data))
                            self.emit('activity', False)
                            if config['mode'] == 'Tokyo Delivery':
                                from .tokyo_delivery import DeliveryInputUncertain
                                from .session import CheckpointCorrupt
                                if isinstance(exc, (DeliveryInputUncertain, CheckpointCorrupt)):
                                    raise
                            if isinstance(exc, SyncPending):
                                # Unwind any held driving/mastery key before waiting.
                                # This does not enter the crash/retry path or its timer.
                                lifecycle.wait_sync(nav)
                                pending_crash = None
                                continue
                            if not isinstance(exc, core.MasteryStopped):
                                failure_stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                                self._save_failure(exc, traceback.format_exc(), failure_stamp, config, nav)
                            if lifecycle.is_crash(exc):
                                lifecycle.mark_recovery(exc)
                                if lifecycle.max_restarts and lifecycle.restarts >= lifecycle.max_restarts:
                                    raise RuntimeError(f'Crash restart limit reached ({lifecycle.max_restarts}). Progress saved. Last error: {exc}') from exc
                                pending_crash = exc
                                continue
                            if isinstance(exc, NetworkDisconnected):
                                self.emit('status', 'Network disconnected — entering verified Horizon Solo and resuming the saved step')
                                try:
                                    nav.recover_disconnect()
                                    self.retry_delay.reset()
                                    self.emit('log', 'Network disconnect recovered without restarting the game.')
                                except NetworkDisconnected as recovery_exc:
                                    seconds = min(5, self.retry_delay.next())
                                    self.emit('status', f'Network still unavailable — retrying recovery in {seconds}s. F7 stops.')
                                    self.emit('log', str(recovery_exc))
                                    lifecycle.pause(seconds)
                                continue
                            if str(exc).startswith('Game focus lost') and lifecycle.restore_focus():
                                self.emit('log', 'Game priority restored focus; resuming the saved stage')
                                continue
                            if (isinstance(exc, RuntimeError) and
                                    not isinstance(exc, core.MasteryStopped) and
                                    config['mode'] in {GOAL_MODE, 'Wheelspin Lab', 'Tokyo Delivery'}):
                                seconds = self.retry_delay.next()
                                self.emit('status', f'Retrying saved step in {seconds}s (attempt {self.retry_delay.attempts}): {exc}. F7 stops.')
                                self.emit('log', 'Retry keeps the durable checkpoint; it never repeats a committed reward or clears an uncertain transaction.')
                                lifecycle.pause(seconds)
                                continue
                            raise

        except core.MasteryStopped as exc:
            self.emit('status', str(exc))
        except Exception as exc:
            self.emit('status', f'Stopped: {exc}')
            self.emit('log', f'ERROR: {exc}')
            self.emit('traceback', traceback.format_exc())
        finally:
            self.running.clear()
            try:
                if session is not None:
                    session.pause()
                    self.emit('progress', dict(session.data))
            except Exception as exc:
                self.emit('log', f'Could not save final run timing: {exc}')
            self.emit('activity', False)
            try:
                account = getattr(self, 'account_observer', None)
                if account and hasattr(account, 'close'):
                    account.close()
                if reader:
                    reader.close()
            finally:
                if lease:
                    lease.__exit__()
                self.emit('done', None)
                if self.performance:
                    if self.background:
                        self.background.submit(self.performance.flush,
                            getattr(self,'account_observer',None),self.background,True)
                    else:
                        self.performance.flush(getattr(self,'account_observer',None),None)
                if self.background:
                    self.background.close()
                    self.background=None

    def _save_failure(self, exc, trace, stamp, config, nav):
        # Capturing diagnostics must never replace the error that stopped inputs.
        observation = getattr(exc, 'failed_observation', None)
        source = 'exception_observation' if observation is not None else 'last_observation'
        if observation is None:
            observation = nav.last
        signature = (type(exc).__name__, str(exc), observation.screen if observation else None)
        if signature == self._last_failure and time.monotonic()-self._last_failure_time < 300:
            self.emit('log', f'Repeated failure (previous screenshot retained): {exc}')
            return
        report = dict(error=str(exc), traceback=trace, config=config,
                      image_source=source,
                      last_screen=observation.screen if observation else None,
                      last_observation_text=[])
        try:
            report['session'] = Session().data
            frame = None
            if observation is None:
                # No original observation exists (for example capture failed
                # before the first menu). Label any later screenshot honestly.
                report['image_source'] = 'post_error_capture'
                try:
                    frame = np.asarray(nav.capture.grab(nav.monitor))[:, :, :3]
                except Exception as diagnostic_error:
                    report['diagnostic_error'] = str(diagnostic_error)
            path = core.BASE/'failures'/f'pipeline_{stamp}.png'
            if self.failure_evidence.submit(path, report, observation=observation,
                    frame=frame, stream=self.background, emit=self.emit):
                self._last_failure, self._last_failure_time = signature, time.monotonic()
        except Exception as diagnostic_error:
            self.emit('log', f'Could not save error details: {diagnostic_error}')


def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
