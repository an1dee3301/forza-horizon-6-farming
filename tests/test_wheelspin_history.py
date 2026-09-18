import sqlite3

import pytest

from fh6.wheelspin_history import WheelspinStore


def reward(slot=1, reward_type="CREDITS", **changes):
    value = dict(slot_index=slot, reward_type=reward_type, raw_ocr="50,000 CR",
                 normalized_text="50 000 cr", classification_confidence=.99,
                 full_screen_path="full.png", slot_crop_path=f"slot_{slot}.png")
    value.update(changes)
    return value


def test_super_and_regular_spins_commit_every_slot(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(2, "SUPER", True, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1), reward(2), reward(3)])
    assert store.spin(spin)["rewards_committed"] == 1
    assert len(store.rewards(spin)) == 3

    regular = store.start_spin(session, 2, "REGULAR")
    with pytest.raises(ValueError, match="exactly 1"):
        store.commit_rewards(regular, [reward(1), reward(2)])


def test_non_car_and_unknown_rewards_are_retained(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", True, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1), reward(2, "CLOTHING", raw_ocr="JACKET"),
                                reward(3, "UNKNOWN", raw_ocr="")])
    assert [row["reward_type"] for row in store.rewards(spin)] == ["CREDITS", "CLOTHING", "UNKNOWN"]


def test_destructive_action_requires_durable_rewards_and_committed_decision(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    with pytest.raises(AssertionError, match="reward screen"):
        store.assert_action_allowed(spin, 1, "SELL")
    store.commit_rewards(spin, [reward(1, "CAR", year=2018, manufacturer="PORSCHE",
        model="911 GT2 RS", duplicate=True, protected=False, decision_confidence=.99), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    with pytest.raises(AssertionError, match="decision"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL")
    store.plan_decision(spin, car["reward_id"], "SELL", .99)
    store.assert_action_allowed(spin, car["reward_id"], "SELL")


def test_protected_or_unknown_car_can_never_be_sold(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", year=2011, manufacturer="LAMBORGHINI",
        model="SESTO ELEMENTO", duplicate=True, protected=True, decision_confidence=.999), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "KEEP", .999)
    with pytest.raises(AssertionError, match="protected"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL")


def test_restart_cannot_repeat_verified_sell(tmp_path):
    path = tmp_path / "lab.sqlite"
    store = WheelspinStore(path)
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", year=2018, manufacturer="PORSCHE",
        model="911 GT2 RS", duplicate=True, protected=False, decision_confidence=.99), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", .99)
    store.action_attempted(spin, car["reward_id"], "SELL")
    store.action_verified(spin, car["reward_id"], "SELL")
    reopened = WheelspinStore(path)
    with pytest.raises(AssertionError, match="already verified"):
        reopened.assert_action_allowed(spin, car["reward_id"], "SELL")


def test_sesto_and_nevera_baseline_ownership_never_creates_pull_rows(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    assert store.global_stats()["protected_exclusive_pulls"] == 0


def test_destructive_interlock_blocks_abbreviated_keep_alias_even_if_flag_is_wrong(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="MERCEDES-BENZ AMG CLK GTR",
        model="M-B CLK-GTR", duplicate=True, protected=False,
        decision_confidence=1.0), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError, match="keep-list"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL")


def test_destructive_interlock_blocks_lamborghini_even_when_flash_hides_gold(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="2022 LAMBORGHINI HURACAN",
        card_color="NEUTRAL", duplicate=True, protected=False,
        decision_confidence=1.0), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError, match="Lamborghini"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL")
