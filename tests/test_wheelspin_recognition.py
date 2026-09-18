import numpy as np
import pytest

from fh6.wheelspin_recognition import (classify_reward_text, stable_rewards,
                                       slot_boxes)


def test_credit_and_non_car_rewards_are_classified():
    assert classify_reward_text("175,000 CR")["reward_type"] == "CREDITS"
    assert classify_reward_text("BLACK LEATHER JACKET")["reward_type"] == "CLOTHING"
    assert classify_reward_text("")["reward_type"] == "UNKNOWN"


def test_protected_car_requires_exact_three_field_match():
    result = classify_reward_text("2015 KOENIGSEGG ONE:1")
    assert result["reward_type"] == "CAR"
    assert result["protected"] is True
    assert result["year"] == 2015
    assert result["manufacturer"] == "Koenigsegg"
    partial = classify_reward_text("KOENIGSEGG ONE:1")
    assert partial["protected"] is None
    assert partial["classification_confidence"] < .97


def test_three_matching_observations_are_required():
    rows = [[{"normalized_text": "50 000 CR"}] * 3 for _ in range(3)]
    assert stable_rewards(rows, 3) == rows[-1]
    rows[-1][0] = {"normalized_text": "100 000 CR"}
    with pytest.raises(RuntimeError, match="stable"):
        stable_rewards(rows, 3)


def test_slot_geometry_is_complete_for_each_spin_type():
    assert len(slot_boxes("SUPER")) == 3
    assert len(slot_boxes("REGULAR")) == 1
    for box in slot_boxes("SUPER") + slot_boxes("REGULAR"):
        x, y, w, h = box
        assert 0 <= x < 1920 and 0 <= y < 1080 and x + w <= 1920 and y + h <= 1080

