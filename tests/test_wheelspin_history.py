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
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="2018 PORSCHE 911 GT2 RS",
        display_name="PORSCHE 911 GT2 RS", year=2018, manufacturer="PORSCHE",
        model="911 GT2 RS", duplicate=True, retain=False,
        wheelspin_exclusive=True, decision_confidence=.99), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    with pytest.raises(AssertionError, match="decision"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL", "PORSCHE 911 GT2 RS")
    store.plan_decision(spin, car["reward_id"], "SELL", .99)
    store.assert_action_allowed(spin, car["reward_id"], "SELL", "PORSCHE 911 GT2 RS")


def test_protected_or_unknown_car_can_never_be_sold(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="2011 LAMBORGHINI SESTO ELEMENTO",
        year=2011, manufacturer="LAMBORGHINI", model="SESTO ELEMENTO",
        duplicate=True, retain=True, decision_confidence=.999), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "KEEP", .999)
    with pytest.raises(AssertionError, match="protected"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL")


def test_restart_cannot_repeat_verified_sell(tmp_path):
    path = tmp_path / "lab.sqlite"
    store = WheelspinStore(path)
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="2018 PORSCHE 911 GT2 RS",
        display_name="PORSCHE 911 GT2 RS", year=2018, manufacturer="PORSCHE",
        model="911 GT2 RS", duplicate=True, retain=False,
        decision_confidence=.99), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", .99)
    store.action_attempted(spin, car["reward_id"], "SELL", "PORSCHE 911 GT2 RS")
    store.action_verified(spin, car["reward_id"], "SELL")
    reopened = WheelspinStore(path)
    with pytest.raises(AssertionError, match="already verified"):
        reopened.assert_action_allowed(spin, car["reward_id"], "SELL", "PORSCHE 911 GT2 RS")


def test_sesto_and_nevera_baseline_ownership_never_creates_pull_rows(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    assert store.global_stats()["exclusive_pulls"] == 0
    assert store.global_stats()["policy_keep_pulls"] == 0
    assert store.global_stats()["protected_sold"] == 0
    assert store.global_stats()["protected_retained"] == 0


def test_destructive_interlock_blocks_abbreviated_keep_alias_even_if_flag_is_wrong(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="MERCEDES-BENZ AMG CLK GTR",
        model="M-B CLK-GTR", duplicate=True, retain=False,
        decision_confidence=1.0), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError, match="keep-list"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL", "M-B CLK-GTR")


@pytest.mark.parametrize("name", [
    "1998 SUBARU IMPREZA 22B-STI VERSION", "SUBARU 22B", "IMPREZA 22B", "22B",
])
def test_destructive_interlock_blocks_both_subaru_22b_copies_by_alias(tmp_path, name):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr=name,
        duplicate=True, retain=True, decision_confidence=1.0), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "KEEP", 1.0)
    with pytest.raises(AssertionError, match="protected"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL", name)


def test_destructive_interlock_blocks_lamborghini_even_when_flash_hides_gold(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="2022 LAMBORGHINI HURACAN",
        card_color="NEUTRAL", duplicate=True, retain=False,
        decision_confidence=1.0), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError, match="keep-list"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL", "HURACAN")


def test_destructive_interlock_blocks_model_only_lamborghini(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="Essenza SCV12",
        model="Essenza SCV12", duplicate=True, retain=False,
        decision_confidence=1.0), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError, match="keep-list"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL", "Essenza SCV12")


def test_other_unresolved_protected_card_blocks_sell(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="2010 FORD Focus RS",
        manufacturer="FORD", model="Focus RS", duplicate=True,
        display_name="FORD Focus RS", retain=False, decision_confidence=1.0),
        reward(2, "CAR", raw_ocr="Sesto Elemento", duplicate=True), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError, match="unresolved protected"):
        store.assert_action_allowed(spin, car["reward_id"], "SELL", "FORD Focus RS")


def test_live_dialog_identity_is_independent_final_sell_interlock(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="1993 NISSAN 240SX",
        display_name="NISSAN 240SX", retain=False, wheelspin_exclusive=True,
        duplicate=True), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError, match="current duplicate"):
        store.action_attempted(spin, car["reward_id"], "SELL", "LAMBO SESTO")
    with pytest.raises(AssertionError, match="current duplicate dialog changed"):
        store.action_attempted(spin, car["reward_id"], "SELL", "NISSAN GT-R")
    store.action_attempted(spin, car["reward_id"], "SELL", "NISSAN 240SX")


def test_partial_card_can_sell_only_with_same_model_and_clear_dialog_maker(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr="Sux 510",
        display_name="DATSUN 510", retain=False, duplicate=True), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    store.assert_action_allowed(spin, car["reward_id"], "SELL", "DATSUN 510")

    other = WheelspinStore(tmp_path / "other.sqlite")
    s2 = other.start_session(1, "SUPER", False, True)
    spin2 = other.start_spin(s2, 1, "SUPER")
    other.commit_rewards(spin2, [reward(1, "CAR", raw_ocr="FORD Mustang",
        display_name="FORD Focus", retain=False, duplicate=True), reward(2), reward(3)])
    car2 = other.rewards(spin2)[0]
    other.plan_decision(spin2, car2["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError, match="shared model"):
        other.assert_action_allowed(spin2, car2["reward_id"], "SELL", "FORD Focus")


def test_legacy_catalog_flag_is_split_from_actual_keep_policy(tmp_path):
    path = tmp_path / "legacy.sqlite"
    store = WheelspinStore(path)
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [
        reward(1, "CAR", raw_ocr="1993 NISSAN 240SX", protected=True,
               wheelspin_exclusive=True),
        reward(2, "CAR", raw_ocr="2011 LAMBORGHINI SESTO ELEMENTO",
               protected=True, wheelspin_exclusive=True),
        reward(3, "CAR", raw_ocr="2013 FERRARI LAFERRARI", protected=True,
               wheelspin_exclusive=True),
    ])
    store.db.close()
    db = sqlite3.connect(path)
    db.execute("ALTER TABLE rewards DROP COLUMN retain")
    db.close()
    reopened = WheelspinStore(path)
    cars = reopened.rewards(spin)
    assert [(r["wheelspin_exclusive"], r["retain"]) for r in cars] == [
        (1, 0), (1, 1), (None, 0)]
    assert reopened.global_stats()["exclusive_pulls"] == 2
    assert reopened.global_stats()["policy_keep_pulls"] == 1


@pytest.mark.parametrize("name", [
    "M-B CLK-GTR", "Mercedes-Benz AMG CLK GTR", "Koenigsegg One:1",
    "ONE 1", "Hennessey Venom GT", "VENOM GT", "Rimac Nevera",
    "NEVERA", "Apollo IE", "Intensa Emozione",
    "Ferrari 599XX Evolution", "599XX Evo", "Sesto Elemento",
    "Centenario", "Murcielago", "Huracan Tecnica", "Essenza SCV12",
    "Countach", "Aventador", "Diablo GTR", "LAMBORGHINI UNKNOWN",
])
def test_every_keep_alias_is_blocked_at_sell_input_even_if_flag_is_false(tmp_path, name):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", False, True)
    spin = store.start_spin(session, 1, "SUPER")
    store.commit_rewards(spin, [reward(1, "CAR", raw_ocr=name,
        display_name=name, retain=False, duplicate=True), reward(2), reward(3)])
    car = store.rewards(spin)[0]
    store.plan_decision(spin, car["reward_id"], "SELL", 1.0)
    with pytest.raises(AssertionError):
        store.action_attempted(spin, car["reward_id"], "SELL", name)
    assert store.rewards(spin)[0]["action_attempted"] is None
