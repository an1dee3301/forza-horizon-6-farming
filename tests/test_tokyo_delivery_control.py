import pytest


pytest.importorskip('vgamepad')

from fh6.tokyo_delivery_control import GuardedPad


def test_worker_stop_neutralizes_virtual_pad():
    class Stopped(Exception):
        pass

    class FakeGame:
        def foreground_matches(self, identity):
            return True

        def sync_windows(self):
            return []

    class FakePad:
        def __init__(self):
            self.resets = 0
            self.updates = 0

        def reset(self):
            self.resets += 1

        def update(self):
            self.updates += 1

    guarded = GuardedPad.__new__(GuardedPad)
    guarded.game = FakeGame()
    guarded.identity = ('one-bound-process',)
    guarded.pad = FakePad()
    guarded.guard = lambda: (_ for _ in ()).throw(Stopped())

    with pytest.raises(Stopped):
        guarded.check()

    assert guarded.pad.resets == 1
    assert guarded.pad.updates == 1
