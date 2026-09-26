from types import SimpleNamespace
import pytest
from fh6.refill_control import decision


PROFILE = SimpleNamespace(share_code='155439962', duration_seconds=917)
FARMS = [dict(share_code=PROFILE.share_code, before_sp=0, after_sp=350,
              gained_sp=350, drive_seconds=917, exit_reason='natural_completion')]*3


def test_small_remaining_target_uses_full_run_when_no_car_is_funded():
    result = decision(6, 273, FARMS, PROFILE, early_exit_disabled=True)
    assert result['planned_exit'] == 'natural_completion'
    assert result['planned_drive_seconds'] == 917


def test_full_run_still_rejected_when_reserve_leaves_insufficient_headroom():
    with pytest.raises(RuntimeError):
        decision(900, 999, FARMS, PROFILE, reserve=900, early_exit_disabled=True)


def test_funded_balance_is_converted_without_full_refill():
    result = decision(700, 987, FARMS, PROFILE, early_exit_disabled=True)
    assert result['mode'] == 'convert'
