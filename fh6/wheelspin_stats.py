"""Scientific, explicitly empirical Wheelspin Lab statistics."""
from math import pow

from .wheelspin_catalog import PROTECTED_CARS, PRIORITY_TARGETS


def empirical_upper_bound_zero(denominator, alpha=.05):
    """Exact one-sided binomial upper bound when the observed hit count is zero."""
    if not denominator:
        return None
    return 1 - pow(alpha, 1 / int(denominator))


def exclusive_rows(store):
    totals = store.db.execute("""SELECT
      COUNT(DISTINCT CASE WHEN s.spin_type='SUPER' AND s.status='COMPLETE' THEN s.spin_id END) super_spins,
      COUNT(r.reward_id) reward_slots,
      SUM(r.reward_type='CAR') car_rewards
      FROM spins s LEFT JOIN rewards r ON r.spin_id=s.spin_id""").fetchone()
    denominators = {key: int(totals[key] or 0) for key in totals.keys()}
    observed = {}
    for row in store.db.execute("""SELECT year,manufacturer,model,COUNT(*) count,
        MIN(timestamp) first_seen,MAX(timestamp) last_seen FROM rewards
        WHERE protected=1 GROUP BY year,manufacturer,model"""):
        observed[(row["year"], row["manufacturer"], row["model"])] = dict(row)
    rows = []
    for car in PROTECTED_CARS:
        hit = observed.get((car.year, car.manufacturer, car.canonical_model), {})
        count = int(hit.get("count", 0))
        rows.append(dict(car=car.display_name, count=count, first_seen=hit.get("first_seen"),
            last_seen=hit.get("last_seen"), priority=car.identity in PRIORITY_TARGETS,
            observed_rate=count,
            pulls_per_100_super_spins=(100*count/denominators["super_spins"] if denominators["super_spins"] else None),
            pulls_per_1000_reward_slots=(1000*count/denominators["reward_slots"] if denominators["reward_slots"] else None),
            pulls_per_1000_car_rewards=(1000*count/denominators["car_rewards"] if denominators["car_rewards"] else None),
            upper_95_per_super_spin=(empirical_upper_bound_zero(denominators["super_spins"]) if count == 0 else None),
            upper_95_per_reward_slot=(empirical_upper_bound_zero(denominators["reward_slots"]) if count == 0 else None),
            upper_95_per_car_reward=(empirical_upper_bound_zero(denominators["car_rewards"]) if count == 0 else None)))
    return rows


def dashboard_data(store):
    return dict(label="OBSERVED EMPIRICAL RATES", totals=store.global_stats(),
                exclusives=exclusive_rows(store))

