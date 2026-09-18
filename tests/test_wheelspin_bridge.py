import importlib.util
from argparse import Namespace
from pathlib import Path

import pytest


PATH = Path("Forza-Horizon-6-Wheelspin-Macro-main/Runtime/bridge.py")
spec = importlib.util.spec_from_file_location("wheelspin_bridge_test", PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def args(**changes):
    values = dict(mode="Wheelspin Lab", target="500", points="500", reserve="0",
        monitor=1, timeout=30, max_restarts=0, steam_backup=1, game_priority=1,
        resume_goal_id="", spin_type="SUPER", dry_run=1, stop_on_unknown=1)
    values.update(changes)
    return Namespace(**values)


def test_bridge_builds_first_class_500_super_dry_run_config():
    config = bridge.configuration(args(), {}, {})
    assert config["mode"] == "Wheelspin Lab"
    assert config["limit"] == 500
    assert config["spin_type"] == "SUPER"
    assert config["dry_run"] is True
    assert config["stop_on_unknown"] is True


def test_wheelspin_lab_does_not_overlap_unfinished_farming_checkpoint():
    with pytest.raises(ValueError, match="farming mission"):
        bridge.configuration(args(), {}, {"phase": "farm", "limit": 10})

