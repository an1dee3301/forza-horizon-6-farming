"""Local AutoHotkey panel adapter for the verified Python game pipeline.

Both panels share the parent's checkpoints, calibration and purchase ledger.
This adapter never implements or sends game inputs itself.
"""
import argparse
import configparser
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
from datetime import datetime, timezone

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE))

from forza_cycle import PurchaseLedger
from fh6.budget import plan_from_sp, whole_number
from fh6.controller import Controller, set_dpi_awareness
from fh6.pipeline import STAGES
from fh6.session import Session
from fh6.telemetry import duration, summary
from fh6.production import GoalSession, MODE as GOAL_MODE
from fh6.profiles import load_profile, save_profile, ChallengeProfile
from fh6.ownership import WorkerLease
from fh6.supervision import validate_resume
from dataclasses import replace
from fh6.wheelspin import MODE as WHEELSPIN_MODE

STAGE_NAMES = dict(STAGES, complete='Complete', inspect_sp='Read actual SP balance', farm='Run Mega V6',
                  farm_prepare='Select the 22B and verify settings', farm_search='Find challenge 155439962',
                  farm_launch='Start the verified challenge', farm_drive='Farm SP — Mega V6',
                  farm_leave='Exit the completed challenge', farm_read_sp='Verify SP earned',
                  farm_return='Return home → Car Collection', game_start='Open game through Steam',
                  game_restart='Restart crashed game', cloud_sync='Waiting for full cloud sync — all actions paused',
                  wheelspin_open='Wheelspin Lab — record rewards')
MODES = (GOAL_MODE, 'Full pipeline', 'Buy only', 'Mastery only', 'Recognition only',
         'Farm SP only', 'Return to collection', 'Check farm setup', WHEELSPIN_MODE, 'Open game')


def configuration(args, saved, goal=None):
    """An unfinished checkpoint always owns the original target and balance."""
    goal = goal or {}
    resume_id = getattr(args, 'resume_goal_id', '')
    if resume_id:
        if args.mode != GOAL_MODE:
            raise ValueError('Automatic worker resume requires the wheelspin target mode')
        validate_resume(goal, resume_id)
    if args.mode == 'Open game':
        result = dict(mode=args.mode, limit=1)
    elif args.mode == GOAL_MODE:
        target = whole_number(args.target, 'Super Wheelspin target')
        reserve = whole_number(args.reserve, 'SP to keep')
        credit_mode=goal.get('credit_limited') is True and goal.get('phase') != 'complete'
        if (not credit_mode and not 1 <= target <= 10000) or reserve > 978:
            raise ValueError('Use a target of 1–10,000 and an SP reserve of 0–978')
        if goal and goal.get('phase') != 'complete':
            if credit_mode:
                target=goal['limit']  # Provisional budget, refreshed from actual credits by the worker.
            if goal.get('starting_spins_counted') and target == goal['limit']+goal['starting_spins_counted']:
                target = goal['limit']
            if target != goal['limit'] or reserve != goal.get('reserve_sp', 0):
                raise ValueError('Resume with the saved wheelspin target and SP reserve')
        result = dict(mode=GOAL_MODE, limit=target, reserve_sp=reserve)
    elif args.mode == WHEELSPIN_MODE:
        if goal and goal.get('phase') != 'complete':
            raise ValueError('Finish or end the saved farming mission before opening saved Wheelspins')
        if saved and saved.get('phase') != 'complete':
            raise ValueError('Finish the saved Mad Mike before starting Wheelspin Lab')
        target = whole_number(args.target, 'Wheelspin quantity')
        if not 1 <= target <= 10000:
            raise ValueError('Use a Wheelspin quantity of 1–10,000')
        result = dict(mode=WHEELSPIN_MODE, limit=target, spin_type=args.spin_type,
                      dry_run=bool(args.dry_run), stop_on_unknown=bool(args.stop_on_unknown))
    elif goal and goal.get('phase') != 'complete' and args.mode != 'Recognition only':
        raise ValueError('Resume or end the saved wheelspin target before running another module')
    elif saved and saved.get('phase') != 'complete':
        if args.mode != 'Recognition only':
            if args.mode != saved['mode']:
                raise ValueError(f"Choose {saved['mode']} to resume this session, or end it after checking the car.")
            result = dict(mode=saved['mode'], limit=saved['limit'])
            if saved.get('skill_points') is not None:
                result.update(skill_points=saved['skill_points'], reserve_sp=saved.get('reserve_sp', 0))
        else:
            result = dict(mode=args.mode, limit=1)
    elif args.mode in ('Full pipeline', 'Buy only'):
        plan = plan_from_sp(args.points, args.reserve)
        if plan.cars < 1:
            raise ValueError('At least 21 spendable SP is required. No run started.')
        result = dict(mode=args.mode, limit=plan.cars)
        if args.mode == 'Full pipeline':
            result.update(skill_points=plan.points, reserve_sp=plan.reserve)
    else:
        result = dict(mode=args.mode, limit=1)
    if args.monitor < 1 or not 2 <= args.timeout <= 120:
        raise ValueError('Use monitor 1 or higher and a timeout between 2 and 120 seconds.')
    restarts = getattr(args, 'max_restarts', 0)
    if type(restarts) is not int or not 0 <= restarts <= 10:
        raise ValueError('Use 0–10 crash restarts per run')
    return dict(result, monitor=args.monitor, timeout=args.timeout, title='Forza Horizon 6',
                steam_backup=args.mode == 'Open game' or bool(getattr(args, 'steam_backup', 1)),
                max_restarts=restarts, game_priority=bool(getattr(args, 'game_priority', 1)),
                resume_goal_id=resume_id)


class Status:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {}
        self.session = {}
        self.active = False
        self.observed = time.monotonic()
        self.analytics_checked = 0

    def event(self, kind, value):
        with self.lock:
            if kind == 'config':
                # Show the requested worker immediately, even while lifecycle
                # or cloud-sync gates run before the mode creates its session.
                self.session = dict(value, completed=0, rewards=0, bought=0,
                                    active_seconds=0, phase='starting', farm_runs=0)
                self.observed = time.monotonic()
            elif kind == 'progress':
                self.session = dict(value)
                self.observed = time.monotonic()
                self.data['goal_pending'] = int(value.get('mode') == GOAL_MODE and value.get('phase') != 'complete')
                self.data['goal_id'] = value.get('id', '') if value.get('mode') == GOAL_MODE else ''
            elif kind == 'activity':
                self.active = value
            elif kind == 'cancelled':
                self.data['cancelled'] = int(value)
            elif kind == 'status':
                self.data['message'] = value
            elif kind == 'stage':
                self.data['stage'] = STAGE_NAMES.get(value, value)
            elif kind == 'screen':
                self.data['screen'] = value.replace('_', ' ')
            elif kind == 'error_image':
                self.data['error_image'] = value

    def write(self, **changes):
        with self.lock:
            self.data.update(changes)
            elapsed = self.session.get('active_seconds', 0)
            if self.active:
                elapsed += time.monotonic() - self.observed
            values = summary(self.session, elapsed)
            points = values['points']
            self.data['run_mode'] = self.session.get('mode', '')
            if self.session.get('mode') == WHEELSPIN_MODE and time.monotonic()-self.analytics_checked >= 1:
                self.analytics_checked = time.monotonic()
                try:
                    from fh6.wheelspin_history import WheelspinStore
                    from fh6.wheelspin_stats import dashboard_data
                    lab = dashboard_data(WheelspinStore(WORKSPACE/'runs/wheelspin_lab.sqlite'))
                    totals, exclusives, retention = lab['totals'], lab['exclusives'], lab['retention']
                    self.data.update(
                        lab_super_spins=totals['super_spins'], lab_regular_spins=totals['regular_spins'],
                        lab_reward_slots=totals['reward_slots'], lab_car_rewards=totals['car_rewards'],
                        lab_duplicates=totals['duplicate_cars'], lab_exclusive_pulls=totals['exclusive_pulls'],
                        lab_sold=totals['cars_sold'], lab_retained=totals['cars_retained'], lab_sell_cr=totals['sell_cr'],
                        analytics_header=(f"WHEELSPIN LAB  •  {totals['super_spins']:,} SWP  •  "
                            f"{totals['reward_slots']:,} slots  •  {totals['car_rewards']:,} cars\n"
                            "Observed empirical rates; garage ownership is never counted as a pull."),
                        analytics_basis="Wheelspin Lab SQLite; every row is committed before duplicate processing.",
                        analytics_overview="~".join([
                            f"Super spins^{totals['super_spins']:,}^Recorded complete",
                            f"Reward slots^{totals['reward_slots']:,}^All reward types",
                            f"Car rewards^{totals['car_rewards']:,}^Observed cards",
                            f"Exclusive pulls^{totals['exclusive_pulls']:,}^Catalog classification",
                            f"Policy keeps^{totals['policy_keep_pulls']:,}^Six named cars + Lamborghinis",
                            f"Keeps verified^{totals['protected_retained']:,}^Verified actions",
                            f"Protected sold^{totals['protected_sold']:,}^Historical errors",
                            f"Cars sold^{totals['cars_sold']:,}^Verified actions",
                            f"Sell CR^{totals['sell_cr']:,}^Known verified offers",
                        ]),
                        analytics_wheelspin="~".join(
                            f"{row['car']}^{row['count']}^{row['first_seen'] or '—'}^{row['last_seen'] or '—'}^"
                            f"{row['pulls_per_100_super_spins']:.3f}" if row['pulls_per_100_super_spins'] is not None else
                            f"{row['car']}^{row['count']}^{row['first_seen'] or '—'}^{row['last_seen'] or '—'}^—"
                            for row in exclusives),
                        analytics_retention="~".join(
                            [f"{name}^{count}^Named KEEP" for name, count in retention['named'].items()] +
                            [f"Lamborghini total^{retention['lamborghini_total']}^All models"] +
                            [f"Lamborghini: {model}^{count}^Model observed"
                             for model, count in retention['lamborghini_models'].items()]),
                    )
                except Exception:
                    self.data['analytics_header'] = 'Wheelspin Lab measurements temporarily unavailable.'
            if self.session.get('mode') == GOAL_MODE and time.monotonic()-self.analytics_checked >= 5:
                self.analytics_checked = time.monotonic()
                try:
                    from fh6.analytics import current, display, panel_data
                    analytics = current(goal=dict(self.session, active_seconds=elapsed))
                    cleanup = analytics.get('garage_cleanup') or {}
                    removed = cleanup.get('removed', 0) if type(cleanup.get('removed', 0)) is int else 0
                    bought = self.session.get('bought', 0)
                    processed = min(bought, self.session.get('rewards', 0))
                    zero_at = cleanup.get('bought_at_verified_empty', 0)
                    removed += max(0, zero_at-cleanup.get('removed_at_verified_empty', removed))
                    verified_zero = bool(cleanup.get('verified_empty') and bought == zero_at)
                    left = max(0, bought-removed)
                    self.data.update(mad_mike_bought=bought, mad_mike_processed=processed,
                                     mad_mike_removed=removed, mad_mike_left=left,
                                     mad_mike_left_prefix='' if verified_zero else '≤')
                    self.data['analytics_text'] = display(analytics).replace('\n', ' | ')
                    self.data.update({k:v.replace('\n',' || ') for k,v in panel_data(analytics).items()})
                    self.data['eta_range'] = f"{analytics['eta_seconds']/3600:.1f}–{analytics['eta_upper_seconds']/3600:.1f} h estimated"
                    from fh6.reporting import read_json
                    from fh6.panel_inventory import inventory_labels
                    proof=read_json(WORKSPACE/'runs/inventory_observed.json')
                    runtime=read_json(WORKSPACE/'runs/report_runtime.json')
                    account=read_json(WORKSPACE/'runs/account_observed.json')
                    self.data.update(inventory_labels(proof, self.session, account, runtime, os.getpid()))
                except Exception:
                    self.data['analytics_text'] = 'Measurements temporarily unavailable; game execution continues.'
            self.data.update(completed=values['completed'], bought=self.session.get('bought', 0),
                             window_left=('UNTIL CREDIT LIMIT / F7' if self.session.get('credit_limited') is True else 'UNTIL TARGET / F7'),
                             rewards=self.session.get('rewards', 0), limit=self.session.get('limit', 0),
                             elapsed=duration(values['elapsed']), eta=duration(values['eta']),
                             spend=f"{values['credits']:,}", percent=round(values['percent']),
                             remaining=values['remaining'] if values['remaining'] is not None else '—',
                             points_left=('≤ ' if values['partial_tree'] else '') + f'{points:,}' if points is not None else '—',
                             phase=self.session.get('phase', ''),
                             farm_runs=self.session.get('farm_runs', 0),
                             pending=int(bool(self.session and self.session.get('phase') != 'complete')))
            if self.session.get('mode') == GOAL_MODE:
                from fh6.target import totals
                total = totals(self.session)
                self.data.update(completed=total['total_progress'], limit=total['total_target'],
                                 percent=round(total['total_percent']), starting_spins=total['starting_spins'])
            parser = configparser.ConfigParser(interpolation=None)
            parser['run'] = {key: str(value).replace('\r', ' ').replace('\n', ' ')
                             for key, value in self.data.items()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            with temp.open('w', encoding='utf-16') as file:
                parser.write(file)
            # IniRead can briefly open the destination without delete sharing.
            # A telemetry refresh must not abort a purchase or held accelerator.
            for attempt in range(20):
                try:
                    os.replace(temp, self.path)
                    break
                except PermissionError:
                    if attempt == 19:
                        return  # Keep the previous atomic snapshot; refresh next tick.
                    time.sleep(.01)


def owner_alive(pid):
    if not pid:
        return True
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


def inspect_session(status, session):
    settings = {}
    path = WORKSPACE/'runs/settings.json'
    if path.exists():
        settings = json.loads(path.read_text(encoding='utf-8'))
    launch_path = WORKSPACE/'runs/launch_settings.json'
    launch = json.loads(launch_path.read_text(encoding='utf-8')) if launch_path.exists() else {}
    data = session.data
    goal = GoalSession(WORKSPACE/'runs/goal.json').data
    goal_pending = bool(goal and goal.get('phase') != 'complete')
    points = settings.get('skill_points', '')
    if data.get('skill_points') is not None:
        points = data['skill_points']
        if data.get('phase') == 'complete':
            points = '' if data.get('end_reason') == 'ended' else max(0, points - data.get('rewards', 0)*21)
    visible = goal if goal_pending else data
    lab = None
    try:
        from fh6.wheelspin_history import WheelspinStore
        lab = WheelspinStore(WORKSPACE/'runs/wheelspin_lab.sqlite').latest_session()
    except Exception:
        pass
    if lab and lab.get('status') == 'RUNNING' and not goal_pending and not (data and data.get('phase') != 'complete'):
        visible = dict(id=lab['session_id'], mode=WHEELSPIN_MODE, phase='running',
                       completed=lab['completed_spins'], rewards=lab['completed_spins'], bought=0,
                       limit=lab['requested_spins'], active_seconds=0, farm_runs=0)
    status.event('progress', visible)
    status.event('stage', visible.get('phase', 'inspect_sp'))
    status.write(input_sp=points, reserve=data.get('reserve_sp', settings.get('reserve_sp', 0)),
                 share_code=load_profile().share_code, challenge_seconds=load_profile().duration_seconds,
                 input_target=goal.get('limit', 10)+goal.get('starting_spins_counted',0), goal_pending=int(goal_pending),
                 goal_reserve=goal.get('reserve_sp', 0),
                 monitor=settings.get('monitor', 1), timeout=settings.get('timeout', 30),
                 steam_backup=int(launch.get('steam_backup', True)), max_restarts=launch.get('max_restarts', 0),
                 game_priority=int(launch.get('game_priority', True)),
                 message='Saved wheelspin target ready to resume.' if goal_pending else
                 'An unfinished car is saved. The target mode will finish it first.' if data and data.get('phase') != 'complete'
                 else 'Enter how many Super Wheelspins to earn, then Start or F6.',
                 error_image='', busy=0, ok=1, history=history_text(session),
                 saved_mode=WHEELSPIN_MODE if lab and lab.get('status') == 'RUNNING' else GOAL_MODE)
    if (WORKSPACE/'runs/cloud_sync.json').exists():
        status.write(stage='Waiting for full cloud sync',
                     message='Cloud sync needs verification. Use Recovery only after confirming it fully completed.')


def history_text(session):
    rows = []
    for record in session.history()[:15]:
        state = 'Ended' if record.get('end_reason') == 'ended' else 'Complete' if record.get('phase') == 'complete' else 'Saved'
        rows.append(f"{record['id'][:8]}  {state}  •  {record['mode']}  •  "
                    f"{record.get('completed', 0)}/{record.get('limit') or '∞'} cycles  •  "
                    f"{record.get('bought', 0)} bought  •  {duration(record.get('active_seconds'))}")
    return ' | '.join(rows) or 'Completed and ended runs will appear here.'


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', type=Path, required=True)
    parser.add_argument('--owner', type=int, default=0)
    parser.add_argument('--action', choices=('inspect', 'run', 'end', 'resolve-bought', 'resolve-not-bought', 'save-profile', 'confirm-sync'), default='inspect')
    parser.add_argument('--mode', choices=MODES, default=MODES[0])
    parser.add_argument('--points', default='')
    parser.add_argument('--target', default='10')
    parser.add_argument('--share-code', default='155439962')
    parser.add_argument('--challenge-seconds', type=int, default=900)
    parser.add_argument('--reserve', default='0')
    parser.add_argument('--spin-type', choices=('SUPER', 'REGULAR'), default='SUPER')
    parser.add_argument('--dry-run', type=int, choices=(0, 1), default=1)
    parser.add_argument('--stop-on-unknown', type=int, choices=(0, 1), default=1)
    parser.add_argument('--monitor', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--steam-backup', type=int, choices=(0, 1), default=1)
    parser.add_argument('--max-restarts', type=int, default=0)
    parser.add_argument('--game-priority', type=int, choices=(0, 1), default=1)
    parser.add_argument('--resume-goal-id', default='')
    args = parser.parse_args(argv)
    status = Status(args.channel/'status.ini')
    controller = None
    hotkey = None
    try:
        session = Session()
        inspect_session(status, session)
        if args.action == 'inspect':
            return 0
        if args.action == 'confirm-sync':
            from fh6.cloud_sync import confirm_current_sync
            confirm_current_sync()
            status.write(message='Your sync confirmation is recorded. Waiting for a stable game screen.')
            return 0
        if args.action != 'run':
            with WorkerLease():
                if args.action == 'save-profile':
                    goal = GoalSession(WORKSPACE/'runs/goal.json')
                    challenge_path = WORKSPACE/'runs/challenge.json'
                    challenge = json.loads(challenge_path.read_text(encoding='utf-8')) if challenge_path.exists() else {}
                    if any(item and item.get('phase') != 'complete' for item in (goal.data, challenge)):
                        raise ValueError('Finish the saved wheelspin target and challenge before changing its profile')
                    save_profile(replace(load_profile(), share_code=args.share_code, duration_seconds=args.challenge_seconds))
                elif args.action == 'end':
                    goal = GoalSession(WORKSPACE/'runs/goal.json')
                    goal.end()
                    session.end()
                else:
                    PurchaseLedger().resolve('bought' if args.action == 'resolve-bought' else 'not-bought')
            inspect_session(status, session)
            if args.action == 'save-profile':
                status.write(message='Challenge profile saved.')
            return 0
        config = configuration(args, session.data, GoalSession(WORKSPACE/'runs/goal.json').data)
        set_dpi_awareness()
        controller = Controller(status.event)
        def stop_mission():
            with status.lock:
                status.data['cancelled'] = 1
            controller.stop()
        # The AHK panel owns the global F7 hotkey and writes the channel stop
        # file. A second low-level Python hook produced phantom F7 events while
        # Forza was rapidly accepting Enter, terminating healthy spin chains.
        if (args.channel/'stop').exists() or not owner_alive(args.owner):
            raise RuntimeError('Start cancelled.')
        launch_path = WORKSPACE/'runs/launch_settings.json'
        launch_path.parent.mkdir(exist_ok=True)
        launch_tmp = launch_path.with_suffix('.tmp')
        launch_tmp.write_text(json.dumps(dict(steam_backup=bool(args.steam_backup),
                                             max_restarts=args.max_restarts, game_priority=bool(args.game_priority))), encoding='utf-8')
        launch_tmp.replace(launch_path)
        status.write(busy=1, ok=1, message='Starting in five seconds. Switch to the game.')
        controller.start(config, delay=5)
        while controller.busy:
            if (args.channel/'stop').exists() or not owner_alive(args.owner):
                stop_mission()
            status.write(log_path=str(controller.log_path or ''))
            time.sleep(.1)
        status.write(busy=0, history=history_text(Session()))
        return 0
    except Exception as exc:
        if controller:
            controller.stop()
        status.write(busy=0, ok=0, message=f'Stopped: {exc}')
        return 1
    finally:
        if controller and controller.thread is not None and controller.thread.is_alive():
            controller.stop()
            controller.thread.join(timeout=7)
        if hotkey is not None:
            keyboard.remove_hotkey(hotkey)


if __name__ == '__main__':
    raise SystemExit(main())
