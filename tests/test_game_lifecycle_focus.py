import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fh6.game_lifecycle import GameLifecycle


def test_startup_overlay_does_not_refocus_or_use_startup_timeout(tmp_path):
    now = [0.0]
    running = threading.Event()
    running.set()
    backend = Mock()
    backend.pids.return_value = [42]
    backend.crashed.return_value = False
    backend.activate.return_value = True
    nav = Mock()
    nav.title = 'Forza Horizon 6'
    nav.observe.return_value = SimpleNamespace(screen='campaign', doc=Mock(), frame=None)
    nav.is_home.side_effect = lambda obs: obs.screen == 'campaign'
    nav.is_roam.return_value = False

    def sleep(seconds):
        now[0] += seconds

    lifecycle = GameLifecycle(
        running, backend=backend, clock=lambda: now[0], sleep=sleep,
        path=Path(tmp_path) / 'recovery.json', startup_timeout=10, priority=True)

    def foreground():
        return 'Steam Sign In' if now[0] < 12 else 'Forza Horizon 6'

    with patch('fh6.game_lifecycle.core.foreground_title', side_effect=foreground):
        lifecycle.wait_ready(nav, launched=False)

    assert now[0] > lifecycle.startup_timeout
    backend.activate.assert_not_called()
    nav.key.assert_not_called()
