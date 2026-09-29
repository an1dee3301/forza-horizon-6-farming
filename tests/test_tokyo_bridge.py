"""First-class Tokyo Delivery bridge configuration and display checks."""

import importlib.util
from argparse import Namespace
from pathlib import Path

import pytest


PATH = Path("Forza-Horizon-6-Wheelspin-Macro-main/Runtime/bridge.py")
spec = importlib.util.spec_from_file_location("tokyo_bridge_test", PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def args(**changes):
    values = dict(mode="Tokyo Delivery", target="3", points="0", reserve="0",
                  monitor=1, timeout=30, max_restarts=0, steam_backup=1,
                  game_priority=1, resume_goal_id="", spin_type="SUPER",
                  dry_run=1, stop_on_unknown=1)
    values.update(changes)
    return Namespace(**values)


def test_delivery_uses_saved_target_and_normal_worker_configuration():
    config = bridge.configuration(args(), {}, {}, {})
    assert config["mode"] == bridge.TOKYO_DELIVERY_MODE
    assert config["limit"] == 3
    assert config["monitor"] == 1
    assert config["steam_backup"] is True
    checkpoint = {"mode": "Tokyo Delivery", "phase": "active", "limit": 3}
    assert bridge.configuration(args(), {}, {}, checkpoint)["limit"] == 3
    with pytest.raises(ValueError, match="saved shift target"):
        bridge.configuration(args(target="4"), {}, {}, checkpoint)


@pytest.mark.parametrize("target", ["0", "10001", "1.5", "bad"])
def test_delivery_rejects_invalid_shift_count(target):
    with pytest.raises(ValueError):
        bridge.configuration(args(target=target), {}, {}, {})


def test_delivery_does_not_overlap_saved_farming_or_car_work():
    with pytest.raises(ValueError, match="farming mission"):
        bridge.configuration(args(), {}, {"phase": "farm", "limit": 2}, {})
    with pytest.raises(ValueError, match="saved Mad Mike"):
        bridge.configuration(args(), {"phase": "mastery", "limit": 2}, {}, {})
    with pytest.raises(ValueError, match="Resume the saved Tokyo Delivery"):
        bridge.configuration(args(mode="Wheelspin Lab"), {}, {},
                             {"phase": "active", "limit": 3})


def test_delivery_status_uses_verified_shift_counters(tmp_path):
    status = bridge.Status(tmp_path / "status.ini")
    status.event("progress", dict(mode="Tokyo Delivery", id="example",
                                  phase="active", completed=1, limit=3,
                                  active_seconds=12, bought=0, rewards=0,
                                  farm_runs=0))
    status.event("stage", "tokyo_active")
    status.write(ok=1)
    assert status.data["completed"] == 1
    assert status.data["remaining"] == 2
    assert status.data["window_left"] == "UNTIL SHIFTS / F7"
    assert status.data["stage"] == "Tokyo Delivery — drive the route"
    assert "1 / 3 verified shifts" in status.data["analytics_header"]
