"""Retry guarded garage cleanup until empty, then report and resume."""
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def cleanup_state():
    try:
        return json.loads((ROOT/'runs/analytics.json').read_text(encoding='utf-8')).get('garage_cleanup') or {}
    except Exception:
        return {}


def main():
    while True:
        result = subprocess.run([sys.executable, '-m', 'fh6.live_check', 'cleanup-mad-mike'], cwd=ROOT)
        state = cleanup_state()
        if result.returncode == 0 and not state.get('active') and not state.get('error'):
            break
        time.sleep(1.0)
    note = f"Garage cleanup complete: {state.get('removed', 0)} confirmed Mad Mike removals. Mission resuming."
    subprocess.run([sys.executable, '-m', 'fh6.discord_reports', '--send', '--note', note],
                   cwd=ROOT, check=False)
    import keyboard
    keyboard.press_and_release('f6')


if __name__ == '__main__':
    main()
