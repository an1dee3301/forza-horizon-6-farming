"""Independent Discord reporter and its small rectangular settings window."""
import argparse
import ctypes
import json
import os
import sys
import threading
import time

from . import report_secrets as secrets
from .reporting import (RUNS, DeliveryError, now, payload, read_json, render,
                        report_due, send, snapshot, write_json)


STATE = RUNS/'discord_delivery.json'
FARM_STATE = RUNS/'discord_farm_delivery.json'


def periodic_due(elapsed, interval):
    return elapsed >= max(60, min(3600, int(interval)))


def deliver_farm(data):
    from .farm_notices import farm_due
    saved = read_json(FARM_STATE)
    if not farm_due(data, saved):
        return {'skipped': 'No new verified farm start.'}
    notice = dict(data, report_kind='farm_start', status=data['farm_event']['timer'])
    # A statistical report image is safe here; the last Mazda garage photo
    # belongs exclusively to its reward and is never reused for a farm notice.
    receipt = send(secrets.webhook(), notice)
    keys = saved.get('sent_keys', [])+[data['farm_event']['key']]
    write_json(FARM_STATE, dict(receipt=receipt, sent_keys=keys[-2000:], event=data['farm_event']))
    return receipt


def game_state():
    try:
        from .game_lifecycle import WindowsGame
        identity = WindowsGame().identity()
        return 'running' if identity else 'closed'
    except Exception:
        return 'not verified'


def deliver(data, *, periodic=False):
    previous = read_json(STATE).get('snapshot')
    if not periodic and not report_due(previous, data, 0, 0):
        return {'skipped': 'No newly earned Super Wheelspin; no Discord message sent.'}
    from .report_images import evidence
    garage_image = None
    if periodic:
        data = dict(data, report_kind='status')
        # Reuse the latest approved My Horizon frame for this mission, retaining
        # its original timestamp even while newer rewards are being converted.
        metadata = {}
        garage_image = evidence(goal_id=data['goal_id'], metadata_out=metadata)
        data['game_capture']=metadata if garage_image else {}
    else:
        garage_image = evidence(goal_id=data['goal_id'], earned=data['earned'])
    if garage_image is None and not periodic:
        return {'skipped': 'Waiting for the garage photo for this newly earned wheelspin.'}
    checkpoint = (data.get('account') or {}).get('checkpoint') or {}
    if not periodic and checkpoint and checkpoint.get('status') != 'Verified':
        from datetime import datetime, timezone
        try:
            age = (datetime.now(timezone.utc)-datetime.fromisoformat(garage_image[1])).total_seconds()
            if 0 <= age < 8:
                return {'skipped': 'Waiting for the current account check to finish.'}
        except (TypeError, ValueError):
            pass
    reports = RUNS/'reports'
    reports.mkdir(parents=True, exist_ok=True)
    write_json(reports/'latest.json', data)
    from .inventory_history import remember
    remember(RUNS,data)
    receipt = send(secrets.webhook(), data, game_image=garage_image)
    write_json(STATE, {'receipt': receipt, 'snapshot': data, 'last_attempt': now(), 'error': None})
    return receipt


def watch():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, 'Local\\FH6AutoDiscordReporter')
    if not handle:
        raise RuntimeError('Could not start the Discord reporter')
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        return
    # Charts, compression and account reporting yield CPU to the game/input
    # worker. Keep the requested report cadence; this is scheduling, not a
    # reduction in chart content or freshness requirements.
    try:
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.SetPriorityClass.restype = ctypes.c_int
        kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
    except (AttributeError, OSError):
        pass  # Optional scheduling must never prevent reports.
    saved = read_json(STATE)
    previous = saved.get('snapshot')
    from datetime import datetime
    try:
        last_sent = datetime.fromisoformat(saved['receipt']['sent_at']).timestamp()
    except (KeyError, ValueError):
        last_sent = 0
    retry_at, attempts, last_game_check, game = 0, 0, 0, None
    configured_stamp = None
    try:
        while True:
            try:
                config = secrets.settings()
                stamp = secrets.CONFIG.stat().st_mtime_ns if secrets.CONFIG.exists() else None
                if stamp != configured_stamp:
                    configured_stamp, retry_at = stamp, 0
                current_time = time.time()
                if config.get('enabled') and current_time >= retry_at:
                    if current_time-last_game_check >= 15:
                        game, last_game_check = game_state(), current_time
                    interval = max(60, min(3600, int(config.get('interval_seconds', 60))))
                    periodic = config.get('mode', 'periodic') == 'periodic'
                    # Read/aggregate analytics only when the minute report is due.
                    if periodic and not periodic_due(current_time-last_sent, interval):
                        time.sleep(2)
                        continue
                    data = snapshot(game=game)
                    from .farm_notices import farm_due
                    new_farm = not periodic and farm_due(data, read_json(FARM_STATE))
                    if periodic or (current_time-last_sent >= 30 and (new_farm or report_due(previous, data, current_time-last_sent, interval))):
                        try:
                            receipt = deliver_farm(data) if new_farm else deliver(data, periodic=periodic)
                            if receipt.get('message_id'):
                                if not new_farm:
                                    previous = data
                                last_sent, attempts = current_time, 0
                        except DeliveryError as exc:
                            attempts += 1
                            # Persist only sanitized text; never response bodies or URLs.
                            write_json(STATE, {**read_json(STATE), 'last_attempt': now(), 'error': str(exc)})
                            retry_at = float('inf') if exc.permanent else time.time()+max(
                                exc.retry_after, min(900, 15*2**min(attempts, 6)))
            except Exception:
                try:
                    write_json(STATE, {**read_json(STATE), 'last_attempt': now(),
                        'error': 'Reporter could not read its configuration or checkpoint; game execution is unaffected'})
                except OSError:
                    pass  # A locked error checkpoint must not terminate the reporter.
                retry_at = time.time()+60
            time.sleep(2)
    finally:
        kernel.CloseHandle(handle)


def start_watcher():
    import subprocess
    import forza_cycle as core
    subprocess.Popen([str(core.BASE/'.venv/Scripts/pythonw.exe'), '-m', 'fh6.discord_reports', '--watch'],
                     cwd=core.BASE, creationflags=subprocess.CREATE_NO_WINDOW)


def settings_window():
    import tkinter as tk
    window = tk.Tk()
    window.title('FH6 // DISCORD REPORTS')
    window.configure(bg='#0B1018')
    window.resizable(False, False)
    window.option_add('*Font', 'Consolas 11')
    config = secrets.settings()
    enabled = tk.BooleanVar(value=config.get('enabled', False))
    url = tk.StringVar()
    minutes = tk.StringVar(value=str(config.get('interval_seconds', 60)//60))
    status = tk.StringVar(value='Saved webhook stays private. Leave its field blank to keep it.')
    def text(value, row):
        tk.Label(window, text=value, fg='#E6EDF3', bg='#0B1018', anchor='w').grid(
            row=row, column=0, columnspan=2, padx=22, pady=8, sticky='w')
    text('FH6 // DISCORD REPORTS', 0)
    tk.Checkbutton(window, text='Enable automatic reports', variable=enabled,
        fg='#00C087', bg='#0B1018', selectcolor='#182331', activebackground='#0B1018',
        activeforeground='#00C087').grid(row=1,column=0,columnspan=2,padx=18,sticky='w')
    text('Webhook (encrypted for this Windows user)', 2)
    tk.Entry(window, textvariable=url, show='*', width=64, bg='#182331', fg='white',
        insertbackground='white', relief='solid').grid(row=3,column=0,columnspan=2,padx=22,pady=4)
    text('Report interval in minutes (1–60), including farming and recovery:', 4)
    tk.Entry(window, textvariable=minutes, width=6, bg='#182331', fg='white',
        insertbackground='white', relief='solid').grid(row=5,column=0,padx=22,sticky='w')
    text('Three boards + My Horizon image carousel. Account strip at the top.', 6)
    def save():
        try:
            secrets.configure(url.get() or None, enabled=enabled.get(), interval_seconds=int(minutes.get())*60)
            url.set('')
            start_watcher()
            status.set('Saved. Reporting runs independently of game inputs.')
        except (ValueError, RuntimeError):
            status.set('Check the webhook and interval. Existing settings were kept.')
    def test():
        status.set('Sending current progress and image…')
        def task():
            try:
                receipt = deliver(snapshot(game=game_state()), periodic=True)
                message = receipt.get('skipped') or 'Discord confirmed the message and image.'
            except Exception:
                message = 'Delivery failed. Check the saved webhook and connection.'
            window.after(0, lambda: status.set(message))
        threading.Thread(target=task, daemon=True).start()
    for column, (title, command) in enumerate([('SAVE', save), ('SEND STATUS NOW', test)]):
        tk.Button(window, text=title, command=command, bg='#00C087', fg='#0B1018',
            relief='solid', borderwidth=1, width=25).grid(row=7,column=column,padx=22,pady=12)
    tk.Label(window, textvariable=status, wraplength=640, justify='left', fg='#E6EDF3',
        bg='#0B1018').grid(row=8,column=0,columnspan=2,padx=22,pady=(6,22),sticky='w')
    window.mainloop()


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--configure-stdin', action='store_true')
    mode.add_argument('--send', action='store_true')
    mode.add_argument('--watch', action='store_true')
    mode.add_argument('--settings', action='store_true')
    mode.add_argument('--capture-game', action='store_true')
    parser.add_argument('--note')
    args = parser.parse_args()
    if args.configure_stdin:
        secrets.configure(sys.stdin.read().strip())
        print('Discord webhook encrypted and reports enabled.')
    elif args.send:
        print(json.dumps(deliver(snapshot(game=game_state(), note=args.note), periodic=True)))
    elif args.watch:
        watch()
    elif args.capture_game:
        from .report_images import capture_game_window, store_frame
        frame = capture_game_window()
        if frame is None:
            raise RuntimeError('No verified game-only image was available; desktop was not captured')
        store_frame(frame, now(), source='Verified FH6 window capture')
        print('Verified game-only report screenshot saved.')
    else:
        settings_window()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, (DeliveryError, ValueError, RuntimeError)) else 'Discord reporting failed')
        raise SystemExit(1)
