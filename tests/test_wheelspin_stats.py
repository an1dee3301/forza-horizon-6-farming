from fh6.wheelspin_history import WheelspinStore
from fh6.wheelspin_stats import empirical_upper_bound_zero, exclusive_rows, retention_counts


def test_zero_hit_upper_bound_uses_observed_denominator():
    assert empirical_upper_bound_zero(0) is None
    assert 0 < empirical_upper_bound_zero(1500) < .01


def test_exclusive_table_contains_all_45_even_with_zero_hits(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    rows = exclusive_rows(store)
    assert len(rows) == 45
    assert all(row["count"] == 0 for row in rows)
    sesto = next(row for row in rows if row["car"] == "2011 Lamborghini Sesto Elemento")
    assert sesto["observed_rate"] == 0
    assert sesto["upper_95_per_reward_slot"] is None


def test_keep_counters_include_named_targets_and_lamborghini_models(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", True, True)
    spin = store.start_spin(session, 1, "SUPER")
    rows = [
        dict(slot_index=1, reward_type="CAR", raw_ocr="M-B CLK-GTR"),
        dict(slot_index=2, reward_type="CAR", raw_ocr="Essenza SCV12"),
        dict(slot_index=3, reward_type="CAR", raw_ocr="1993 NISSAN 240SX"),
    ]
    for row in rows:
        row.update(normalized_text="", classification_confidence=.9,
                   full_screen_path="full.png", slot_crop_path="slot.png")
    store.commit_rewards(spin, rows)
    counts = retention_counts(store)
    assert counts["named"]["CLK GTR"] == 1
    assert counts["lamborghini_total"] == 1
    assert counts["lamborghini_models"]["Essenza SCV12"] == 1
    assert counts["named"]["ONE:1"] == 0


def test_exclusive_stats_use_immutable_card_not_mutated_dialog_identity(tmp_path):
    store = WheelspinStore(tmp_path / "lab.sqlite")
    session = store.start_session(1, "SUPER", True, True)
    spin = store.start_spin(session, 1, "SUPER")
    rows = [dict(slot_index=1, reward_type="CAR",
                 raw_ocr="2011 LAMBORGHINI SESTO ELEMENTO",
                 year=2011, manufacturer="Lamborghini", model="Sesto Elemento",
                 wheelspin_exclusive=True, retain=True),
            dict(slot_index=2, reward_type="CREDITS", raw_ocr="50,000 CR"),
            dict(slot_index=3, reward_type="CREDITS", raw_ocr="50,000 CR")]
    for row in rows:
        row.update(normalized_text="", classification_confidence=.9,
                   full_screen_path="full.png", slot_crop_path="slot.png")
    store.commit_rewards(spin, rows)
    car = store.rewards(spin)[0]
    store.associate_duplicate(spin, car["reward_id"], dict(year=None,
        manufacturer=None, model="LAMBO SESTO", display_name="LAMBO SESTO",
        retain=True), 1.0, "dialog.png")
    sesto = next(r for r in exclusive_rows(store)
                 if r["car"] == "2011 Lamborghini Sesto Elemento")
    assert sesto["count"] == 1
