from fh6.wheelspin_history import WheelspinStore
from fh6.wheelspin_stats import empirical_upper_bound_zero, exclusive_rows


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

