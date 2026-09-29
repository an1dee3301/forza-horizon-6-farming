"""Delivery checkpoint copies never become an automatic input rollback."""

import json

import pytest

from fh6.session import CheckpointCorrupt, load_checkpoint, replace_checkpoint


def test_delivery_checkpoint_keeps_previous_copy_but_refuses_corrupt_current(tmp_path):
    destination = tmp_path / "tokyo_delivery.json"
    for completed in (0, 1):
        temporary = tmp_path / f"checkpoint_{completed}.tmp"
        temporary.write_text(json.dumps({"completed": completed}), encoding="utf-8")
        replace_checkpoint(temporary, destination, keep_backup=True)
    backup = destination.with_name(destination.name + ".bak")
    assert load_checkpoint(destination)["completed"] == 1
    assert json.loads(backup.read_text(encoding="utf-8"))["completed"] == 0
    destination.write_text("{broken", encoding="utf-8")
    with pytest.raises(CheckpointCorrupt, match="previous valid copy"):
        load_checkpoint(destination)


def test_missing_delivery_checkpoint_with_backup_requires_reconciliation(tmp_path):
    destination = tmp_path / "tokyo_delivery.json"
    temporary = tmp_path / "checkpoint.tmp"
    temporary.write_text('{"completed": 0}', encoding="utf-8")
    replace_checkpoint(temporary, destination, keep_backup=True)
    destination.unlink()
    with pytest.raises(CheckpointCorrupt, match="missing"):
        load_checkpoint(destination)
