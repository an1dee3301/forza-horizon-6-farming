# Upgrades Back settling trial — 26 September 2026

A 0.35-second wait before Back was tested on eight paid-car returns, followed by eight normal-timing cars in the same batch. The trial ended automatically after car eight.

| Measurement | Trial | Normal timing |
|---|---:|---:|
| Cars completed | 8 | 8 |
| Complete cohort wall time | 445.673 s | 421.387 s |
| Median complete cycle | 54.661 s | 52.280 s |
| Median full return stage | 11.853 s | 12.403 s |
| Upgrades Back retries | 0 | 5 |
| Failed attempts | 0 | 0 |

**Decision: not promoted.** The changed transition needed fewer retries, but the complete conversion cohort did not improve. Normal timing remains active.

This small sequential comparison is not causal proof that the added wait slowed the full cycle: initial setup and unrelated menu delays also differ. Cohort wall time includes gaps between cars; return timings include the added wait and retries. Exact Back-function timing was emitted only for the trial and is not used as a matched control comparison.

These are conversion measurements, not saved Super Wheelspins/hour. Full farming, recovery and final cleanup time must be included in native-inventory qualification. The 33/hour target remains unverified.

Aggregate data: [JSON](upgrades-back-trial-20260926.json). No account identifiers, purchase receipts, or runtime screenshots are published here.
