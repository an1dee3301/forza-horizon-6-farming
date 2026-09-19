from dataclasses import dataclass

from fh6.farm_setup import FarmSetupChecks


@dataclass
class Profile:
    share_code: str = '155439962'


def test_abnormal_yield_forces_full_setup_check_once(tmp_path):
    checks = FarmSetupChecks('mission', lambda: 'same-game', tmp_path / 'setup.json')
    profile = Profile()
    called = []

    def full():
        called.append('full')

    def video():
        called.append('video')

    assert checks.ensure(profile, full, video) == 'full'
    assert checks.ensure(profile, full, video) == 'cached'
    checks.invalidate_full()
    assert checks.ensure(profile, full, video) == 'full'
    assert checks.ensure(profile, full, video) == 'cached'
    assert called == ['full', 'full']


def test_full_invalidation_does_not_touch_another_mission(tmp_path):
    path = tmp_path / 'setup.json'
    owner = FarmSetupChecks('owner', lambda: 'same-game', path)
    profile = Profile()
    owner.ensure(profile, lambda: None, lambda: None)
    FarmSetupChecks('other', lambda: 'same-game', path).invalidate_full()
    assert owner.reusable(profile)
