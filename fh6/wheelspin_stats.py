"""Scientific, explicitly empirical Wheelspin Lab statistics."""
from math import pow
from collections import Counter

from .wheelspin_catalog import (EXCLUSIVE_CARS, PRIORITY_TARGETS,
                                NAMED_KEEP_ALIASES, named_keep_target,
                                lamborghini_candidate, lamborghini_model_name,
                                identify_exclusive)


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
    for row in store.db.execute("""SELECT raw_ocr,timestamp FROM rewards
        WHERE reward_type='CAR' AND wheelspin_exclusive=1"""):
        match = identify_exclusive(row["raw_ocr"])
        if match is None:
            continue
        key = match.car.identity
        hit = observed.setdefault(key, dict(count=0, first_seen=None, last_seen=None))
        hit["count"] += 1
        stamp = row["timestamp"]
        hit["first_seen"] = min(hit["first_seen"], stamp) if hit["first_seen"] else stamp
        hit["last_seen"] = max(hit["last_seen"], stamp) if hit["last_seen"] else stamp
    rows = []
    for car in EXCLUSIVE_CARS:
        hit = observed.get(car.identity, {})
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
                exclusives=exclusive_rows(store), retention=retention_counts(store))


def retention_counts(store):
    """Count observed pulls by user keep policy, independently of catalog flags."""
    named = Counter({name: 0 for name in NAMED_KEEP_ALIASES})
    models = Counter()
    lamborghinis = 0
    for row in store.db.execute("""SELECT raw_ocr,display_name,manufacturer,model
        FROM rewards WHERE reward_type='CAR'"""):
        text = " ".join(str(row[key] or "") for key in row.keys())
        target = named_keep_target(text)
        if target:
            named[target] += 1
        if lamborghini_candidate(text):
            lamborghinis += 1
            models[lamborghini_model_name(text) or "Unknown model"] += 1
    return dict(named=dict(named), lamborghini_total=lamborghinis,
                lamborghini_models=dict(sorted(models.items())))
