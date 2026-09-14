"""One-shot cleanup completion handoff: report, then resume with F6."""
import argparse
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def wait_process(pid):
    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if handle:
        try:
            ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    args = parser.parse_args()
    wait_process(args.pid)
    time.sleep(.75)
    data = json.loads((ROOT/'runs/analytics.json').read_text(encoding='utf-8'))
    cleanup = data.get('garage_cleanup') or {}
    if cleanup.get('active') or cleanup.get('error'):
        return 1
    note = f"Garage cleanup complete: {cleanup.get('removed', 0)} confirmed Mad Mike removals. Mission resuming."
    subprocess.run([sys.executable, '-m', 'fh6.discord_reports', '--send', '--note', note],
                   cwd=ROOT, check=False)
    import keyboard
    keyboard.press_and_release('f6')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
